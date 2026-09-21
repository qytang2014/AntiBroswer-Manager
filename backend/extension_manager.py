"""Chrome extension management subsystem.

Handles downloading, unpacking, manifest inspection, and registry of Chrome
extensions (.crx and .zip files) for profile-level usage.
"""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx

from .database import (
    create_extension,
    delete_extension,
    get_extension,
    list_extensions,
)
from .runtime import resolve_runtime

logger = logging.getLogger("cloakbrowser.manager.extensions")

RUNTIME = resolve_runtime()
EXTENSIONS_DIR = RUNTIME.data_dir / "extensions"

# Chrome extension ID is 32 lowercase chars in [a-p]
_EXT_ID_RE = re.compile(r"([a-p]{32})")
_ZIP_MAGIC = b"PK\x03\x04"

# Curated popular extensions for quick 1-click install
POPULAR_EXTENSIONS = [
    {
        "id": "cjpalhdlnbpafiamejdnhcphjbkeiagm",
        "name": "uBlock Origin",
        "description": "An efficient ad and tracker blocker.",
        "version": "Latest",
        "rating": 4.8,
    },
    {
        "id": "nkbihfbeogaeaoehlefnkodbefgpgknn",
        "name": "MetaMask",
        "description": "Ethereum wallet in your browser.",
        "version": "Latest",
        "rating": 4.6,
    },
    {
        "id": "iphcomljkgghnfcnojlahf Eureka",
        "id": "hlkenndednhfkekhgcdicdfddnkalmdm",
        "name": "Cookie-Editor",
        "description": "Simple and powerful Cookie Editor.",
        "version": "Latest",
        "rating": 4.7,
    },
    {
        "id": "padekgcemlokbadohgkifijomclgjgif",
        "name": "Proxy SwitchyOmega",
        "description": "Manage and switch between multiple proxies easily.",
        "version": "Latest",
        "rating": 4.5,
    },
    {
        "id": "idgpnmonknjnojddfkpgkljpfnnfcklj",
        "name": "ModHeader - Modify HTTP headers",
        "description": "Modify request and response headers.",
        "version": "Latest",
        "rating": 4.6,
    },
]


def extract_webstore_id(input_str: str) -> str | None:
    """Extract a 32-char Chrome Web Store extension ID from a URL or raw ID."""
    match = _EXT_ID_RE.search(input_str.strip().lower())
    return match.group(1) if match else None


def _find_zip_offset(data: bytes) -> int:
    """Locate the starting offset of ZIP data inside a CRX archive."""
    offset = data.find(_ZIP_MAGIC)
    if offset == -1:
        raise ValueError("Invalid extension package: no ZIP header found")
    return offset


