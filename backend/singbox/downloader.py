"""Sing-box binary downloader.

Resolves the sing-box executable via:
  1. CLOAKBROWSER_SINGBOX_PATH environment variable (user-supplied override)
  2. System PATH (shutil.which)
  3. Local cache at AntiBrowser-Manager/singbox/ (previously downloaded)
  4. Auto-download from GitHub Releases (latest stable release)

The download path mirrors the pattern established by cloakbrowser/download.py.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import httpx

from ._platform import (
    get_singbox_asset_name,
    get_singbox_binary_name,
    get_singbox_inner_binary_path,
    get_singbox_platform,
)

logger = logging.getLogger("backend.singbox")

# GitHub API endpoint for latest sing-box release
_SINGBOX_GITHUB_API = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"

# Download timeout — large archive on slow connections
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)


from ..runtime import resolve_runtime

def _get_singbox_cache_dir() -> Path:
    """Return the local cache directory for the sing-box binary."""
    return resolve_runtime().data_dir / "singbox"


def ensure_singbox() -> Path:
    """Ensure the sing-box binary is available and return its absolute path.

    Resolution order:
      1. CLOAKBROWSER_SINGBOX_PATH env var (user override, skips download)
      2. 'sing-box' on the system PATH
      3. Previously downloaded binary in AntiBrowser-Manager/singbox/
      4. Auto-download latest stable release from GitHub

    Returns:
        Absolute Path to the sing-box executable.

    Raises:
        RuntimeError: If the platform is unsupported or the download fails.
    """
    # 1. Explicit override (highest priority)
    override = os.environ.get("CLOAKBROWSER_SINGBOX_PATH")
    if override:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(
                f"CLOAKBROWSER_SINGBOX_PATH set to '{override}' but file not found."
            )
        logger.debug("Using sing-box binary from CLOAKBROWSER_SINGBOX_PATH: %s", p)
        return p

    # 2. System PATH
    found = shutil.which("sing-box")
    if found:
        logger.debug("Using sing-box from system PATH: %s", found)
        return Path(found)

    # 3. Local cache (previously auto-downloaded)
    cache_dir = _get_singbox_cache_dir()
    cached = cache_dir / get_singbox_binary_name()
    if cached.exists() and _is_executable(cached):
        logger.debug("Using cached sing-box binary: %s", cached)
        return cached

    # 4. Auto-download
    logger.info("sing-box binary not found — downloading from GitHub Releases...")
    return _download_singbox(cache_dir)


def _is_executable(path: Path) -> bool:
    """Return True if the file exists and is executable."""
    return path.exists() and os.access(path, os.X_OK)


def _stream_download(url: str, dest: Path) -> None:
    """Download url to dest, streaming with a simple progress indicator."""
    with httpx.stream("GET", url, timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    sys.stderr.write(f"\r  sing-box download: {pct}%   ")
                    sys.stderr.flush()
    if total:
        sys.stderr.write("\n")
        sys.stderr.flush()


def _extract_archive(archive: Path, dest_dir: Path) -> None:
    """Extract a .tar.gz or .zip archive to dest_dir."""
    if archive.suffix == ".gz" or archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest_dir)
    elif archive.suffix == ".zip":
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(dest_dir)
    else:
        raise RuntimeError(f"Unknown archive format: {archive}")


def _fetch_release_info() -> str:
    """Find the latest sing-box release version without getting blocked by rate limits.

    Tries:
      1. GitHub REST API (with optional GITHUB_TOKEN / GH_TOKEN)
      2. HTML redirect from https://github.com/SagerNet/sing-box/releases/latest (no API rate limit)

    Returns the version string without a leading 'v', e.g. '1.14.1'.
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.get(
            _SINGBOX_GITHUB_API,
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers=headers,
        )
        if resp.status_code == 200:
            tag = resp.json().get("tag_name", "")
            if tag:
                return tag.lstrip("v")
    except Exception as exc:
        logger.debug("GitHub API fetch failed: %s", exc)

    # Fallback: parse 302 redirect from web releases URL (does not hit API rate limit)
    try:
        resp = httpx.get(
            "https://github.com/SagerNet/sing-box/releases/latest",
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
        )
        loc = resp.headers.get("location", "")
        if loc and "/releases/tag/" in loc:
            tag = loc.split("/releases/tag/")[-1].lstrip("v").strip("/")
            if tag:
                return tag
    except Exception as exc:
        logger.debug("Web redirect fetch failed: %s", exc)

    raise RuntimeError(
        "Failed to determine latest sing-box version from GitHub (rate limited or network error).\n"
        "Set CLOAKBROWSER_SINGBOX_PATH to a local binary to skip auto-download."
    )


def _fetch_latest_version() -> str:
    """Query the GitHub API or web redirect to find the latest sing-box release tag."""
    return _fetch_release_info()


def _find_asset_url(release_data: dict, asset_name: str) -> str:
    """Return the browser_download_url for a specific asset in a release dict."""
    for asset in release_data.get("assets", []):
        if asset.get("name") == asset_name:
            return asset["browser_download_url"]
    available = [a["name"] for a in release_data.get("assets", [])]
    raise RuntimeError(
        f"sing-box release asset '{asset_name}' not found. "
        f"Available assets: {available}"
    )


def _download_singbox(cache_dir: Path) -> Path:
    """Download the latest sing-box release and return the binary path.

    Args:
        cache_dir: Directory where the binary will be cached.

    Returns:
        Path to the extracted sing-box executable.
    """
    # Ensure platform is supported before making any network calls
    get_singbox_platform()  # raises RuntimeError on unsupported platforms

    cache_dir.mkdir(parents=True, exist_ok=True)

    version = _fetch_release_info()
    asset_name = get_singbox_asset_name(version)
    download_url = f"https://github.com/SagerNet/sing-box/releases/download/v{version}/{asset_name}"
    logger.info("Downloading sing-box %s (%s)...", version, asset_name)

    # Download to a temp file in the cache dir
    archive_path = cache_dir / asset_name
    try:
        _stream_download(download_url, archive_path)
    except Exception as exc:
        archive_path.unlink(missing_ok=True)
        raise RuntimeError(f"sing-box download failed: {exc}") from exc

    # Extract to a temp directory, then move the binary into cache_dir
    extract_tmp = Path(tempfile.mkdtemp(dir=cache_dir, prefix="singbox_extract_"))
    try:
        _extract_archive(archive_path, extract_tmp)

        # Locate binary — may be in a subdirectory named after the archive
        inner = get_singbox_inner_binary_path(extract_tmp, version)
        binary_name = get_singbox_binary_name()

        if not inner.exists():
            # Fallback: search directly in extract root
            flat = extract_tmp / binary_name
            if flat.exists():
                inner = flat
            else:
                raise RuntimeError(
                    f"sing-box binary not found in extracted archive. "
                    f"Expected: {inner} or {flat}"
                )

        dest = cache_dir / binary_name
        shutil.move(str(inner), str(dest))

        # Set executable bit on POSIX systems
        if platform.system() != "Windows":
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    finally:
        # Clean up temp extraction dir and archive
        shutil.rmtree(extract_tmp, ignore_errors=True)
        archive_path.unlink(missing_ok=True)

    logger.info("sing-box %s installed at: %s", version, dest)
    return dest
