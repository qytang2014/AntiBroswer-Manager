import asyncio
import json
import logging
import os
import platform
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import AsyncIterator, Any
import requests

from camoufox.pkgman import (
    CamoufoxFetcher,
    AvailableVersion,
    Version,
    GITHUB_TOKEN,
    OS_NAME,
)
import camoufox.pkgman as cp
import camoufox.multiversion as cm
from .runtime import resolve_runtime

logger = logging.getLogger("cloakbrowser.manager.camoufox")

# Ensure camoufox pkgman installs into our managed data directory
_camoufox_data_dir = resolve_runtime().data_dir / "kernels" / "camoufox"
_camoufox_data_dir.mkdir(parents=True, exist_ok=True)
cp.INSTALL_DIR = _camoufox_data_dir
cm.BROWSERS_DIR = _camoufox_data_dir / "browsers"
cm.BROWSERS_DIR.mkdir(parents=True, exist_ok=True)

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


# ── Built-in Catalog of Official Releases ────────────────────────────────────
# Guaranteed fallback when GitHub API is blocked, unauthenticated rate-limited (403),
# or offline. Matches the official daijro/camoufox releases on GitHub.
BUILTIN_CAMOUFOX_CATALOG: dict[str, list[dict[str, Any]]] = {
    "mac.arm64": [
        {
            "version": "152.0.4",
            "build": "beta.31",
            "display": "v152.0.4-beta.31",
            "url": "https://github.com/daijro/camoufox/releases/download/font-bundle-v1/camoufox-152.0.4-beta.31-mac.arm64.zip",
            "asset_size": 312722182,
            "sha256": "7b8d12d61de9a9fbd3ce9c034399ba5307e44f4d8951873cc53ad39d20957737",
            "is_prerelease": False,
        },
        {
            "version": "152.0.4",
            "build": "beta.30",
            "display": "v152.0.4-beta.30",
            "url": "https://github.com/daijro/camoufox/releases/download/v152.0.4-beta.30/camoufox-152.0.4-beta.30-mac.arm64.zip",
            "asset_size": 312665777,
            "sha256": "3b43e766574f286a6a63296cf58b660b7a3120952086c869b4df4c9a71604bc3",
            "is_prerelease": False,
        },
        {
            "version": "152.0.4",
            "build": "beta.29",
            "display": "v152.0.4-beta.29",
            "url": "https://github.com/daijro/camoufox/releases/download/v152.0.4-beta.29/camoufox-152.0.4-beta.29-mac.arm64.zip",
            "asset_size": 312645436,
            "sha256": "620d33289b5d52154cc7d92a9cca5915329aa6684105ab0f371d01480768eb53",
            "is_prerelease": False,
        },
        {
            "version": "135.0.1",
            "build": "beta.24",
            "display": "v135.0.1-beta.24",
            "url": "https://github.com/daijro/camoufox/releases/download/v135.0.1-beta.24/camoufox-135.0.1-beta.24-mac.arm64.zip",
            "asset_size": 297579070,
            "sha256": None,
            "is_prerelease": False,
        },
    ],
    "mac.x86_64": [
        {
            "version": "152.0.4",
            "build": "beta.31",
            "display": "v152.0.4-beta.31",
            "url": "https://github.com/daijro/camoufox/releases/download/font-bundle-v1/camoufox-152.0.4-beta.31-mac.x86_64.zip",
            "asset_size": 319891561,
            "sha256": "4a6f02ffc1992a41306b00851fc0ef339ff555c92a547fe865690f89b58d8840",
            "is_prerelease": False,
        },
        {
            "version": "152.0.4",
            "build": "beta.30",
            "display": "v152.0.4-beta.30",
            "url": "https://github.com/daijro/camoufox/releases/download/v152.0.4-beta.30/camoufox-152.0.4-beta.30-mac.x86_64.zip",
            "asset_size": 319886717,
            "sha256": "f12f90a3650478e670064a2f071c13b998fdd1125f79dc9f6cad5a9b9395b4bc",
            "is_prerelease": False,
        },
        {
            "version": "152.0.4",
            "build": "beta.29",
            "display": "v152.0.4-beta.29",
            "url": "https://github.com/daijro/camoufox/releases/download/v152.0.4-beta.29/camoufox-152.0.4-beta.29-mac.x86_64.zip",
            "asset_size": 319859591,
            "sha256": None,
            "is_prerelease": False,
        },
    ],
    "win.x86_64": [
        {
            "version": "152.0.4",
            "build": "beta.31",
            "display": "v152.0.4-beta.31",
            "url": "https://github.com/daijro/camoufox/releases/download/font-bundle-v1/camoufox-152.0.4-beta.31-win.x86_64.zip",
            "asset_size": 493147697,
            "sha256": "ed63ea51d2a07f99bacdae0f43b9ff5518bfc9ac2f15d84e2251fe06c7141e81",
            "is_prerelease": False,
        },
        {
            "version": "152.0.4",
            "build": "beta.30",
            "display": "v152.0.4-beta.30",
            "url": "https://github.com/daijro/camoufox/releases/download/v152.0.4-beta.30/camoufox-152.0.4-beta.30-win.x86_64.zip",
            "asset_size": 493141328,
            "sha256": "ea52a02fb1cfb1813ef6a326bea03fb2b650c9774143d953a94a27bfc8f10072",
            "is_prerelease": False,
        },
        {
            "version": "152.0.4",
            "build": "beta.29",
            "display": "v152.0.4-beta.29",
            "url": "https://github.com/daijro/camoufox/releases/download/v152.0.4-beta.29/camoufox-152.0.4-beta.29-win.x86_64.zip",
            "asset_size": 493114948,
            "sha256": None,
            "is_prerelease": False,
        },
    ],
    "lin.x86_64": [
        {
            "version": "152.0.4",
            "build": "beta.31",
            "display": "v152.0.4-beta.31",
            "url": "https://github.com/daijro/camoufox/releases/download/font-bundle-v1/camoufox-152.0.4-beta.31-lin.x86_64.zip",
            "asset_size": 663476534,
            "sha256": "3a7958c84c0c1962574bb177a10a247b614823557308ccb7cf2e2bc9ce406c55",
            "is_prerelease": False,
        },
        {
            "version": "152.0.4",
            "build": "beta.30",
            "display": "v152.0.4-beta.30",
            "url": "https://github.com/daijro/camoufox/releases/download/v152.0.4-beta.30/camoufox-152.0.4-beta.30-lin.x86_64.zip",
            "asset_size": 663467670,
            "sha256": "5720d45b894ce1770543de024c6f10d514b38be560fa2dc3226b3d8586caf672",
            "is_prerelease": False,
        },
    ],
    "lin.arm64": [
        {
            "version": "152.0.4",
            "build": "beta.31",
            "display": "v152.0.4-beta.31",
            "url": "https://github.com/daijro/camoufox/releases/download/font-bundle-v1/camoufox-152.0.4-beta.31-lin.arm64.zip",
            "asset_size": 653889377,
            "sha256": "98dbffa9b687d42693dd0abebc47737e651b9e4b6991ba8571c3c29062645c04",
            "is_prerelease": False,
        },
        {
            "version": "152.0.4",
            "build": "beta.30",
            "display": "v152.0.4-beta.30",
            "url": "https://github.com/daijro/camoufox/releases/download/v152.0.4-beta.30/camoufox-152.0.4-beta.30-lin.arm64.zip",
            "asset_size": 653870625,
            "sha256": "60447260af8bebdb0ec3f2aa72f687b879e5598367303de2e3fdbc7a5be8c124",
            "is_prerelease": False,
        },
    ],
}


