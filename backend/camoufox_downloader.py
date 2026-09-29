import asyncio
import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import AsyncIterator, Any
import httpx
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
try:
    _camoufox_data_dir.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
cp.INSTALL_DIR = _camoufox_data_dir
cm.BROWSERS_DIR = _camoufox_data_dir / "browsers"
try:
    cm.BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

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


def scan_all_installed_camoufox_kernels() -> dict[str, dict[str, Any]]:
    """Scan locally installed Camoufox browser kernels under the managed data directory:
    <data_dir>/kernels/camoufox/browsers.

    If kernels already exist there, directly reuse them without re-downloading.
    """
    browsers_root = _camoufox_data_dir / "browsers"
    if not browsers_root.exists():
        return {}

    seen_dirs: set[Path] = set()
    result: dict[str, dict[str, Any]] = {}
    active_rel = None
    try:
        active_rel = cm.load_config().get("active_version")
    except Exception:
        pass

    for repo_dir in browsers_root.iterdir():
        if not repo_dir.is_dir() or repo_dir.name.startswith("."):
            continue

        # Check subdirectories (e.g. official/152.0.4-beta.31-7b8d12d6) or direct version folders
        sub_dirs = [d for d in repo_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        has_sub_versions = any(
            (d / "Camoufox.app").exists()
            or (d / "camoufox").exists()
            or (d / "camoufox.exe").exists()
            or (d / "version.json").exists()
            for d in sub_dirs
        )
        version_dirs = sub_dirs if has_sub_versions else [repo_dir]

        for vdir in version_dirs:
            try:
                resolved_vdir = vdir.resolve()
            except Exception:
                resolved_vdir = vdir
            if resolved_vdir in seen_dirs:
                continue
            seen_dirs.add(resolved_vdir)

            # Locate executable binary
            bin_path = None
            for cand in [
                vdir / "Camoufox.app" / "Contents" / "MacOS" / "camoufox",
                vdir / "camoufox",
                vdir / "camoufox.exe",
            ]:
                if cand.exists():
                    bin_path = cand
                    break

            if not bin_path:
                try:
                    bp = cp.launch_path(vdir)
                    if bp and bp.exists():
                        bin_path = bp
                except Exception:
                    pass

            if not bin_path or not bin_path.exists():
                continue

            # Ensure executable bit on Unix
            try:
                st = bin_path.stat()
                if not (st.st_mode & 0o111):
                    bin_path.chmod(st.st_mode | 0o755)
            except Exception:
                pass

            # Read version info
            vjson_path = vdir / "version.json"
            v_data: dict[str, Any] = {}
            if vjson_path.exists():
                try:
                    v_data = json.loads(vjson_path.read_text(encoding="utf-8"))
                except Exception:
                    v_data = {}

            v_str = str(v_data.get("version") or "").strip()
            b_str = str(v_data.get("build") or "").strip()
            if not v_str:
                parts = vdir.name.split("-")
                v_str = parts[0].strip()
                if len(parts) > 1:
                    b_str = parts[1].strip()

            # Compute size
            try:
                tot_bytes = sum(f.stat().st_size for f in vdir.rglob("*") if f.is_file())
                size_mb = round(tot_bytes / (1024 * 1024), 1)
            except Exception:
                size_mb = 0.0

            is_active = False
            if active_rel:
                is_active = (active_rel in str(vdir) or vdir.name in active_rel)

            entry = {
                "install_dir": vdir,
                "binary_path": str(bin_path),
                "version": v_str,
                "build": b_str,
                "size_mb": size_mb,
                "is_active": is_active,
                "folder_name": vdir.name,
            }

            aliases = [
                vdir.name,
                vdir.name.lstrip("vV"),
            ]
            if v_str and b_str:
                aliases.extend([
                    f"{v_str}-{b_str}",
                    f"v{v_str}-{b_str}",
                    f"{v_str}_{b_str}",
                ])

            for alias in aliases:
                if alias and alias not in result:
                    result[alias] = entry

    return result


def get_camoufox_kernel_list(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Build list of Camoufox kernel descriptors (both available and locally installed)."""
    current_platform = get_current_camoufox_platform_key()
    available_versions = fetch_camoufox_available_versions(force_refresh=force_refresh)
    installed_map = scan_all_installed_camoufox_kernels()

    kernels: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    # 1. Process available versions
    for cv in available_versions:
        cv_disp = getattr(cv, "display", None) or f"v{cv.version.full_string}"
        cv_ver_str = str(getattr(getattr(cv, "version", None), "full_string", cv_disp)).lstrip("v")
        clean_key = cv_ver_str.lstrip("v")
        v_ver = getattr(getattr(cv, "version", None), "version", "")
        v_build = getattr(getattr(cv, "version", None), "build", "")

        lookup_keys = [
            clean_key,
            cv_ver_str,
            f"{v_ver}-{v_build}" if v_build else v_ver,
            f"v{v_ver}-{v_build}" if v_build else f"v{v_ver}",
            cv_disp,
            cv_disp.lstrip("v"),
        ]
        lookup_keys = [lk for lk in lookup_keys if lk and lk != "-"]
        inst_info = None
        for lk in lookup_keys:
            if lk and lk in installed_map:
                inst_info = installed_map[lk]
                break

        is_installed = inst_info is not None
        binary_path = inst_info.get("binary_path") if inst_info else None
        size_mb = inst_info.get("size_mb") if inst_info else None
        if not size_mb and getattr(cv, "asset_size", None):
            size_mb = round(cv.asset_size / (1024 * 1024), 1)

        seen_keys.add(clean_key)
        if inst_info:
            seen_keys.add(inst_info["folder_name"])
            seen_keys.add(f"{inst_info['version']}-{inst_info['build']}")

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
    processed_paths: set[str] = set()
    for key, inst_info in installed_map.items():
        install_path_str = inst_info["binary_path"]
        if install_path_str in processed_paths:
            continue
        v_tag = f"{inst_info['version']}-{inst_info['build']}" if inst_info.get("build") else inst_info["version"]
        if v_tag in seen_keys or inst_info["folder_name"] in seen_keys:
            continue

        processed_paths.add(install_path_str)
        seen_keys.add(v_tag)
        kernels.append({
            "version": v_tag,
            "tier": "free",
            "browser_type": "camoufox",
            "name": f"Camoufox {v_tag} (本地安装)",
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
    """Resumable, atomic download & install pipeline for Camoufox kernels.

    Key safeguards:
    1. Downloads to a .part file with HTTP Range resumption and mirror fallback.
    2. Verifies SHA-256 integrity before unpacking.
    3. Extracts to a temporary folder and verifies executable validity.
    4. NEVER deletes an existing installation before the new one is downloaded and ready.
    5. Atomically replaces destination directory using backup-restore pattern.
    """
    yield {
        "browser_type": "camoufox",
        "stage": "connecting",
        "message": f"正在解析 Camoufox {version}...",
        "percent": 0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "speed_mb": None,
    }

    # 0. Check if already installed locally; if so, directly reuse it without downloading
    installed_map = scan_all_installed_camoufox_kernels()
    clean_req_version = version.lstrip("vV").strip()
    existing_inst = None
    for k in [clean_req_version, version, f"v{clean_req_version}"]:
        if k in installed_map:
            existing_inst = installed_map[k]
            break
    if not existing_inst:
        for k, inst in installed_map.items():
            if clean_req_version in (
                inst.get("version"),
                inst.get("folder_name"),
                f"{inst.get('version')}-{inst.get('build')}",
            ):
                existing_inst = inst
                break

    if existing_inst and existing_inst.get("binary_path"):
        bp = Path(existing_inst["binary_path"])
        if bp.exists():
            logger.info("Camoufox 内核 %s 已存在于本地目录 %s，直接复用，无需重复下载", version, bp)
            yield {
                "browser_type": "camoufox",
                "stage": "completed",
                "message": f"Camoufox {version} 本地已存在，直接复用！",
                "percent": 100,
                "downloaded_bytes": 0,
                "total_bytes": 0,
                "speed_mb": None,
                "binary_path": str(bp),
            }
            return

    # 1. Resolve version object
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

    # 2. Build candidate URLs (direct GitHub + mirror accelerators)
    primary_url = target_v.url
    candidate_urls = [primary_url]
    if "github.com" in primary_url:
        candidate_urls.append(f"https://ghfast.top/{primary_url}")
        candidate_urls.append(f"https://ghproxy.net/{primary_url}")

    # Check imported proxy
    from .extension_manager import get_imported_proxy_url
    fallback_proxy: str | None = None
    try:
        async for p_url in get_imported_proxy_url():
            fallback_proxy = p_url
            break
    except Exception:
        pass

    # 3. Setup download cache path
    dl_dir = _camoufox_data_dir / ".downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    plat_key = get_current_camoufox_platform_key()
    safe_name = f"{target_v.version.version}_{target_v.version.build}_{plat_key}"
    part_file = dl_dir / f"camoufox_{safe_name}.zip.part"

    total_bytes = getattr(target_v, "asset_size", 0) or 0
    downloaded_bytes = 0
    if part_file.exists():
        downloaded_bytes = part_file.stat().st_size

    download_success = False
    if total_bytes > 0 and downloaded_bytes == total_bytes:
        download_success = True

    # 4. Resumable streaming download loop
    if not download_success:
        last_error = None
        max_attempts = 6
        timeout = httpx.Timeout(connect=15.0, read=90.0, write=30.0, pool=15.0)

        for attempt in range(max_attempts):
            url = candidate_urls[attempt % len(candidate_urls)]
            # Try proxy on early attempts if available
            proxy_for_attempt = fallback_proxy if (fallback_proxy and attempt < 2) else None

            headers: dict[str, str] = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            }
            if GITHUB_TOKEN and "api.github" in url:
                headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

            if downloaded_bytes > 0:
                headers["Range"] = f"bytes={downloaded_bytes}-"

            try:
                client_kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
                if proxy_for_attempt:
                    client_kwargs["proxy"] = proxy_for_attempt

                async with httpx.AsyncClient(**client_kwargs) as client:
                    async with client.stream("GET", url, headers=headers) as resp:
                        if resp.status_code == 206:
                            open_mode = "ab"
                            content_range = resp.headers.get("content-range", "")
                            if "/" in content_range:
                                try:
                                    total_bytes = int(content_range.rsplit("/", 1)[-1])
                                except ValueError:
                                    pass
                        elif resp.status_code == 200:
                            open_mode = "wb"
                            downloaded_bytes = 0
                            if resp.headers.get("content-length"):
                                total_bytes = int(resp.headers["content-length"])
                        elif resp.status_code == 416:
                            # Range satisfied or invalid
                            if total_bytes and downloaded_bytes >= total_bytes:
                                download_success = True
                                break
                            else:
                                part_file.write_bytes(b"")
                                downloaded_bytes = 0
                                continue
                        else:
                            last_error = RuntimeError(f"HTTP {resp.status_code} from {url}")
                            continue

                        last_bytes = downloaded_bytes
                        last_yield_time = time.monotonic()

                        with open(part_file, open_mode) as f:
                            async for chunk in resp.aiter_bytes(chunk_size=131072):
                                if not chunk:
                                    continue
                                f.write(chunk)
                                downloaded_bytes += len(chunk)
                                now = time.monotonic()
                                elapsed = now - last_yield_time

                                if elapsed >= 0.25 or (total_bytes > 0 and downloaded_bytes >= total_bytes):
                                    speed_mb = round(((downloaded_bytes - last_bytes) / (1024 * 1024)) / max(elapsed, 0.001), 1)
                                    last_bytes = downloaded_bytes
                                    last_yield_time = now

                                    pct = round((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0
                                    dl_mb = round(downloaded_bytes / (1024 * 1024), 1)
                                    tot_mb = f" / {round(total_bytes / (1024 * 1024), 1)} MB" if total_bytes > 0 else ""

                                    yield {
                                        "browser_type": "camoufox",
                                        "stage": "downloading",
                                        "message": f"正在下载 Camoufox {version}: {dl_mb} MB{tot_mb} ({speed_mb} MB/s)",
                                        "percent": pct,
                                        "downloaded_bytes": downloaded_bytes,
                                        "total_bytes": total_bytes,
                                        "speed_mb": speed_mb,
                                    }

                        if downloaded_bytes > 0 and (total_bytes == 0 or downloaded_bytes >= total_bytes):
                            download_success = True
                            break

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Camoufox download interrupted (attempt %d/%d) from %s: %s",
                    attempt + 1,
                    max_attempts,
                    url,
                    exc,
                )
                await asyncio.sleep(1.0)

            if download_success:
                break

    if not download_success or not part_file.exists() or part_file.stat().st_size == 0:
        yield {
            "browser_type": "camoufox",
            "stage": "error",
            "message": f"Camoufox 下载失败: 无法连接下载源或连接中断 ({last_error})，请检查网络或配置代理节点后重试。",
            "percent": 0,
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
        }
        return

    # 5. Integrity verification stage
    expected_sha = getattr(target_v, "sha256", None)
    if expected_sha:
        yield {
            "browser_type": "camoufox",
            "stage": "verifying",
            "message": f"下载完成，正在校验完整性 (SHA-256)...",
            "percent": 100,
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
        }
        hasher = hashlib.sha256()
        with open(part_file, "rb") as f:
            while chunk := f.read(1048576):
                hasher.update(chunk)
        calc_sha = hasher.hexdigest().lower()
        if calc_sha != expected_sha.lower():
            logger.error("SHA256 mismatch for %s: expected %s, got %s", part_file, expected_sha, calc_sha)
            part_file.unlink(missing_ok=True)
            yield {
                "browser_type": "camoufox",
                "stage": "error",
                "message": f"Camoufox 压缩包 SHA-256 校验失败 (预期 {expected_sha[:8]}..., 实际 {calc_sha[:8]}...)，损坏文件已清理，请重试。",
                "percent": 0,
            }
            return

    # 6. Extraction to isolated temporary directory
    yield {
        "browser_type": "camoufox",
        "stage": "extracting",
        "message": f"下载校验完成，正在解压并部署 Camoufox {version}...",
        "percent": 100,
        "downloaded_bytes": downloaded_bytes,
        "total_bytes": total_bytes,
    }

    extract_tmp = _camoufox_data_dir / f".tmp_extract_{int(time.time())}_{os.getpid()}"
    try:
        extract_tmp.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(part_file, "r") as zf:
            for member in zf.infolist():
                target_path = (extract_tmp / member.filename).resolve()
                if not str(target_path).startswith(str(extract_tmp.resolve())):
                    raise RuntimeError(f"Zip 压缩包包含非法路径穿透: {member.filename}")
                zf.extract(member, extract_tmp)
                # Restore unix executable permissions
                perm = member.external_attr >> 16
                if perm:
                    try:
                        target_path.chmod(perm)
                    except Exception:
                        pass

        # Flatten single root folder if zip wrapped all files into an extra directory
        sub_items = [p for p in extract_tmp.iterdir() if not p.name.startswith(".")]
        if len(sub_items) == 1 and sub_items[0].is_dir() and sub_items[0].suffix != ".app":
            inner_dir = sub_items[0]
            for child in inner_dir.iterdir():
                shutil.move(str(child), str(extract_tmp / child.name))
            inner_dir.rmdir()

        # On macOS, remove Gatekeeper quarantine xattrs
        if platform.system() == "Darwin":
            try:
                subprocess.run(
                    ["xattr", "-rd", "com.apple.quarantine", str(extract_tmp)],
                    capture_output=True,
                    timeout=10.0,
                )
            except Exception:
                pass

        # Ensure executable permissions on all binaries and shell scripts
        for item in extract_tmp.rglob("*"):
            if item.is_file() and (
                item.name == "camoufox"
                or item.name == "camoufox.exe"
                or item.suffix in (".sh", ".bin")
                or "/MacOS/" in str(item)
            ):
                try:
                    item.chmod(item.stat().st_mode | 0o755)
                except Exception:
                    pass

        # Locate binary in extracted tree
        bin_path = None
        for cand in [
            extract_tmp / "Camoufox.app" / "Contents" / "MacOS" / "camoufox",
            extract_tmp / "camoufox",
            extract_tmp / "camoufox.exe",
        ]:
            if cand.exists():
                bin_path = cand
                break

        if not bin_path or not bin_path.exists():
            raise RuntimeError(f"解压完成但未在预期结构中找到可执行文件: {extract_tmp}")

        # Write version.json metadata
        v_meta = {
            "version": target_v.version.version,
            "build": target_v.version.build,
            "prerelease": target_v.is_prerelease,
            "sha256": getattr(target_v, "sha256", None),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (extract_tmp / "version.json").write_text(json.dumps(v_meta, indent=2), encoding="utf-8")

        # 7. Safe atomic swap to destination directory
        repo_name = "official"
        sha8 = getattr(target_v, "sha8", "") or (target_v.sha256[:8] if target_v.sha256 else "")
        v_folder_name = cm.version_folder_name(target_v.version.version, target_v.version.build, sha8)
        dest_dir = cm.BROWSERS_DIR / repo_name / v_folder_name
        dest_dir.parent.mkdir(parents=True, exist_ok=True)

        if dest_dir.exists():
            backup_dir = dest_dir.parent / f"{dest_dir.name}.bak_{int(time.time())}"
            dest_dir.rename(backup_dir)
            try:
                extract_tmp.rename(dest_dir)
                shutil.rmtree(backup_dir, ignore_errors=True)
            except Exception as swap_err:
                if backup_dir.exists() and not dest_dir.exists():
                    backup_dir.rename(dest_dir)
                raise swap_err
        else:
            extract_tmp.rename(dest_dir)

        # 8. Post-install registration & sanitization
        try:
            cm.set_active(f"browsers/{repo_name}/{v_folder_name}")
            cm.COMPAT_FLAG.touch()
        except Exception as reg_err:
            logger.debug("Camoufox active flag update notice: %s", reg_err)

        try:
            from .camoufox_policies import sanitize_all_installed_camoufox_kernels
            sanitize_all_installed_camoufox_kernels()
        except Exception as san_err:
            logger.debug("Camoufox policies sanitization notice: %s", san_err)

        # Cleanup .part file
        part_file.unlink(missing_ok=True)

        # Find final binary path in dest_dir
        final_bin = None
        for cand in [
            dest_dir / "Camoufox.app" / "Contents" / "MacOS" / "camoufox",
            dest_dir / "camoufox",
            dest_dir / "camoufox.exe",
        ]:
            if cand.exists():
                final_bin = cand
                break

        yield {
            "browser_type": "camoufox",
            "stage": "completed",
            "message": f"Camoufox {version} 安装完成，已就绪！",
            "percent": 100,
            "downloaded_bytes": total_bytes,
            "total_bytes": total_bytes,
            "speed_mb": None,
            "binary_path": str(final_bin) if final_bin else None,
        }

    except Exception as exc:
        logger.error("Failed during Camoufox extract/deploy: %s", exc, exc_info=True)
        yield {
            "browser_type": "camoufox",
            "stage": "error",
            "message": f"Camoufox 解压安装失败: {exc}",
            "percent": 0,
        }
    finally:
        if extract_tmp.exists():
            shutil.rmtree(extract_tmp, ignore_errors=True)

