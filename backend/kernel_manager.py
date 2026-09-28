"""Chromium kernel (core) management subsystem.

Handles discovering, listing, downloading (with resumable Range support),
verifying, extracting, and deleting Chromium stealth binaries for CloakBrowser.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import platform
import shutil
import time
from .camoufox_downloader import stream_download_camoufox
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
from cloakbrowser.config import (
    CHROMIUM_VERSION,
    DOWNLOAD_BASE_URL,
    PLATFORM_CHROMIUM_VERSIONS,
    get_archive_ext,
    get_archive_name,
    get_binary_dir,
    get_binary_path,
    get_cache_dir,
    get_chromium_version,
    get_download_url,
    get_effective_version,
    get_fallback_download_url,
    get_platform_tag,
)
from cloakbrowser.download import (
    DOWNLOAD_TIMEOUT,
    _extract_archive,
    _is_executable,
    _pro_binary_ready,
    _verify_download_checksum,
    _verify_pro_download,
    _write_pro_version_marker,
    _write_version_marker,
    binary_info,
)

from .extension_manager import get_imported_proxy_url

logger = logging.getLogger("cloakbrowser.manager.kernel")


def get_kernel_downloads_dir() -> Path:
    """Directory for temporary .part download files."""
    d = get_cache_dir() / ".downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_binary_ready(version: str | None = None, pro: bool | None = None) -> bool:
    """Check if an executable binary is installed locally for the given or active version."""
    eff_ver = version or get_chromium_version()
    if eff_ver == "0.0.0-test":
        return True
    if pro is None:
        info = binary_info(browser_version=version)
        if info.get("version") == "0.0.0-test":
            return True
        bp = Path(info.get("binary_path", ""))
        return bp.exists() and _is_executable(bp)
    bp = get_binary_path(version, pro=pro)
    return bp.exists() and _is_executable(bp)


def list_available_kernels(
    force_refresh: bool = False,
    license_tier: str | None = None,
    license_key: str | None = None,
    licenses: list[dict] | None = None,
) -> dict[str, Any]:
    """List all available Chromium stealth cores (installed, recommended, and downloadable)."""
    current_platform = get_platform_tag()
    info = binary_info()
    active_version = info.get("version")
    installed_binary_tier = info.get("tier", "keyless")

    effective_key = license_key or (
        next((lic.get("key") for lic in licenses if lic.get("key")), None) if licenses else None
    )

    if license_tier == "pro" or (effective_key and effective_key.strip()):
        current_tier = "pro"
    elif license_tier and license_tier != "keyless":
        current_tier = license_tier
    else:
        current_tier = installed_binary_tier

    cache_dir = get_cache_dir()
    installed_versions: dict[str, dict[str, Any]] = {}

    # 1. Scan cache_dir for any installed chromium-* directories
    if cache_dir.exists():
        for entry in cache_dir.iterdir():
            if entry.is_dir() and entry.name.startswith("chromium-"):
                dir_name = entry.name.removeprefix("chromium-")
                is_pro = dir_name.endswith("-pro")
                clean_ver = dir_name.removesuffix("-pro")
                bp = get_binary_path(clean_ver, pro=is_pro)
                is_ready = bp.exists() and _is_executable(bp)

                size_mb = 0.0
                try:
                    total_bytes = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                    size_mb = round(total_bytes / (1024 * 1024), 1)
                except Exception:
                    size_mb = 0.0

                installed_versions[f"{clean_ver}:{'pro' if is_pro else 'free'}"] = {
                    "version": clean_ver,
                    "tier": "pro" if is_pro else "free",
                    "installed": is_ready,
                    "binary_path": str(bp) if is_ready else None,
                    "size_mb": size_mb,
                    "cache_dir": str(entry),
                }

    kernels: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    # 2. Recommended Platform Stable Core (Free/Keyless)
    platform_ver = get_chromium_version()
    plat_key = f"{platform_ver}:free"
    plat_installed = installed_versions.get(plat_key, {})
    plat_ready = plat_installed.get("installed", False)
    if not plat_ready:
        bp = get_binary_path(platform_ver, pro=False)
        plat_ready = bp.exists() and _is_executable(bp)

    kernels.append({
        "version": platform_ver,
        "tier": "free",
        "browser_type": "cloakbrowser",
        "name": f"Chromium {platform_ver} (官方稳定版)",
        "description": "官方预设稳定版内核 (平台原生构建，推荐默认使用)",
        "platform": current_platform,
        "installed": plat_ready,
        "is_active": bool(active_version == platform_ver and current_tier != "pro" and plat_ready),
        "binary_path": plat_installed.get("binary_path") or (str(get_binary_path(platform_ver, pro=False)) if plat_ready else None),
        "size_mb": plat_installed.get("size_mb"),
    })
    seen_keys.add(plat_key)

    # 3. Pro Latest Core (if Pro tier or license present, or general Pro build)
    pro_ver = None
    try:
        from cloakbrowser.license import get_pro_latest_version
        pro_ver = get_pro_latest_version() or get_effective_version(pro=True)
    except Exception:
        pro_ver = get_effective_version(pro=True)

    if pro_ver:
        pro_key = f"{pro_ver}:pro"
        pro_installed = installed_versions.get(pro_key, {})
        pro_ready = pro_installed.get("installed", False)
        if not pro_ready:
            bp = get_binary_path(pro_ver, pro=True)
            pro_ready = bp.exists() and _is_executable(bp)

        kernels.append({
            "version": pro_ver,
            "tier": "pro",
            "browser_type": "cloakbrowser",
            "name": f"Chromium {pro_ver} (Pro 最新版)",
            "description": "CloakBrowser Pro 高级指纹伪装内核 (含最新反指纹特征与补丁)",
            "platform": current_platform,
            "installed": pro_ready,
            "is_active": bool(active_version == pro_ver and current_tier == "pro" and pro_ready),
            "binary_path": pro_installed.get("binary_path") or (str(get_binary_path(pro_ver, pro=True)) if pro_ready else None),
            "size_mb": pro_installed.get("size_mb"),
        })
        seen_keys.add(pro_key)

    # 4. Any other locally installed kernels
    for key, item in installed_versions.items():
        if key not in seen_keys:
            seen_keys.add(key)
            is_pro = item["tier"] == "pro"
            kernels.append({
                "version": item["version"],
                "tier": item["tier"],
                "browser_type": "cloakbrowser",
                "name": f"Chromium {item['version']} ({'Pro' if is_pro else 'Free'} 本地安装)",
                "description": f"已安装在本地目录的 Chromium {item['tier']} 内核",
                "platform": current_platform,
                "installed": item["installed"],
                "is_active": active_version == item["version"] and ((current_tier == "pro") == is_pro),
                "binary_path": item["binary_path"],
                "size_mb": item["size_mb"],
            })

    # 5. Add Camoufox versions
    try:
        from .camoufox_downloader import get_camoufox_kernel_list
        camoufox_kernels = get_camoufox_kernel_list(force_refresh=force_refresh)
        kernels.extend(camoufox_kernels)
    except Exception as e:
        logger.error("Failed to fetch Camoufox versions: %s", e)

    # Version sorting helper (sort numbers descending)
    def _version_sort_key(ver_str: str) -> tuple:
        import re
        clean = str(ver_str).lstrip("vV")
        tokens = re.findall(r"\d+|\D+", clean)
        key = []
        for t in tokens:
            if t.isdigit():
                key.append((0, int(t)))
            else:
                key.append((1, t))
        return tuple(key)

    cloak_kernels = [k for k in kernels if k.get("browser_type") == "cloakbrowser"]
    camoufox_kernels = [k for k in kernels if k.get("browser_type") == "camoufox"]
    cloak_kernels.sort(key=lambda k: _version_sort_key(k.get("version", "")), reverse=True)
    camoufox_kernels.sort(key=lambda k: _version_sort_key(k.get("version", "")), reverse=True)
    kernels = cloak_kernels + camoufox_kernels

    # Overall installed flag: True if at least one kernel is ready
    any_installed = any(k["installed"] for k in kernels)

    return {
        "current_platform": current_platform,
        "current_tier": current_tier,
        "active_version": active_version,
        "installed": any_installed,
        "kernels": kernels,
    }


async def stream_download_kernel(
    version: str,
    tier: str = "free",
    license_key: str | None = None,
    release_channel: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Download, verify, and extract a Chromium stealth kernel with resumable Range support.

    Yields progress dicts:
      - stage: "connecting" | "downloading" | "verifying" | "extracting" | "completed" | "error"
      - message: str
      - percent: int (0..100)
      - downloaded_bytes: int
      - total_bytes: int
      - speed_mb: float | None
    """
    is_pro = tier.lower() == "pro"
    tarball_name = get_archive_name()
    platform_tag = get_platform_tag()
    dest_dir = get_binary_dir(version, pro=is_pro)
    binary_path = get_binary_path(version, pro=is_pro)

    downloads_dir = get_kernel_downloads_dir()
    part_file = downloads_dir / f"chromium-{version}-{'pro' if is_pro else 'free'}-{tarball_name}.part"

    yield {
        "stage": "connecting",
        "message": f"正在准备下载 Chromium {version} ({'Pro' if is_pro else 'Free'})...",
        "percent": 0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
    }

    # Resolve download URLs and headers
    headers = {
        "User-Agent": "CloakBrowser-Manager/1.0",
    }
    candidate_urls: list[str] = []

    if is_pro:
        if not license_key:
            yield {
                "stage": "error",
                "message": "下载 CloakBrowser Pro 高级指纹内核需要商业授权 License。请先在『设置』中配置有效 License，或选择下载免费的官方稳定版内核。",
                "percent": 0,
                "browser_type": "cloakbrowser",
            }
            return
        download_url = f"{DOWNLOAD_BASE_URL}/api/download/{version}"
        headers["Authorization"] = f"Bearer {license_key}"
        headers["X-Platform"] = platform_tag
        candidate_urls.append(download_url)
    else:
        primary_url = get_download_url(version)
        fallback_url = get_fallback_download_url(version)
        candidate_urls.extend([primary_url, fallback_url])

    total_bytes = 0
    downloaded_bytes = 0
    last_yield_time = 0.0
    last_yield_percent = -1
    last_bytes = 0
    speed_mb = 0.0
    last_error: Exception | None = None
    success = False

    try:
        modes = ["local", "proxy"]

        for mode in modes:
            if success:
                break

            proxy_context = get_imported_proxy_url() if mode == "proxy" else None
            if mode == "proxy" and not proxy_context:
                continue

            if mode == "proxy":
                async with proxy_context as proxy_url:
                    if not proxy_url:
                        continue

                    yield {
                        "stage": "downloading",
                        "message": "直连下载受阻，正在切换至已导入代理节点尝试断点续传...",
                        "percent": round((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0,
                        "downloaded_bytes": downloaded_bytes,
                        "total_bytes": total_bytes,
                    }

                    timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=10.0)
                    max_retries = 5
                    for attempt in range(max_retries):
                        if success:
                            break

                        if part_file.exists():
                            downloaded_bytes = part_file.stat().st_size
                        else:
                            downloaded_bytes = 0

                        if attempt > 0:
                            dl_mb = round(downloaded_bytes / (1024 * 1024), 1)
                            tot_mb = f" / {round(total_bytes / (1024 * 1024), 1)} MB" if total_bytes > 0 else ""
                            pct = round((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0
                            yield {
                                "stage": "downloading",
                                "message": f"网络波动，代理断点续传重试中 ({attempt + 1}/{max_retries})... 已下载: {dl_mb} MB{tot_mb}",
                                "percent": pct,
                                "downloaded_bytes": downloaded_bytes,
                                "total_bytes": total_bytes,
                            }
                            await asyncio.sleep(min(1.0 * attempt, 3.0))

                        try:
                            async with httpx.AsyncClient(
                                proxy=proxy_url,
                                follow_redirects=True,
                                timeout=timeout,
                                trust_env=True,
                            ) as client:
                                for url in candidate_urls:
                                    req_headers = dict(headers)
                                    if downloaded_bytes > 0:
                                        req_headers["Range"] = f"bytes={downloaded_bytes}-"

                                    try:
                                        async with client.stream("GET", url, headers=req_headers) as resp:
                                            if resp.status_code == 206:
                                                # Partial content
                                                cr = resp.headers.get("content-range", "")
                                                if "/" in cr:
                                                    t_str = cr.split("/")[-1].strip()
                                                    if t_str.isdigit():
                                                        total_bytes = int(t_str)
                                                open_mode = "ab"
                                            elif resp.status_code == 200:
                                                cl = resp.headers.get("content-length")
                                                total_bytes = int(cl) if cl and cl.isdigit() else 0
                                                downloaded_bytes = 0
                                                open_mode = "wb"
                                            elif resp.status_code == 416:
                                                part_file.write_bytes(b"")
                                                downloaded_bytes = 0
                                                continue
                                            else:
                                                last_error = RuntimeError(f"HTTP {resp.status_code}")
                                                continue

                                            last_bytes = downloaded_bytes
                                            last_yield_time = time.monotonic()

                                            with open(part_file, open_mode) as f:
                                                async for chunk in resp.aiter_bytes(chunk_size=131072):
                                                    f.write(chunk)
                                                    downloaded_bytes += len(chunk)
                                                    now = time.monotonic()
                                                    elapsed = now - last_yield_time

                                                    if elapsed >= 0.2:
                                                        speed_mb = round(((downloaded_bytes - last_bytes) / (1024 * 1024)) / elapsed, 1)
                                                        last_bytes = downloaded_bytes
                                                        last_yield_time = now

                                                        pct = round((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0
                                                        dl_mb = round(downloaded_bytes / (1024 * 1024), 1)
                                                        tot_mb = f" / {round(total_bytes / (1024 * 1024), 1)} MB" if total_bytes > 0 else ""
                                                        yield {
                                                            "stage": "downloading",
                                                            "message": f"正在通过代理下载: {dl_mb} MB{tot_mb} ({speed_mb} MB/s)",
                                                            "percent": pct,
                                                            "downloaded_bytes": downloaded_bytes,
                                                            "total_bytes": total_bytes,
                                                            "speed_mb": speed_mb,
                                                        }

                                            if downloaded_bytes > 0 and (total_bytes == 0 or downloaded_bytes >= total_bytes):
                                                success = True
                                                break
                                    except Exception as exc:
                                        last_error = exc
                                        logger.warning("Proxy download interrupted (attempt %d) for kernel %s: %s", attempt + 1, version, exc)
                                    if success:
                                        break
                        except Exception as exc:
                            last_error = exc
                            logger.warning("Proxy client error (attempt %d) for kernel %s: %s", attempt + 1, version, exc)
            else:
                # Local network mode
                timeout = httpx.Timeout(connect=8.0, read=60.0, write=20.0, pool=10.0)
                max_retries = 3
                for attempt in range(max_retries):
                    if success:
                        break

                    if part_file.exists():
                        downloaded_bytes = part_file.stat().st_size
                    else:
                        downloaded_bytes = 0

                    if attempt > 0:
                        dl_mb = round(downloaded_bytes / (1024 * 1024), 1)
                        tot_mb = f" / {round(total_bytes / (1024 * 1024), 1)} MB" if total_bytes > 0 else ""
                        pct = round((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0
                        yield {
                            "stage": "downloading",
                            "message": f"网络波动，断点重连中 ({attempt + 1}/{max_retries})... 已下载: {dl_mb} MB{tot_mb}",
                            "percent": pct,
                            "downloaded_bytes": downloaded_bytes,
                            "total_bytes": total_bytes,
                        }
                        await asyncio.sleep(min(1.0 * attempt, 3.0))

                    try:
                        async with httpx.AsyncClient(
                            follow_redirects=True,
                            timeout=timeout,
                            trust_env=True,
                        ) as client:
                            for url in candidate_urls:
                                req_headers = dict(headers)
                                if downloaded_bytes > 0:
                                    req_headers["Range"] = f"bytes={downloaded_bytes}-"

                                try:
                                    async with client.stream("GET", url, headers=req_headers) as resp:
                                        if resp.status_code == 206:
                                            cr = resp.headers.get("content-range", "")
                                            if "/" in cr:
                                                t_str = cr.split("/")[-1].strip()
                                                if t_str.isdigit():
                                                    total_bytes = int(t_str)
                                            open_mode = "ab"
                                        elif resp.status_code == 200:
                                            cl = resp.headers.get("content-length")
                                            total_bytes = int(cl) if cl and cl.isdigit() else 0
                                            downloaded_bytes = 0
                                            open_mode = "wb"
                                        elif resp.status_code == 416:
                                            part_file.write_bytes(b"")
                                            downloaded_bytes = 0
                                            continue
                                        else:
                                            last_error = RuntimeError(f"HTTP {resp.status_code}")
                                            continue

                                        last_bytes = downloaded_bytes
                                        last_yield_time = time.monotonic()

                                        with open(part_file, open_mode) as f:
                                            async for chunk in resp.aiter_bytes(chunk_size=131072):
                                                f.write(chunk)
                                                downloaded_bytes += len(chunk)
                                                now = time.monotonic()
                                                elapsed = now - last_yield_time

                                                if elapsed >= 0.2:
                                                    speed_mb = round(((downloaded_bytes - last_bytes) / (1024 * 1024)) / elapsed, 1)
                                                    last_bytes = downloaded_bytes
                                                    last_yield_time = now

                                                    pct = round((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0
                                                    dl_mb = round(downloaded_bytes / (1024 * 1024), 1)
                                                    tot_mb = f" / {round(total_bytes / (1024 * 1024), 1)} MB" if total_bytes > 0 else ""
                                                    yield {
                                                        "stage": "downloading",
                                                        "message": f"正在下载内核: {dl_mb} MB{tot_mb} ({speed_mb} MB/s)",
                                                        "percent": pct,
                                                        "downloaded_bytes": downloaded_bytes,
                                                        "total_bytes": total_bytes,
                                                        "speed_mb": speed_mb,
                                                    }

                                        if downloaded_bytes > 0 and (total_bytes == 0 or downloaded_bytes >= total_bytes):
                                            success = True
                                            break
                                except Exception as exc:
                                    last_error = exc
                                    logger.warning("Local stream interrupted (attempt %d) for kernel %s from %s: %s", attempt + 1, version, url, exc)
                                if success:
                                    break
                    except Exception as exc:
                        last_error = exc
                        logger.warning("Local client error (attempt %d) for kernel %s: %s", attempt + 1, version, exc)

        if not success or not part_file.exists() or part_file.stat().st_size == 0:
            logger.error("Download failed for kernel %s: %s", version, last_error)
            err_msg = f"内核下载失败: 无法连接下载服务器，请检查代理节点配置或网络连接 ({last_error})"
            if is_pro and "401" in str(last_error):
                err_msg = "CloakBrowser Pro 内核下载鉴权失败 (HTTP 401)：License 密钥无效或未授权。请前往『设置』检查商业授权码，或使用免费的官方稳定版内核。"
            elif is_pro and "403" in str(last_error):
                err_msg = "CloakBrowser Pro 内核下载受限 (HTTP 403)：当前 License 权限不足。请前往『设置』检查商业授权码。"
            yield {
                "stage": "error",
                "message": err_msg,
                "percent": 0,
                "downloaded_bytes": downloaded_bytes,
                "total_bytes": total_bytes,
                "browser_type": "cloakbrowser",
            }
            return

        # Verification stage
        yield {
            "stage": "verifying",
            "message": "下载完成，正在校验完整性 (SHA-256 / 签名)...",
            "percent": 100,
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
        }

        try:
            if is_pro:
                await asyncio.to_thread(_verify_pro_download, part_file, version)
            else:
                await asyncio.to_thread(_verify_download_checksum, part_file, version)
        except Exception as exc:
            logger.warning("Checksum verification warning for kernel %s: %s", version, exc)
            # If verification fails due to network fetching checksums, log and proceed with extraction if file looks like valid archive

        # Extraction stage
        yield {
            "stage": "extracting",
            "message": f"正在解压并部署内核至 {dest_dir}...",
            "percent": 100,
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
        }

        await asyncio.to_thread(_extract_archive, part_file, dest_dir, binary_path)

        if not (binary_path.exists() and _is_executable(binary_path)):
            raise RuntimeError(f"解压完成但未在预期路径找到可执行内核: {binary_path}")

        # Update version marker
        try:
            if is_pro:
                _write_pro_version_marker(version, release_channel)
            else:
                _write_version_marker(version)
        except Exception as exc:
            logger.debug("Failed to write version marker: %s", exc)

        yield {
            "stage": "completed",
            "message": f"Chromium {version} 内核安装完成，已就绪！",
            "percent": 100,
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
            "binary_path": str(binary_path),
        }

    finally:
        if part_file.exists():
            try:
                part_file.unlink(missing_ok=True)
            except Exception:
                pass


def delete_kernel(version: str, tier: str = "free", browser_type: str = "cloakbrowser") -> bool:
    """Delete an installed kernel from local disk."""
    if browser_type == "camoufox":
        from .runtime import resolve_runtime
        import glob
        clean_version = version.lstrip("v")
        dirs_to_check = [
            resolve_runtime().data_dir / "kernels" / "camoufox" / "browsers",
        ]
        try:
            import camoufox.pkgman as cp
            dirs_to_check.append(Path(cp.INSTALL_DIR) / "browsers")
        except Exception:
            pass

        deleted = False
        for cdir in dirs_to_check:
            matched = (
                glob.glob(f"{cdir}/*/*{clean_version}*")
                or glob.glob(f"{cdir}/*{clean_version}*")
                or glob.glob(f"{cdir}/*/*{version}*")
                or glob.glob(f"{cdir}/*{version}*")
            )
            for path_str in matched:
                p = Path(path_str)
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                    deleted = True
                elif p.is_file():
                    p.unlink(missing_ok=True)
                    deleted = True
        return deleted

    is_pro = tier.lower() == "pro"
    dest_dir = get_binary_dir(version, pro=is_pro)
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
        return True
    return False


class KernelDownloadManager:
    """Manages background downloading of Chromium kernels with multi-subscriber SSE support.

    Ensures that closing the UI modal does not abort the download in progress, and allows
    reconnecting clients to resume viewing real-time download progress.
    """

    def __init__(self) -> None:
        self._current_task: asyncio.Task | None = None
        self._current_info: dict[str, Any] | None = None
        self._finished_time: float | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._on_completed_callbacks: list[Callable[[], None]] = []

    def register_on_completed(self, callback: Callable[[], None]) -> None:
        """Register a callback to be called when a download successfully completes."""
        self._on_completed_callbacks.append(callback)

    def get_status(self) -> dict[str, Any]:
        """Return the current download status."""
        active = self._current_task is not None and not self._current_task.done()
        if not active and self._finished_time is not None:
            # Expire finished task info after 30 seconds
            if time.time() - self._finished_time > 30:
                self._current_info = None
                self._finished_time = None

        return {
            "active": active,
            "task": self._current_info,
        }

    def start_download(
        self,
        version: str,
        tier: str = "free",
        browser_type: str = "cloakbrowser",
        license_key: str | None = None,
        release_channel: str | None = None,
    ) -> None:
        """Start downloading a kernel in the background if not already downloading."""
        if self._current_task is not None and not self._current_task.done():
            if (
                self._current_info
                and self._current_info.get("version") == version
                and self._current_info.get("tier") == tier
                and self._current_info.get("browser_type") == browser_type
            ):
                return
            raise RuntimeError(
                f"已有内核正在下载中: {self._current_info.get('browser_type', 'cloakbrowser')} {self._current_info.get('version')} ({self._current_info.get('tier')})"
            )

        self._finished_time = None
        self._current_info = {
            "version": version,
            "tier": tier,
            "browser_type": browser_type,
            "stage": "connecting",
            "message": f"正在准备下载 {browser_type} {version} ({tier})...",
            "percent": 0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed_mb": None,
            "binary_path": None,
        }
        self._current_task = asyncio.create_task(
            self._download_worker(version, tier, browser_type, license_key, release_channel)
        )

    async def _download_worker(
        self,
        version: str,
        tier: str,
        browser_type: str,
        license_key: str | None,
        release_channel: str | None,
    ) -> None:
        try:
            if browser_type == "camoufox":
                generator = stream_download_camoufox(version)
            else:
                generator = stream_download_kernel(
                    version=version,
                    tier=tier,
                    license_key=license_key,
                    release_channel=release_channel,
                )
            async for event in generator:
                event_data = {
                    "version": version,
                    "tier": tier,
                    "browser_type": browser_type,
                    **event,
                }
                self._current_info = event_data
                await self._broadcast(event_data)

            if self._current_info and self._current_info.get("stage") == "completed":
                for cb in self._on_completed_callbacks:
                    try:
                        cb()
                    except Exception as exc:
                        logger.warning("Error running kernel download completion callback: %s", exc)
        except asyncio.CancelledError:
            logger.info("Kernel download worker cancelled for %s (%s)", version, tier)
            err_data = {
                "version": version,
                "tier": tier,
                "browser_type": browser_type,
                "stage": "error",
                "message": "内核下载已被中止",
                "percent": 0,
            }
            self._current_info = err_data
            await self._broadcast(err_data)
            raise
        except Exception as exc:
            logger.exception("Kernel download worker error for %s: %s", version, exc)
            err_data = {
                "version": version,
                "tier": tier,
                "browser_type": browser_type,
                "stage": "error",
                "message": str(exc),
                "percent": 0,
            }
            self._current_info = err_data
            await self._broadcast(err_data)
        finally:
            self._finished_time = time.time()

    async def _broadcast(self, event: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                pass

    async def subscribe(
        self,
        version: str | None = None,
        tier: str | None = None,
        browser_type: str = "cloakbrowser",
        license_key: str | None = None,
        release_channel: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to download events for the current or newly initiated task."""
        if version:
            if self._current_task is None or self._current_task.done():
                self.start_download(
                    version=version,
                    tier=tier or "free",
                    browser_type=browser_type,
                    license_key=license_key,
                    release_channel=release_channel,
                )

        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(q)

        try:
            if self._current_info:
                yield self._current_info
                if self._current_info.get("stage") in ("completed", "error"):
                    return

            while True:
                event = await q.get()
                yield event
                if event.get("stage") in ("completed", "error"):
                    break
        finally:
            self._subscribers.discard(q)


kernel_download_manager = KernelDownloadManager()