def get_current_camoufox_platform_key() -> str:
    """Return platform key formatted as os.arch matching Camoufox releases."""
    mach = platform.machine().lower()
    is_arm = mach in ("arm64", "aarch64")
    if sys_plat := sys_platform_name():
        if sys_plat == "darwin":
            return "mac.arm64" if is_arm else "mac.x86_64"
        if sys_plat == "win32":
            return "win.x86_64"
        return "lin.arm64" if is_arm else "lin.x86_64"
    return "mac.arm64"


def sys_platform_name() -> str:
    import sys
    return sys.platform


def _dict_to_available_version(item: dict[str, Any]) -> AvailableVersion:
    return AvailableVersion(
        version=Version(build=item["build"], version=item["version"]),
        url=item["url"],
        is_prerelease=item.get("is_prerelease", False),
        asset_size=item.get("asset_size"),
        sha256=item.get("sha256"),
    )


# In-memory cache for available versions
_cached_available_versions: list[AvailableVersion] | None = None
_cached_versions_time: float = 0.0
_VERSIONS_CACHE_TTL = 3600.0  # 1 hour


def fetch_camoufox_available_versions(force_refresh: bool = False) -> list[AvailableVersion]:
    """Fetch available Camoufox versions with in-memory caching, disk cache and fallback catalog."""
    global _cached_available_versions, _cached_versions_time
    now = time.time()

    if not force_refresh and _cached_available_versions and (now - _cached_versions_time < _VERSIONS_CACHE_TTL):
        return list(_cached_available_versions)

    cache_file = _camoufox_data_dir / "available_versions_cache.json"

    # Try live fetch from GitHub API with optional proxy
    try:
        from camoufox.pkgman import list_available_versions
        # Check proxy
        proxy_env = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        versions = list_available_versions(include_prerelease=False)
        if not versions:
            versions = list_available_versions(include_prerelease=True)

        if versions:
            _cached_available_versions = versions
            _cached_versions_time = now
            # Persist to disk cache
            try:
                cache_data = [
                    {
                        "version": v.version.version,
                        "build": v.version.build,
                        "url": v.url,
                        "asset_size": v.asset_size,
                        "sha256": v.sha256,
                        "is_prerelease": v.is_prerelease,
                    }
                    for v in versions[:10]
                ]
                cache_file.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as write_err:
                logger.debug("Failed to write Camoufox versions disk cache: %s", write_err)
            return list(versions)
    except Exception as exc:
        logger.warning("Failed to fetch Camoufox versions from GitHub API (%s). Falling back to cache/catalog.", exc)

    # Fallback 1: Disk Cache
    if cache_file.exists():
        try:
            cached_items = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached_items, list) and cached_items:
                recovered = [_dict_to_available_version(it) for it in cached_items]
                _cached_available_versions = recovered
                _cached_versions_time = now
                return recovered
        except Exception as read_err:
            logger.debug("Failed to read Camoufox versions disk cache: %s", read_err)

    # Fallback 2: Built-in Catalog for this platform
    plat_key = get_current_camoufox_platform_key()
    catalog_items = BUILTIN_CAMOUFOX_CATALOG.get(plat_key, [])
    if catalog_items:
        recovered = [_dict_to_available_version(it) for it in catalog_items]
        _cached_available_versions = recovered
        _cached_versions_time = now
        return recovered

    return []