def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract a ZIP file safely, preventing Zip Slip directory traversal."""
    target_dir.mkdir(parents=True, exist_ok=True)
    resolved_target = target_dir.resolve()

    for member in zf.infolist():
        target_path = (target_dir / member.filename).resolve()
        if not target_path.is_relative_to(resolved_target):
            raise ValueError(f"Malicious extension path detected: {member.filename}")
        if member.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _resolve_manifest_i18n(manifest: dict[str, Any], ext_dir: Path) -> tuple[str, str]:
    """Resolve localized extension name and description from _locales."""
    name = manifest.get("name", "Unnamed Extension")
    description = manifest.get("description", "")

    locales_dir = ext_dir / "_locales"
    if not locales_dir.is_dir():
        return name, description

    # Priority: zh_CN, zh, en, first available
    preferred_locales = ["zh_CN", "zh", "en", "en_US"]
    messages_file = None
    for loc in preferred_locales:
        candidate = locales_dir / loc / "messages.json"
        if candidate.is_file():
            messages_file = candidate
            break

    if not messages_file:
        for p in locales_dir.glob("*/messages.json"):
            messages_file = p
            break

    if messages_file:
        try:
            messages = json.loads(messages_file.read_text(encoding="utf-8"))
            if name.startswith("__MSG_") and name.endswith("__"):
                msg_key = name[6:-2]
                name = messages.get(msg_key, {}).get("message", name)
            if description.startswith("__MSG_") and description.endswith("__"):
                msg_key = description[6:-2]
                description = messages.get(msg_key, {}).get("message", description)
        except Exception as exc:
            logger.debug("Failed to read locale messages: %s", exc)

    return name, description


def _parse_extension_metadata(ext_dir: Path) -> dict[str, Any]:
    """Inspect an unpacked extension directory and extract metadata from manifest.json."""
    manifest_path = ext_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Extension directory is missing manifest.json")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Malformed manifest.json: {exc}") from exc

    name, description = _resolve_manifest_i18n(manifest, ext_dir)
    version = str(manifest.get("version", "1.0.0"))

    # Locate icon
    icon_rel_path = None
    icons = manifest.get("icons")
    if isinstance(icons, dict):
        # Pick largest available icon
        for size in ["128", "96", "64", "48", "32", "16"]:
            if size in icons:
                candidate = ext_dir / icons[size]
                if candidate.is_file():
                    icon_rel_path = icons[size]
                    break

    return {
        "name": name,
        "version": version,
        "description": description,
        "icon_rel_path": icon_rel_path,
    }


async def install_extension_from_bytes(
    file_bytes: bytes,
    filename: str,
    source: str = "upload",
    webstore_id: str | None = None,
) -> dict[str, Any]:
    """Unpack a .crx or .zip file into the managed extensions directory."""
    ext_id = webstore_id or str(uuid.uuid4())[:12]
    target_dir = EXTENSIONS_DIR / ext_id

    # If already exists, clear first
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)

    # If CRX, skip header to ZIP offset
    offset = 0
    if filename.lower().endswith(".crx") or file_bytes.startswith(b"Cr24"):
        offset = _find_zip_offset(file_bytes)

    zip_bytes = file_bytes[offset:]
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            _safe_extract_zip(zf, target_dir)
    except Exception as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise ValueError(f"Failed to unpack extension: {exc}") from exc

    try:
        meta = _parse_extension_metadata(target_dir)
    except Exception as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise exc

    icon_url = f"/api/extensions/{ext_id}/icon" if meta.get("icon_rel_path") else None

    return create_extension(
        ext_id=ext_id,
        name=meta["name"],
        version=meta["version"],
        description=meta["description"],
        icon_url=icon_url,
        path=str(target_dir),
        source=source,
        webstore_id=webstore_id,
    )


async def install_from_webstore(id_or_url: str) -> dict[str, Any]:
    """Download and install an extension directly from Google Chrome Web Store."""
    webstore_id = extract_webstore_id(id_or_url)
    if not webstore_id:
        raise ValueError(
            f"Invalid Chrome Web Store ID or URL: '{id_or_url}'. "
            "Must be a 32-character ID or full Web Store URL."
        )

    # Google Official CRX download endpoint
    crx_url = (
        "https://clients2.google.com/service/update2/crx"
        "?response=redirect&prodversion=120.0&acceptformat=crx2,crx3"
        f"&x=id%3D{webstore_id}%26uc"
    )

    logger.info("Downloading Chrome extension %s from Web Store...", webstore_id)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        resp = await client.get(crx_url, headers=headers)
        if resp.status_code != 200 or not resp.content:
            raise RuntimeError(
                f"Failed to download extension from Chrome Web Store (HTTP {resp.status_code})"
            )
        file_bytes = resp.content

    return await install_extension_from_bytes(
        file_bytes=file_bytes,
        filename=f"{webstore_id}.crx",
        source="webstore_id",
        webstore_id=webstore_id,
    )


def remove_extension(ext_id: str) -> bool:
    """Remove an installed extension from disk and database."""
    ext = get_extension(ext_id)
    if not ext:
        return False

    target_dir = Path(ext["path"])
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)

    return delete_extension(ext_id)
