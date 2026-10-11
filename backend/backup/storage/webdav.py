"""WebDAV remote storage backend implementation using asynchronous HTTPX."""

from __future__ import annotations

import asyncio
import datetime
import email.utils
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urljoin

import httpx

from . import BackupStorage

logger = logging.getLogger("cloakbrowser.manager.backup.webdav")


class WebDAVStorage(BackupStorage):
    """WebDAV storage backend supporting generic WebDAV servers, NAS, and OpenList."""

    def __init__(
        self,
        url: str,
        username: str = "",
        password: str = "",
        remote_path: str = "/antibrowser_backups",
        skip_ssl_verify: bool = False,
    ):
        self.raw_url = url.rstrip("/")
        self.username = username
        self.password = password
        self.remote_path = "/" + remote_path.strip("/") if remote_path.strip("/") else ""
        self.skip_ssl_verify = skip_ssl_verify

    def _client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        auth = (self.username, self.password) if self.username or self.password else None
        return httpx.AsyncClient(
            auth=auth,
            verify=not self.skip_ssl_verify,
            timeout=timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=60.0),
        )

    def _dir_url(self) -> str:
        if not self.remote_path:
            return self.raw_url + "/"
        return f"{self.raw_url}{self.remote_path}/"

    def _file_url(self, filename: str) -> str:
        clean_name = filename.lstrip("/")
        return f"{self._dir_url()}{clean_name}"

    async def _ensure_remote_dir(self, client: httpx.AsyncClient) -> None:
        """Create remote path directories if they do not exist using MKCOL."""
        if not self.remote_path:
            return
        segments = [s for s in self.remote_path.split("/") if s]
        current_path = ""
        for seg in segments:
            current_path += f"/{seg}"
            url = f"{self.raw_url}{current_path}/"
            try:
                res = await client.request("MKCOL", url)
                if res.status_code not in (201, 405, 301, 200):
                    logger.debug("MKCOL %s returned status %d", url, res.status_code)
            except Exception as exc:
                logger.debug("MKCOL %s exception: %s", url, exc)

    async def test_connection(self) -> tuple[bool, str | None]:
        async with self._client(timeout=15.0) as client:
            try:
                # 1. Try PROPFIND on the base URL or dir URL
                res = await client.request(
                    "PROPFIND",
                    self.raw_url + "/",
                    headers={"Depth": "0"},
                )
                if res.status_code in (401, 403):
                    return False, f"Authentication failed (HTTP {res.status_code}): please check username and password"

                # 2. Ensure destination directory can be created or queried
                await self._ensure_remote_dir(client)
                dir_res = await client.request(
                    "PROPFIND",
                    self._dir_url(),
                    headers={"Depth": "0"},
                )
                if dir_res.status_code in (200, 207):
                    return True, None
                if dir_res.status_code in (401, 403):
                    return False, f"Access denied to path '{self.remote_path}' (HTTP {dir_res.status_code})"

                return True, None
            except httpx.ConnectError as exc:
                return False, f"Connection failed: unable to connect to WebDAV server ({exc})"
            except httpx.TimeoutException:
                return False, "Connection timed out connecting to WebDAV server"
            except Exception as exc:
                return False, f"WebDAV connection error: {exc}"

    async def upload_file(
        self,
        local_path: Path,
        remote_filename: str,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> None:
        if not local_path.is_file():
            raise FileNotFoundError(f"Local file not found: {local_path}")

        async with self._client(timeout=None) as client:
            await self._ensure_remote_dir(client)
            dest_url = self._file_url(remote_filename)
            file_size = local_path.stat().st_size

            if progress_callback:
                progress_callback(0, f"Uploading {remote_filename} ({file_size} bytes)...")

            with open(local_path, "rb") as f:
                content = f.read()

            res = await client.put(dest_url, content=content)
            if res.status_code not in (200, 201, 204):
                raise RuntimeError(f"WebDAV upload failed with status {res.status_code}: {res.text[:200]}")

            if progress_callback:
                progress_callback(100, f"Uploaded {remote_filename} successfully")

    async def download_file(
        self,
        remote_filename: str,
        local_path: Path,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        target_url = self._file_url(remote_filename)

        # For small sidecars (.sha256), use a shorter 15s timeout; archives get None
        timeout = 15.0 if remote_filename.endswith(".sha256") else None

        async with self._client(timeout=timeout) as client:
            if progress_callback:
                progress_callback(5, f"正在连接远端存储下载 {remote_filename}...")

            # 1. Probe headers to get exact content-length and check range support
            headers = {"Accept-Encoding": "identity"}
            total_bytes = 0
            accepts_ranges = False

            try:
                head_res = await client.head(target_url, headers=headers)
                if head_res.status_code == 404:
                    raise FileNotFoundError(f"Remote file not found: {remote_filename}")
                if head_res.status_code == 200:
                    cl = head_res.headers.get("content-length")
                    if cl and cl.isdigit():
                        total_bytes = int(cl)
                    accepts_ranges = head_res.headers.get("accept-ranges") == "bytes"
            except FileNotFoundError:
                raise
            except Exception as exc:
                logger.debug("HEAD request failed for %s: %s", target_url, exc)

            # Fallback to PROPFIND if size is unknown
            if total_bytes == 0 and not remote_filename.endswith(".sha256"):
                try:
                    prop_res = await client.request("PROPFIND", target_url, headers={"Depth": "0"})
                    if prop_res.status_code in (200, 207):
                        root = ET.fromstring(prop_res.content)
                        ns = {"d": "DAV:"}
                        length_el = root.find(".//d:getcontentlength", ns) or root.find(".//{DAV:}getcontentlength")
                        if length_el is not None and length_el.text and length_el.text.strip().isdigit():
                            total_bytes = int(length_el.text.strip())
                except Exception:
                    pass

            # 2. If file >= 2MB and server supports ranges, use multi-part concurrent range download
            if accepts_ranges and total_bytes >= 2 * 1024 * 1024:
                try:
                    await self._download_concurrent(
                        client, target_url, remote_filename, local_path, total_bytes, progress_callback
                    )
                    return
                except Exception as exc:
                    logger.warning("Concurrent download failed (%s), falling back to streaming: %s", remote_filename, exc)

            # 3. Standard single-stream download (fallback or for smaller files)
            await self._download_streaming(
                client, target_url, remote_filename, local_path, total_bytes, progress_callback
            )

    async def _download_concurrent(
        self,
        client: httpx.AsyncClient,
        target_url: str,
        remote_filename: str,
        local_path: Path,
        total_bytes: int,
        progress_callback: Callable[[int, str], None] | None = None,
        num_workers: int = 4,
    ) -> None:
        # Pre-allocate output file
        with open(local_path, "wb") as f:
            f.truncate(total_bytes)

        part_size = (total_bytes + num_workers - 1) // num_workers
        downloaded = 0
        lock = asyncio.Lock()
        start_time = time.monotonic()
        last_report_time = start_time
        last_report_bytes = 0

        async def worker(idx: int) -> None:
            nonlocal downloaded, last_report_time, last_report_bytes
            start = idx * part_size
            end = min(total_bytes - 1, (idx + 1) * part_size - 1)
            if start > end:
                return

            req_headers = {"Accept-Encoding": "identity", "Range": f"bytes={start}-{end}"}
            async with client.stream("GET", target_url, headers=req_headers) as res:
                if res.status_code not in (200, 206):
                    raise RuntimeError(f"Range request failed (HTTP {res.status_code})")

                with open(local_path, "r+b") as f_out:
                    f_out.seek(start)
                    async for chunk in res.aiter_bytes(chunk_size=1024 * 256):
                        f_out.write(chunk)
                        async with lock:
                            downloaded += len(chunk)
                            now = time.monotonic()
                            if progress_callback and (now - last_report_time >= 0.35):
                                interval = max(0.001, now - last_report_time)
                                speed = (downloaded - last_report_bytes) / interval
                                last_report_time = now
                                last_report_bytes = downloaded

                                mb_down = downloaded / (1024 * 1024)
                                mb_total = total_bytes / (1024 * 1024)
                                speed_mb = speed / (1024 * 1024)
                                pct = min(99, int((downloaded / total_bytes) * 100))
                                progress_callback(
                                    pct,
                                    f"正在多线程并发下载 {remote_filename}: {mb_down:.1f} MB / {mb_total:.1f} MB ({pct}%) · {speed_mb:.1f} MB/s",
                                )

        await asyncio.gather(*(worker(i) for i in range(num_workers)))

        actual_size = local_path.stat().st_size
        if actual_size != total_bytes:
            raise RuntimeError(f"Download incomplete: expected {total_bytes} bytes but got {actual_size} bytes")

        if progress_callback:
            mb_final = total_bytes / (1024 * 1024)
            progress_callback(100, f"备份包 {remote_filename} 下载完成 ({mb_final:.1f} MB)")

    async def _download_streaming(
        self,
        client: httpx.AsyncClient,
        target_url: str,
        remote_filename: str,
        local_path: Path,
        total_bytes: int,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> None:
        headers = {"Accept-Encoding": "identity"}
        async with client.stream("GET", target_url, headers=headers) as res:
            if res.status_code == 404:
                raise FileNotFoundError(f"Remote file not found: {remote_filename}")
            if res.status_code not in (200, 206):
                body = await res.aread()
                raise RuntimeError(
                    f"WebDAV download failed (HTTP {res.status_code}): {body.decode(errors='replace')[:200]}"
                )

            if total_bytes == 0:
                total_header = res.headers.get("content-length")
                if total_header and total_header.isdigit():
                    total_bytes = int(total_header)

            downloaded = 0
            start_time = time.monotonic()
            last_report_time = start_time
            last_report_bytes = 0

            with open(local_path, "wb") as f:
                async for chunk in res.aiter_bytes(chunk_size=1024 * 512):
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()

                    if progress_callback and (now - last_report_time >= 0.35):
                        interval = max(0.001, now - last_report_time)
                        speed = (downloaded - last_report_bytes) / interval
                        last_report_time = now
                        last_report_bytes = downloaded

                        mb_down = downloaded / (1024 * 1024)
                        speed_mb = speed / (1024 * 1024)

                        if total_bytes > 0:
                            pct = min(99, int((downloaded / total_bytes) * 100))
                            mb_total = total_bytes / (1024 * 1024)
                            progress_callback(
                                pct,
                                f"正在下载 {remote_filename}: {mb_down:.1f} MB / {mb_total:.1f} MB ({pct}%) · {speed_mb:.1f} MB/s",
                            )
                        else:
                            pct = min(95, int(10 + 80 * (1 - (0.9 ** (mb_down / 5)))))
                            progress_callback(
                                pct,
                                f"正在下载 {remote_filename}: 已下载 {mb_down:.1f} MB · {speed_mb:.1f} MB/s",
                            )

            if total_bytes > 0 and downloaded != total_bytes:
                raise RuntimeError(
                    f"Download incomplete: expected {total_bytes} bytes but received {downloaded} bytes."
                )

        if progress_callback:
            mb_final = downloaded / (1024 * 1024)
            progress_callback(100, f"备份包 {remote_filename} 下载完成 ({mb_final:.1f} MB)")

    async def list_backups(self) -> list[dict[str, Any]]:
        import xml.etree.ElementTree as ET

        async with self._client(timeout=30.0) as client:
            await self._ensure_remote_dir(client)
            res = await client.request(
                "PROPFIND",
                self._dir_url(),
                headers={"Depth": "1"},
            )
            if res.status_code not in (200, 207):
                logger.warning("WebDAV list failed with status %d: %s", res.status_code, res.text[:200])
                return []

            try:
                root = ET.fromstring(res.content)
            except Exception as exc:
                logger.warning("Failed to parse WebDAV PROPFIND XML: %s", exc)
                return []

            # Namespace handling
            ns = {"d": "DAV:"}
            # Also catch if server doesn't use standard DAV: prefix
            responses = root.findall(".//d:response", ns) or root.findall(".//{DAV:}response")

            all_entries: dict[str, dict[str, Any]] = {}
            sidecars: dict[str, str] = {}

            for resp in responses:
                href_el = resp.find("d:href", ns) or resp.find("{DAV:}href")
                if href_el is None or not href_el.text:
                    continue
                href = unquote(href_el.text.strip())
                filename = href.rstrip("/").split("/")[-1]

                # Check if it's a directory
                collection_el = (
                    resp.find(".//d:collection", ns)
                    or resp.find(".//{DAV:}collection")
                )
                if collection_el is not None:
                    continue

                # Get size
                length_el = resp.find(".//d:getcontentlength", ns) or resp.find(".//{DAV:}getcontentlength")
                size = int(length_el.text) if length_el is not None and length_el.text and length_el.text.isdigit() else 0

                # Get modified time
                time_el = resp.find(".//d:getlastmodified", ns) or resp.find(".//{DAV:}getlastmodified")
                created_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                if time_el is not None and time_el.text:
                    try:
                        parsed_tuple = email.utils.parsedate_to_datetime(time_el.text)
                        created_iso = parsed_tuple.isoformat()
                    except Exception:
                        pass

                if filename.endswith(".sha256"):
                    base_name = filename[:-7]
                    sidecars[base_name] = href
                elif filename.startswith("antibrowser-backup-") and (
                    filename.endswith(".tar.gz") or filename.endswith(".tar.gz.enc")
                ):
                    is_encrypted = filename.endswith(".enc")
                    mode = "session" if ("-session." in filename or "-full." in filename) else "config"

                    # Try to extract timestamp from filename if available: antibrowser-backup-YYYYMMDD-HHmmss
                    time_match = re.search(r"antibrowser-backup-(\d{8})-(\d{6})", filename)
                    if time_match:
                        try:
                            dt = datetime.datetime.strptime(
                                f"{time_match.group(1)}{time_match.group(2)}",
                                "%Y%m%d%H%M%S",
                            ).replace(tzinfo=datetime.timezone.utc)
                            created_iso = dt.isoformat()
                        except Exception:
                            pass

                    all_entries[filename] = {
                        "name": filename,
                        "size_bytes": size,
                        "created_at": created_iso,
                        "mode": mode,
                        "encrypted": is_encrypted,
                        "checksum": None,
                    }

            # Fetch checksum contents for sidecar files if present
            for base_name, item in all_entries.items():
                if base_name in sidecars:
                    item["checksum"] = "present"

            # Sort descending by creation date
            backups = list(all_entries.values())
            backups.sort(key=lambda x: x["created_at"], reverse=True)
            return backups

    async def delete_file(self, remote_filename: str) -> None:
        async with self._client(timeout=20.0) as client:
            main_url = self._file_url(remote_filename)
            await client.delete(main_url)
            # Try to delete sidecar .sha256 as well
            sidecar_url = self._file_url(remote_filename + ".sha256")
            try:
                await client.delete(sidecar_url)
            except Exception:
                pass

    async def apply_retention(self, retain_count: int) -> list[str]:
        if retain_count <= 0:
            return []
        backups = await self.list_backups()
        if len(backups) <= retain_count:
            return []

        to_delete = backups[retain_count:]
        deleted = []
        for item in to_delete:
            try:
                await self.delete_file(item["name"])
                deleted.append(item["name"])
            except Exception as exc:
                logger.warning("Failed to delete old backup %s: %s", item["name"], exc)
        return deleted