def get_camoufox_kernel_list() -> list[dict[str, Any]]:
    """Build list of Camoufox kernel descriptors (both available and locally installed)."""
    current_platform = get_current_camoufox_platform_key()
    available_versions = fetch_camoufox_available_versions()

    # Scan locally installed versions
    installed_map: dict[str, dict[str, Any]] = {}
    try:
        installed_list = cm.list_installed()
        for iv in installed_list:
            v_full = iv.version.full_string.lstrip("v")
            v_disp = f"v{v_full}"
            size_mb = 0.0
            if iv.path.exists():
                try:
                    tot_bytes = sum(f.stat().st_size for f in iv.path.rglob("*") if f.is_file())
                    size_mb = round(tot_bytes / (1024 * 1024), 1)
                except Exception:
                    size_mb = 0.0

            bin_path = None
            try:
                bin_path = str(cp.launch_path(iv.path))
            except Exception:
                # Fallback search for executable in version folder
                for cand in [
                    iv.path / "Camoufox.app" / "Contents" / "MacOS" / "camoufox",
                    iv.path / "camoufox",
                    iv.path / "camoufox.exe",
                ]:
                    if cand.exists():
                        bin_path = str(cand)
                        break

            installed_map[v_full] = {
                "installed": True,
                "binary_path": bin_path,
                "size_mb": size_mb,
                "is_active": iv.is_active,
            }
    except Exception as exc:
        logger.debug("Error listing installed Camoufox browsers: %s", exc)

    kernels: list[dict[str, Any]] = []
    seen_versions: set[str] = set()

    # 1. Process available versions
    for cv in available_versions:
        cv_disp = getattr(cv, "display", None) or f"v{cv.version.full_string}"
        cv_ver_str = str(getattr(getattr(cv, "version", None), "full_string", cv_disp)).lstrip("v")
        clean_key = cv_ver_str.lstrip("v")

        inst_info = installed_map.get(clean_key)
        is_installed = inst_info is not None
        binary_path = inst_info.get("binary_path") if inst_info else None
        size_mb = inst_info.get("size_mb") if inst_info else None
        if not size_mb and getattr(cv, "asset_size", None):
            size_mb = round(cv.asset_size / (1024 * 1024), 1)

        seen_versions.add(clean_key)
        kernels.append({
            "version": cv_ver_str,
            "tier": "free",
            "browser_type": "camoufox",
            "name": f"Camoufox {cv_ver_str}",
            "description": "基于 Firefox 的开源免授权反指纹浏览器内核 (具备底层特征随机化防护)",
            "platform": current_platform,
            "installed": is_installed,
            "is_active": inst_info.get("is_active", False) if inst_info else False,
            "binary_path": binary_path,
            "size_mb": size_mb,
        })

    # 2. Add any locally installed versions not in available catalog
    for v_full, inst_info in installed_map.items():
        if v_full not in seen_versions:
            seen_versions.add(v_full)
            kernels.append({
                "version": v_full,
                "tier": "free",
                "browser_type": "camoufox",
                "name": f"Camoufox {v_full} (本地安装)",
                "description": "已安装在本地目录的 Camoufox (Firefox) 内核",
                "platform": current_platform,
                "installed": True,
                "is_active": inst_info.get("is_active", False),
                "binary_path": inst_info.get("binary_path"),
                "size_mb": inst_info.get("size_mb"),
            })

    return kernels


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
    versions = fetch_camoufox_available_versions()

    clean_req_version = version.lstrip("v")
    target_v = None
    for v in versions:
        disp = str(getattr(v, "display", "")).lstrip("v")
        full_ver = str(getattr(getattr(v, "version", None), "full_string", "")).lstrip("v")
        v_str = str(getattr(getattr(v, "version", None), "version", "")).lstrip("v")
        if clean_req_version in (disp, full_ver, v_str):
            target_v = v
            break

    # If not found in fetched versions, check platform catalog directly
    if not target_v:
        plat_key = get_current_camoufox_platform_key()
        for cat in BUILTIN_CAMOUFOX_CATALOG.get(plat_key, []):
            if clean_req_version in (cat["version"], cat["build"], f"{cat['version']}-{cat['build']}"):
                target_v = _dict_to_available_version(cat)
                break

    if not target_v:
        yield {
            "browser_type": "camoufox",
            "stage": "error",
            "message": f"未找到匹配当前平台的 Camoufox 版本: {version}",
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
