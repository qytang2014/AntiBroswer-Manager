"""WebDAV remote storage backend implementation using asynchronous HTTPX."""

from __future__ import annotations

import datetime
import email.utils
import logging
import os
import re
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

        async with self._client(timeout=120.0) as client:
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

        async with self._client(timeout=180.0) as client:
            if progress_callback:
                progress_callback(10, f"Downloading {remote_filename} from WebDAV...")

            res = await client.get(target_url)
            if res.status_code == 404:
                raise FileNotFoundError(f"Remote file not found: {remote_filename}")
            if res.status_code not in (200, 206):
                raise RuntimeError(f"WebDAV download failed (HTTP {res.status_code}): {res.text[:200]}")

            local_path.write_bytes(res.content)

            if progress_callback:
                progress_callback(100, f"Downloaded {remote_filename} successfully")

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
                    mode = "full" if "-full." in filename else "config"

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
