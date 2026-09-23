"""Platform detection for sing-box binary download.

Maps the current OS/architecture to the corresponding sing-box GitHub Release
asset name and executable filename, following the same pattern as the main
config.py SUPPORTED_PLATFORMS map.
"""

from __future__ import annotations

import platform
from pathlib import Path


# Maps (platform.system(), platform.machine()) -> (os_tag, arch_tag, archive_ext)
# Mirrors sing-box's own release naming convention on GitHub.
_SINGBOX_PLATFORM_MAP: dict[tuple[str, str], tuple[str, str, str]] = {
    ("Linux",   "x86_64"):  ("linux",   "amd64",  ".tar.gz"),
    ("Linux",   "aarch64"): ("linux",   "arm64",  ".tar.gz"),
    ("Darwin",  "arm64"):   ("darwin",  "arm64",  ".tar.gz"),
    ("Darwin",  "x86_64"):  ("darwin",  "amd64",  ".tar.gz"),
    ("Windows", "AMD64"):   ("windows", "amd64",  ".zip"),
    ("Windows", "x86_64"):  ("windows", "amd64",  ".zip"),
}


def get_singbox_platform() -> tuple[str, str, str]:
    """Return (os_tag, arch_tag, archive_ext) for the sing-box release asset.

    Raises RuntimeError if the current platform has no pre-built sing-box release.
    """
    key = (platform.system(), platform.machine())
    entry = _SINGBOX_PLATFORM_MAP.get(key)
    if entry is None:
        supported = ", ".join(f"{s}/{m}" for s, m in _SINGBOX_PLATFORM_MAP)
        raise RuntimeError(
            f"sing-box: unsupported platform {key[0]} {key[1]}. "
            f"Supported: {supported}"
        )
    return entry


def get_singbox_binary_name() -> str:
    """Return the sing-box executable filename for the current platform."""
    return "sing-box.exe" if platform.system() == "Windows" else "sing-box"


def get_singbox_asset_name(version: str) -> str:
    """Return the expected GitHub Release asset filename for a given version.

    Example: 'sing-box-1.10.0-linux-amd64.tar.gz'
    """
    os_tag, arch_tag, ext = get_singbox_platform()
    return f"sing-box-{version}-{os_tag}-{arch_tag}{ext}"


def get_singbox_inner_binary_path(extract_dir: Path, version: str) -> Path:
    """Return the path to the sing-box binary inside the extracted archive.

    sing-box archives contain a top-level subdirectory named after the asset,
    e.g. sing-box-1.10.0-linux-amd64/sing-box. This helper reconstructs that path.
    """
    os_tag, arch_tag, _ = get_singbox_platform()
    subdir = f"sing-box-{version}-{os_tag}-{arch_tag}"
    return extract_dir / subdir / get_singbox_binary_name()
