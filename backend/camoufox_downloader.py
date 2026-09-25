import asyncio
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import AsyncIterator, Any
import requests
from camoufox.pkgman import CamoufoxFetcher, list_available_versions, GITHUB_TOKEN
import camoufox.pkgman as cp
import camoufox.multiversion as cm
from .runtime import resolve_runtime

# Ensure camoufox pkgman installs into our managed data directory
_camoufox_data_dir = resolve_runtime().data_dir / "kernels" / "camoufox"
cp.INSTALL_DIR = _camoufox_data_dir
cm.BROWSERS_DIR = _camoufox_data_dir / "browsers"

try:
    import platformdirs
    _orig_user_cache_dir = platformdirs.user_cache_dir
    def _custom_user_cache_dir(appname=None, *args, **kwargs):
        if appname == "camoufox":
            return str(_camoufox_data_dir)
        return _orig_user_cache_dir(appname, *args, **kwargs)
    platformdirs.user_cache_dir = _custom_user_cache_dir
except Exception:
    pass


class CustomCamoufoxFetcher(CamoufoxFetcher):
    progress_callback = None
    proxy_url: str | None = None
    fallback_proxy_url: str | None = None

    @classmethod
    def download_file(cls, file, url):
        headers = (
            {"Authorization": f"Bearer {GITHUB_TOKEN}"} if "api.github" in url and GITHUB_TOKEN else {}
        )
        proxies = {"http": cls.proxy_url, "https": cls.proxy_url} if cls.proxy_url else None

        response = None
        try:
            response = requests.get(url, stream=True, headers=headers, proxies=proxies, timeout=(15.0, 120.0))
            response.raise_for_status()
        except Exception as exc:
            if not proxies and cls.fallback_proxy_url:
                fb_proxies = {"http": cls.fallback_proxy_url, "https": cls.fallback_proxy_url}
                response = requests.get(url, stream=True, headers=headers, proxies=fb_proxies, timeout=(15.0, 120.0))
                response.raise_for_status()
            else:
                raise exc

        total_size = int(response.headers.get("content-length", 0))
        block_size = 131072  # 128KB chunks
        downloaded = 0
        last_update = 0

        for chunk in response.iter_content(block_size):
            if not chunk:
                continue
            file.write(chunk)
            downloaded += len(chunk)
            if downloaded - last_update >= 65536 or (total_size > 0 and downloaded >= total_size):
                if cls.progress_callback:
                    cls.progress_callback(downloaded, total_size)
                last_update = downloaded

        file.seek(0)
        return file


async def stream_download_camoufox(version: str) -> AsyncIterator[dict[str, Any]]:
    yield {
        "browser_type": "camoufox",
        "stage": "connecting",
        "message": f"正在解析 Camoufox {version}...",
        "percent": 0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "speed_mb": None,
    }

    # 1. find version object
    try:
        versions = list_available_versions(include_prerelease=True)
    except Exception as e:
        yield {
            "browser_type": "camoufox",
            "stage": "error",
            "message": f"获取 Camoufox 版本列表失败: {e}",
            "percent": 0,
        }
        return

    clean_req_version = version.lstrip("v")
    target_v = None
    for v in versions:
        disp = str(getattr(v, "display", "")).lstrip("v")
        full_ver = str(getattr(getattr(v, "version", None), "full_string", "")).lstrip("v")
        v_str = str(getattr(getattr(v, "version", None), "version", "")).lstrip("v")
        if clean_req_version in (disp, full_ver, v_str):
            target_v = v
            break

    if not target_v:
        yield {
            "browser_type": "camoufox",
            "stage": "error",
            "message": f"未在 GitHub Releases 找到版本: {version}",
            "percent": 0,
        }
        return

    # Check imported proxy if direct is blocked
    from .extension_manager import get_imported_proxy_url
    fallback_proxy: str | None = None
    try:
        async for p_url in get_imported_proxy_url():
            fallback_proxy = p_url
            break
    except Exception:
        pass

    CustomCamoufoxFetcher.fallback_proxy_url = fallback_proxy
    fetcher = CustomCamoufoxFetcher(selected_version=target_v)

    # 2. queue to get progress from thread
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def progress_callback(downloaded: int, total_size: int):
        loop.call_soon_threadsafe(queue.put_nowait, ("PROGRESS", downloaded, total_size))

    CustomCamoufoxFetcher.progress_callback = progress_callback

    def download_thread():
        try:
            # We wrap installation: download_file -> verify -> unzip
            fetcher.install(replace=True)
            try:
                from .camoufox_policies import sanitize_all_installed_camoufox_kernels
                sanitize_all_installed_camoufox_kernels()
            except Exception:
                pass
            loop.call_soon_threadsafe(queue.put_nowait, ("DONE", None, None))
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, ("ERROR", e, None))

    t = threading.Thread(target=download_thread, daemon=True)
    t.start()

    last_bytes = 0
    last_yield_time = time.monotonic()
    total_bytes_expected = getattr(target_v, "asset_size", 0)

    while True:
        action, arg1, arg2 = await queue.get()
        now = time.monotonic()

        if action == "DONE":
            yield {
                "browser_type": "camoufox",
                "stage": "completed",
                "message": f"Camoufox {version} 安装完成，已就绪！",
                "percent": 100,
                "downloaded_bytes": total_bytes_expected,
                "total_bytes": total_bytes_expected,
                "speed_mb": None,
            }
            break
        elif action == "ERROR":
            err_msg = str(arg1)
            yield {
                "browser_type": "camoufox",
                "stage": "error",
                "message": f"Camoufox 下载安装失败: {err_msg}",
                "percent": 0,
            }
            break
        elif action == "PROGRESS":
            downloaded = arg1
            total = arg2 or total_bytes_expected
            elapsed = now - last_yield_time

            if elapsed >= 0.2 or downloaded >= total:
                speed_mb = round(((downloaded - last_bytes) / (1024 * 1024)) / max(elapsed, 0.001), 1)
                last_bytes = downloaded
                last_yield_time = now

                pct = round((downloaded / total) * 100) if total > 0 else 0
                dl_mb = round(downloaded / (1024 * 1024), 1)
                tot_mb = f" / {round(total / (1024 * 1024), 1)} MB" if total > 0 else ""

                if downloaded >= total and total > 0:
                    yield {
                        "browser_type": "camoufox",
                        "stage": "extracting",
                        "message": f"下载完成，正在解压并部署 Camoufox {version}...",
                        "percent": 100,
                        "downloaded_bytes": downloaded,
                        "total_bytes": total,
                        "speed_mb": speed_mb,
                    }
                else:
                    yield {
                        "browser_type": "camoufox",
                        "stage": "downloading",
                        "message": f"正在下载 Camoufox {version}: {dl_mb} MB{tot_mb} ({speed_mb} MB/s)",
                        "percent": pct,
                        "downloaded_bytes": downloaded,
                        "total_bytes": total,
                        "speed_mb": speed_mb,
                    }
