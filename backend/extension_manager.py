"""Chrome extension management subsystem.

Handles downloading, unpacking, manifest inspection, and registry of Chrome
extensions (.crx and .zip files) for profile-level usage.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import shutil
import tempfile
import time
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
# Root directory for all extensions; sub-divided per engine below.
EXTENSIONS_DIR = RUNTIME.data_dir / "extensions"

# Per-engine subdirectory names.
_ENGINE_SUBDIR: dict[str, str] = {
    "camoufox": "firefox",       # Firefox-based
    "cloakbrowser": "chromium",  # Chromium-based (default)
}


def _ext_engine_dir(browser_type: str = "cloakbrowser") -> Path:
    """Return the engine-specific extensions directory.

    Layout:
        extensions/chromium/{ext_id}/   – CloakBrowser (Chromium) extensions
        extensions/firefox/{ext_id}/    – Camoufox (Firefox) extensions

    Automatically creates the directory if it does not exist.
    """
    subdir = _ENGINE_SUBDIR.get(browser_type, "chromium")
    path = EXTENSIONS_DIR / subdir
    path.mkdir(parents=True, exist_ok=True)
    return path


def migrate_extensions_to_engine_subdirs() -> None:
    """One-time migration: move extensions from the flat layout to per-engine subdirs.

    Old layout:  extensions/{ext_id}/
    New layout:  extensions/chromium/{ext_id}/   (CloakBrowser)
                 extensions/firefox/{ext_id}/    (Camoufox)

    The database ``path`` column is updated in-place for every moved entry.
    Extensions whose on-disk path is already inside a sub-directory are skipped.
    """
    from .database import (
        list_extensions,
        replace_profile_extension_path,
        update_extension_path,
    )

    installed = list_extensions()
    moved = 0
    for ext in installed:
        old_path = Path(ext.get("path") or "")
        if not old_path.is_dir():
            continue

        # Already migrated if parent is 'chromium' or 'firefox'
        if old_path.parent.name in _ENGINE_SUBDIR.values():
            continue

        # Determine target subdirectory from browser_type stored in DB
        browser_type = ext.get("browser_type") or "cloakbrowser"
        new_parent = _ext_engine_dir(browser_type)
        new_path = new_parent / old_path.name

        if new_path == old_path:
            continue

        try:
            if not new_path.exists():
                shutil.move(str(old_path), str(new_path))
            else:
                # Target already occupied — keep existing, remove duplicate
                shutil.rmtree(old_path, ignore_errors=True)

            update_extension_path(ext["id"], str(new_path))
            replace_profile_extension_path(str(old_path), str(new_path))
            moved += 1
            logger.info(
                "Migrated extension %s: %s → %s",
                ext["id"],
                old_path,
                new_path,
            )
        except Exception as exc:
            logger.warning(
                "Failed to migrate extension %s (%s → %s): %s",
                ext["id"],
                old_path,
                new_path,
                exc,
            )

    if moved:
        logger.info("Extension migration complete: %d extension(s) moved.", moved)


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
        "id": "nngceckbapebfimnlniiiahkandclblb",
        "name": "Bitwarden Password Manager",
        "description": "A secure and free password manager for all of your devices.",
        "version": "Latest",
        "rating": 4.9,
    },
    {
        "id": "fnaicdffflnofjppbagibeoednhnbjhg",
        "name": "floccus bookmarks sync",
        "description": "Sync your bookmarks privately across browsers via Nextcloud, WebDAV or Git.",
        "version": "Latest",
        "rating": 4.7,
    },
    {
        "id": "hlkenndednhfkekhgcdicdfddnkalmdm",
        "name": "Cookie-Editor",
        "description": "Simple and powerful Cookie Editor.",
        "version": "Latest",
        "rating": 4.7,
    },
    {
        "id": "idgpnmonknjnojddfkpgkljpfnnfcklj",
        "name": "ModHeader - Modify HTTP headers",
        "description": "Modify request and response headers.",
        "version": "Latest",
        "rating": 4.6,
    },
]
POPULAR_FIREFOX_EXTENSIONS = [
    {
        "id": "uBlock0@raymondhill.net",
        "name": "uBlock Origin",
        "description": "An efficient ad and tracker blocker.",
        "version": "Latest",
        "rating": 4.8,
    },
    {
        "id": "{446900e4-71c2-419f-a6a7-df9c091e268b}",
        "name": "Bitwarden Password Manager",
        "description": "A secure and free password manager for all of your devices.",
        "version": "Latest",
        "rating": 4.8,
    },
    {
        "id": "floccus@fralef.me",
        "name": "floccus bookmarks sync",
        "description": "Sync your bookmarks privately across browsers via Nextcloud, WebDAV or Git.",
        "version": "Latest",
        "rating": 4.7,
    },
    {
        "id": "{c3c10168-4186-445c-9c5b-63f12b8e2c87}",
        "name": "Cookie-Editor",
        "description": "Simple and powerful Cookie Editor.",
        "version": "Latest",
        "rating": 4.7,
    },
    {
        "id": "{7227d8ce-6d27-4632-bd88-beee2c070f80}",
        "name": "ModHeader - Modify HTTP headers",
        "description": "Modify request and response headers.",
        "version": "Latest",
        "rating": 4.6,
    },
]


import contextlib
from collections.abc import AsyncIterator


def _get_sorted_candidate_nodes() -> list[dict[str, Any]]:
    """Return imported proxy nodes sorted by reliability and latency.

    Prioritizes reliable TCP stream protocols (VLESS, VMESS, ANYTLS, TROJAN, SS)
    over experimental UDP-only protocols that may be blocked locally or experience resets.
    """
    try:
        from .database import list_proxy_nodes
        nodes = list_proxy_nodes()
    except Exception:
        nodes = []
    if not nodes:
        return []

    def _sort_key(node: dict[str, Any]) -> tuple[int, int]:
        proto = (node.get("protocol") or "").lower()
        # 0: proven reliable TCP stream protocols, 1: UDP-based or unknown
        rel = 0 if proto in ("anytls", "vless", "vmess", "trojan", "ss", "shadowsocks") else 1
        lat = node.get("last_latency_ms") or 9999
        if lat <= 0:
            lat = 9999
        return (rel, lat)

    return sorted(nodes, key=_sort_key)


@contextlib.asynccontextmanager
async def get_imported_proxy_url(node: dict[str, Any] | None = None) -> AsyncIterator[str | None]:
    """Provide a proxy URL from AntiBrowser-Manager's imported nodes if available.

    If node is not specified, selects the most reliable low-latency candidate.
    Falls back to environment variables or active local desktop proxies if no nodes are imported.
    """
    from .database import list_proxy_nodes

    if node is None:
        candidates = _get_sorted_candidate_nodes()
        node = candidates[0] if candidates else None

    if not node:
        # Fallback to system environment proxy or active local desktop proxy if available
        env_proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or os.environ.get("ALL_PROXY")
            or os.environ.get("all_proxy")
        )
        if env_proxy:
            yield env_proxy
            return

        import socket
        for port in (7890, 7897, 10808, 1080, 2080):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.15):
                    yield f"http://127.0.0.1:{port}"
                    return
            except OSError:
                pass

        yield None
        return

    node_name = node.get("name") or node.get("id") or "默认节点"
    protocol = (node.get("protocol") or "").lower()
    raw_uri = node.get("raw_uri") or ""
    parsed_config = node.get("parsed_config")

    if protocol in ("vless", "vmess", "trojan", "ss", "shadowsocks", "hysteria", "hysteria2", "hy2", "tuic", "anytls"):
        from .singbox_runner import fast_singbox_proxy

        if parsed_config:
            try:
                cfg = json.loads(parsed_config)
                proxy_payload = {"type": "singbox", "config": {"outbounds": [cfg]}}
            except Exception:
                proxy_payload = {"type": "singbox", "config": raw_uri}
        else:
            proxy_payload = {"type": "singbox", "config": raw_uri}

        try:
            with fast_singbox_proxy(proxy_payload) as proxy_url:
                yield proxy_url
        except Exception as exc:
            logger.warning("Failed to start fast sing-box proxy for Web Store (%s): %s", node_name, exc)
            yield None
    else:
        yield raw_uri or None

async def search_firefox_addons(query: str) -> list[dict[str, Any]]:
    """Search Mozilla Firefox Addons by keyword."""
    import urllib.parse
    query = query.strip()
    if not query:
        return []

    url = f"https://addons.mozilla.org/api/v5/addons/search/?q={urllib.parse.quote(query)}&type=extension"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0, trust_env=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch Firefox addons: {exc}") from exc

    results = []
    for item in data.get("results", [])[:10]:
        name_obj = item.get("name", {})
        name = name_obj.get("en-US", name_obj.get(list(name_obj.keys())[0])) if name_obj else "Unknown"
        summary_obj = item.get("summary", {})
        summary = summary_obj.get("en-US", summary_obj.get(list(summary_obj.keys())[0])) if summary_obj else ""

        current_version = item.get("current_version", {})
        version = current_version.get("version", "Latest")

        icon_url = item.get("icon_url")
        if icon_url and "?" in icon_url:
            icon_url = icon_url.split("?")[0]

        ratings = item.get("ratings", {})
        rating = round(ratings.get("average", 0), 1)

        # We need the XPI download URL for direct installation
        files = current_version.get("files", [])
        download_url = files[0].get("url") if files else None

        guid = item.get("guid") or str(item.get("id"))

        results.append({
            "id": download_url or guid,
            "name": name,
            "description": summary,
            "version": version,
            "icon_url": icon_url,
            "rating": rating,
        })
    return results


async def search_chrome_webstore(query: str) -> list[dict[str, Any]]:
    """Search Google Chrome Web Store by keyword, or resolve ID/URL directly.

    Tries local network connection first. If local network fails/times out,
    falls back to AntiBrowser-Manager's imported proxy nodes.
    """
    import html
    import urllib.parse

    query = query.strip()
    if not query:
        return []

    # If user provided a 32-char ID or URL, extract it
    direct_id = extract_webstore_id(query)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    }

    url = f"https://chromewebstore.google.com/search/{urllib.parse.quote(query)}"
    page_text = ""
    req_error: Exception | None = None

    # 1. Attempt local network connection first
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=6.0,
            trust_env=True,
        ) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                page_text = resp.text
            else:
                req_error = RuntimeError(f"HTTP {resp.status_code}")
    except Exception as exc:
        logger.debug("Local network Web Store search failed, trying imported proxy: %s", exc)
        req_error = exc

    # 2. If local network failed, fallback to CloakBrowser imported proxy
    if not page_text:
        async with get_imported_proxy_url() as proxy_url:
            if proxy_url:
                try:
                    async with httpx.AsyncClient(
                        proxy=proxy_url,
                        follow_redirects=True,
                        timeout=20.0,
                        trust_env=True,
                    ) as client:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            page_text = resp.text
                            req_error = None
                        else:
                            req_error = RuntimeError(f"HTTP {resp.status_code}")
                except Exception as exc:
                    logger.warning("Web Store search via imported proxy failed for '%s': %s", query, exc)
                    req_error = exc

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # Pre-fill local matches from popular extensions
    q_lower = query.lower()
    for pop in POPULAR_EXTENSIONS:
        if q_lower in pop["name"].lower() or q_lower in pop["id"].lower():
            if pop["id"] not in seen_ids:
                seen_ids.add(pop["id"])
                results.append({
                    "id": pop["id"],
                    "name": pop["name"],
                    "description": pop["description"],
                    "icon_url": None,
                })

    if page_text:
        cards = re.findall(
            r"data-item-id=\"([a-p]{32})\"([\s\S]*?)(?=(?:data-item-id=\"[a-p]{32}\"|<\/section>|$))",
            page_text,
        )
        for ext_id, chunk in cards:
            name_m = re.search(r"<h2[^>]*>([\s\S]*?)</h2>", chunk)
            name = html.unescape(re.sub(r"<[^>]+>", "", name_m.group(1)).strip()) if name_m else ext_id

            img_m = re.search(r"<img[^>]+src=\"([^\"]+)\"", chunk)
            icon_url = img_m.group(1) if img_m else None

            desc_m = re.search(r"<p[^>]*class=\"[^\"]*rQHEi[^\"]*\"[^>]*>([\s\S]*?)</p>", chunk)
            if not desc_m:
                desc_m = re.search(r"<p[^>]*>([\s\S]*?)</p>", chunk)
            desc = html.unescape(re.sub(r"<[^>]+>", "", desc_m.group(1)).strip()) if desc_m else ""

            existing = next((r for r in results if r["id"] == ext_id), None)
            if existing:
                existing["name"] = name
                existing["description"] = desc or existing["description"]
                existing["icon_url"] = icon_url
            elif ext_id not in seen_ids:
                seen_ids.add(ext_id)
                results.append({
                    "id": ext_id,
                    "name": name,
                    "description": desc,
                    "icon_url": icon_url,
                })

    # If direct_id was detected but wasn't in top results, prioritize or include it
    if direct_id and direct_id not in seen_ids:
        results.insert(0, {
            "id": direct_id,
            "name": f"Extension ({direct_id})",
            "description": "Direct Chrome Web Store extension ID match",
            "icon_url": None,
        })

    if not results and req_error is not None:
        raise RuntimeError("网络错误: 无法连接到 Chrome 应用商店，请检查代理节点配置或网络连接")

    return results


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
        try:
            target_path.relative_to(resolved_target)
        except ValueError:
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
    browser_type: str = "cloakbrowser",
) -> dict[str, Any]:
    """Unpack a .crx or .zip file into the managed extensions directory.

    Extensions are stored in an engine-specific subdirectory:
        extensions/chromium/{ext_id}/  – CloakBrowser (Chromium)
        extensions/firefox/{ext_id}/   – Camoufox (Firefox)
    """
    ext_id = webstore_id or str(uuid.uuid4())[:12]
    target_dir = _ext_engine_dir(browser_type) / ext_id

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
        browser_type=browser_type,
    )


def _build_chrome_crx_urls(webstore_id: str) -> list[str]:
    """Construct Chrome Web Store CRX download URLs with platform & MV3 compatibility."""
    import platform
    sys_name = platform.system().lower()
    os_param = "mac" if "darwin" in sys_name else ("win" if "windows" in sys_name else "linux")
    arch_param = "arm64" if "arm" in platform.machine().lower() or "aarch64" in platform.machine().lower() else "x86-64"

    return [
        # 1. Modern Omaha endpoint with high prodversion for MV3 extensions (e.g. Bitwarden)
        (
            f"https://clients2.google.com/service/update2/crx?response=redirect"
            f"&os={os_param}&arch={arch_param}&prod=chromecrx&prodchannel=unknown"
            f"&prodversion=9999.0.9999.0&acceptformat=crx2,crx3&x=id%3D{webstore_id}%26uc"
        ),
        # 2. Modern Omaha endpoint with Chrome 131 version and platform tags
        (
            f"https://clients2.google.com/service/update2/crx?response=redirect"
            f"&os={os_param}&arch={arch_param}&prod=chromecrx&prodchannel="
            f"&prodversion=131.0.6778.86&acceptformat=crx2,crx3&x=id%3D{webstore_id}%26uc"
        ),
        # 3. Standard fallback with 131
        (
            f"https://clients2.google.com/service/update2/crx"
            f"?response=redirect&prodversion=131.0.6778.86&acceptformat=crx2,crx3&x=id%3D{webstore_id}%26uc"
        ),
        # 4. Google UserContent direct
        (
            f"https://clients2.googleusercontent.com/service/update2/crx"
            f"?response=redirect&prodversion=131.0.6778.86&acceptformat=crx2,crx3&x=id%3D{webstore_id}%26uc"
        ),
        # 5. Legacy 128.0 fallback
        (
            f"https://clients2.google.com/service/update2/crx"
            f"?response=redirect&prodversion=128.0&acceptformat=crx2,crx3&x=id%3D{webstore_id}%26uc"
        ),
    ]


async def stream_install_from_webstore(id_or_url: str, browser_type: str = "cloakbrowser") -> AsyncIterator[dict[str, Any]]:
    """Download and install a Chrome extension with live progress events."""
    is_firefox = (browser_type == "camoufox")

    if is_firefox:
        if id_or_url.startswith("http"):
            webstore_id = id_or_url.split("/")[-1].replace(".xpi", "")
            crx_urls = [id_or_url]
        else:
            webstore_id = id_or_url
            crx_urls = [f"https://addons.mozilla.org/firefox/downloads/latest/{id_or_url}/addon-latest.xpi"]
    else:
        webstore_id = extract_webstore_id(id_or_url)
        crx_urls = _build_chrome_crx_urls(webstore_id) if webstore_id else []

    if not webstore_id:
        yield {
            "stage": "error",
            "message": (
                f"Invalid ID or URL: '{id_or_url}'."
            ),
            "percent": 0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
        }
        return

    yield {
        "stage": "connecting",
        "message": "正在连接 Firefox 附加组件..." if is_firefox else "正在连接 Chrome 应用商店...",
        "percent": 0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
    }

    part_file = Path(tempfile.gettempdir()) / f"cloak_ext_{webstore_id.replace('/', '_')}_{os.getpid()}_{int(time.time() * 1000)}.part"
    total_bytes = 0
    downloaded_bytes = 0
    last_yield_time = 0.0
    last_yield_percent = -1
    last_error: Exception | None = None
    success = False

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
    }

    try:
        # Fast local network probe: if local network can reach Web Store within 2.0s, prioritize direct mode
        can_direct = False
        if crx_urls:
            probe_url = crx_urls[0]
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=2.0, trust_env=True) as probe_client:
                    probe_resp = await probe_client.head(probe_url, headers=headers)
                    if probe_resp.status_code in (200, 302, 204):
                        can_direct = True
            except Exception:
                can_direct = False

        # Build list of connection attempts: local first if reachable, otherwise imported proxy candidates first
        candidate_nodes = _get_sorted_candidate_nodes()
        proxy_nodes_to_try = candidate_nodes[:4] if candidate_nodes else [None]

        modes: list[tuple[str, Any]] = []
        if can_direct:
            modes.append(("local", None))
            for n in proxy_nodes_to_try:
                modes.append(("proxy", n))
        else:
            for n in proxy_nodes_to_try:
                modes.append(("proxy", n))
            modes.append(("local", None))

        for mode, node in modes:
            if success:
                break

            node_name = (node.get("name") or node.get("id")) if node else "系统代理"

            if mode == "proxy":
                proxy_context = get_imported_proxy_url(node)
                async with proxy_context as proxy_url:
                    if not proxy_url:
                        continue

                    yield {
                        "stage": "downloading",
                        "message": f"正在通过已导入代理节点 [{node_name}] 下载...",
                        "percent": round((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0,
                        "downloaded_bytes": downloaded_bytes,
                        "total_bytes": total_bytes,
                    }

                    timeout = httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0)
                    max_retries = 2
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
                                "message": f"代理断点续传中 ({attempt + 1}/{max_retries})... [{node_name}] 已下载: {dl_mb} MB{tot_mb}",
                                "percent": pct,
                                "downloaded_bytes": downloaded_bytes,
                                "total_bytes": total_bytes,
                            }
                            await asyncio.sleep(min(1.0 * attempt, 2.0))

                        try:
                            async with httpx.AsyncClient(
                                proxy=proxy_url,
                                follow_redirects=True,
                                timeout=timeout,
                                trust_env=True,
                            ) as client:
                                for crx_url in crx_urls:
                                    req_headers = dict(headers)
                                    if downloaded_bytes > 0:
                                        req_headers["Range"] = f"bytes={downloaded_bytes}-"

                                    try:
                                        async with client.stream("GET", crx_url, headers=req_headers) as resp:
                                            if resp.status_code == 206:
                                                # Partial content (resumed from breakpoint)
                                                content_range = resp.headers.get("content-range", "")
                                                if "/" in content_range:
                                                    total_str = content_range.split("/")[-1].strip()
                                                    if total_str.isdigit():
                                                        total_bytes = int(total_str)
                                                open_mode = "ab"
                                            elif resp.status_code == 200:
                                                tot_header = resp.headers.get("content-length")
                                                total_bytes = int(tot_header) if tot_header and tot_header.isdigit() else 0
                                                downloaded_bytes = 0
                                                open_mode = "wb"
                                            elif resp.status_code == 416:
                                                # Range Not Satisfiable: check if part file is already complete
                                                if part_file.exists() and part_file.stat().st_size > 0:
                                                    try:
                                                        _find_zip_offset(part_file.read_bytes())
                                                        success = True
                                                        break
                                                    except Exception:
                                                        pass
                                                part_file.write_bytes(b"")
                                                downloaded_bytes = 0
                                                continue
                                            else:
                                                last_error = RuntimeError(f"HTTP {resp.status_code}")
                                                continue

                                            with open(part_file, open_mode) as f:
                                                async for chunk in resp.aiter_bytes(chunk_size=65536):
                                                    f.write(chunk)
                                                    downloaded_bytes += len(chunk)
                                                    pct = round((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0
                                                    now = time.monotonic()
                                                    if pct != last_yield_percent or (now - last_yield_time >= 0.15):
                                                        last_yield_percent = pct
                                                        last_yield_time = now
                                                        dl_mb = round(downloaded_bytes / (1024 * 1024), 1)
                                                        tot_mb = f" / {round(total_bytes / (1024 * 1024), 1)} MB" if total_bytes > 0 else ""
                                                        yield {
                                                            "stage": "downloading",
                                                            "message": f"正在通过代理 [{node_name}] 下载: {dl_mb} MB{tot_mb}",
                                                            "percent": pct,
                                                            "downloaded_bytes": downloaded_bytes,
                                                            "total_bytes": total_bytes,
                                                        }

                                            if downloaded_bytes > 0 and (total_bytes == 0 or downloaded_bytes >= total_bytes):
                                                success = True
                                                break
                                    except Exception as exc:
                                        last_error = exc
                                        logger.warning("Stream via proxy node %s interrupted for %s: %s", node_name, webstore_id, exc)
                                    if success:
                                        break
                        except Exception as exc:
                            last_error = exc
                            logger.warning("Proxy client error for node %s (%s): %s", node_name, webstore_id, exc)
            else:
                # Direct local network mode
                timeout = httpx.Timeout(connect=3.0, read=30.0, write=15.0, pool=10.0)
                max_retries = 2
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
                        await asyncio.sleep(min(1.0 * attempt, 2.0))

                    try:
                        async with httpx.AsyncClient(
                            follow_redirects=True,
                            timeout=timeout,
                            trust_env=True,
                        ) as client:
                            for crx_url in crx_urls:
                                req_headers = dict(headers)
                                if downloaded_bytes > 0:
                                    req_headers["Range"] = f"bytes={downloaded_bytes}-"

                                try:
                                    async with client.stream("GET", crx_url, headers=req_headers) as resp:
                                        if resp.status_code == 206:
                                            # Partial content (resumed from breakpoint)
                                            content_range = resp.headers.get("content-range", "")
                                            if "/" in content_range:
                                                total_str = content_range.split("/")[-1].strip()
                                                if total_str.isdigit():
                                                    total_bytes = int(total_str)
                                            open_mode = "ab"
                                        elif resp.status_code == 200:
                                            # Server returned full file
                                            tot_header = resp.headers.get("content-length")
                                            total_bytes = int(tot_header) if tot_header and tot_header.isdigit() else 0
                                            downloaded_bytes = 0
                                            open_mode = "wb"
                                        elif resp.status_code == 416:
                                            # Range Not Satisfiable
                                            if part_file.exists() and part_file.stat().st_size > 0:
                                                try:
                                                    _find_zip_offset(part_file.read_bytes())
                                                    success = True
                                                    break
                                                except Exception:
                                                    pass
                                            part_file.write_bytes(b"")
                                            downloaded_bytes = 0
                                            continue
                                        else:
                                            last_error = RuntimeError(f"HTTP {resp.status_code}")
                                            continue

                                        with open(part_file, open_mode) as f:
                                            async for chunk in resp.aiter_bytes(chunk_size=65536):
                                                f.write(chunk)
                                                downloaded_bytes += len(chunk)
                                                pct = round((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0
                                                now = time.monotonic()
                                                if pct != last_yield_percent or (now - last_yield_time >= 0.15):
                                                    last_yield_percent = pct
                                                    last_yield_time = now
                                                    dl_mb = round(downloaded_bytes / (1024 * 1024), 1)
                                                    tot_mb = f" / {round(total_bytes / (1024 * 1024), 1)} MB" if total_bytes > 0 else ""
                                                    yield {
                                                        "stage": "downloading",
                                                        "message": f"正在直连下载: {dl_mb} MB{tot_mb}",
                                                        "percent": pct,
                                                        "downloaded_bytes": downloaded_bytes,
                                                        "total_bytes": total_bytes,
                                                    }

                                        if downloaded_bytes > 0 and (total_bytes == 0 or downloaded_bytes >= total_bytes):
                                            success = True
                                            break
                                except Exception as exc:
                                    last_error = exc
                                    logger.warning("Stream interrupted (local attempt %d) for %s: %s", attempt + 1, webstore_id, exc)
                                if success:
                                    break
                    except Exception as exc:
                        last_error = exc
                        logger.warning("Local client error (attempt %d) for %s: %s", attempt + 1, webstore_id, exc)

        if not success or not part_file.exists() or part_file.stat().st_size == 0:
            logger.error("Download failed for extension %s: %s", webstore_id, last_error)
            err_str = str(last_error or "")
            if "HTTP 204" in err_str:
                err_msg = "Chrome 应用商店未提供该扩展安装包 (HTTP 204)。该扩展可能已被 Google 下架、已废弃或不支持当前平台，建议使用本地 .crx / .zip 上传安装。"
            elif is_firefox and "HTTP 404" in err_str:
                err_msg = "Firefox 附加组件未找到该扩展 (HTTP 404)。"
            else:
                err_msg = (
                    "网络错误: 无法连接到 Firefox 附加组件，请检查代理节点配置或网络连接"
                    if is_firefox
                    else "网络错误: 无法连接到 Chrome 应用商店，请检查代理节点配置或网络连接"
                )
            yield {
                "stage": "error",
                "message": err_msg,
                "percent": 0,
                "downloaded_bytes": downloaded_bytes,
                "total_bytes": total_bytes,
            }
            return

        yield {
            "stage": "unpacking",
            "message": "下载完成，正在解压并安装...",
            "percent": 100,
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
        }

        try:
            file_bytes = part_file.read_bytes()
            ext = await install_extension_from_bytes(
                file_bytes=file_bytes,
                filename=f"{webstore_id.replace('/', '_')}.xpi" if is_firefox else f"{webstore_id}.crx",
                source="webstore_id",
                webstore_id=webstore_id,
                browser_type=browser_type,
            )
            yield {
                "stage": "completed",
                "message": f"成功安装扩展 {ext['name']}！",
                "percent": 100,
                "downloaded_bytes": downloaded_bytes,
                "total_bytes": total_bytes,
                "extension": ext,
            }
        except Exception as exc:
            logger.error("Failed to unpack extension %s: %s", webstore_id, exc)
            yield {
                "stage": "error",
                "message": f"解压安装失败: {exc}",
                "percent": 0,
                "downloaded_bytes": downloaded_bytes,
                "total_bytes": total_bytes,
            }
    finally:
        if part_file.exists():
            try:
                part_file.unlink(missing_ok=True)
            except Exception:
                pass


async def install_from_webstore(id_or_url: str, browser_type: str = "cloakbrowser") -> dict[str, Any]:
    """Download and install an extension directly from Google Chrome Web Store or Firefox Addons."""
    last_event: dict[str, Any] | None = None
    async for event in stream_install_from_webstore(id_or_url, browser_type):
        last_event = event

    if not last_event or last_event.get("stage") != "completed":
        err_msg = last_event.get("message") if last_event else "下载安装失败"
        raise RuntimeError(err_msg)

    return last_event["extension"]


def remove_extension(ext_id: str) -> bool:
    """Remove an installed extension from disk and database."""
    ext = get_extension(ext_id)
    if not ext:
        return False

    target_dir = Path(ext["path"])
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)

    return delete_extension(ext_id)


async def check_extensions_updates() -> dict[str, Any]:
    """Check for available updates for all installed extensions via Chrome Omaha protocol.

    - Tries direct local network first; falls back to imported proxy if network is restricted.
    - Web Store extensions (source='webstore_id') are queried against Google's update2 service.
    - Uploaded/manual extensions are marked as 'unsupported' (manual upload).
    """
    import xml.etree.ElementTree as ET
    from .database import list_extensions

    installed = list_extensions()
    results: dict[str, dict[str, Any]] = {}
    query_items: list[tuple[str, str, str]] = []  # (db_id, webstore_id, current_version)

    for ext in installed:
        ext_id = ext["id"]
        cur_version = ext.get("version", "0.0.0")
        source = ext.get("source", "upload")
        webstore_id = ext.get("webstore_id")

        if source == "webstore_id" and webstore_id and _EXT_ID_RE.match(webstore_id):
            query_items.append((ext_id, webstore_id, cur_version))
        else:
            results[ext_id] = {
                "has_update": False,
                "current_version": cur_version,
                "latest_version": None,
                "status": "unsupported",
            }

    if not query_items:
        return {"updates": results, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    # Construct Omaha query params: x=id%3D{ext_id}%26v%3D{current_version}%26uc
    params = [f"x=id%3D{wid}%26v%3D{ver}%26uc" for _, wid, ver in query_items]
    query_str = "&".join(params)
    url = f"https://clients2.google.com/service/update2/crx?{query_str}&acceptformat=crx2,crx3&prodversion=9999.0.9999.0"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
    }

    resp_text = ""
    req_err = None

    # 1. Try local network first
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=6.0, trust_env=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                resp_text = resp.text
            else:
                req_err = RuntimeError(f"HTTP {resp.status_code}")
    except Exception as exc:
        req_err = exc

    # 2. Try imported proxy if local failed
    if not resp_text:
        async with get_imported_proxy_url() as proxy_url:
            if proxy_url:
                try:
                    async with httpx.AsyncClient(proxy=proxy_url, follow_redirects=True, timeout=15.0, trust_env=True) as client:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            resp_text = resp.text
                            req_err = None
                        else:
                            req_err = RuntimeError(f"HTTP {resp.status_code}")
                except Exception as exc:
                    req_err = exc

    if not resp_text:
        logger.warning("Failed to check extension updates: %s", req_err)
        for db_id, _, cur_ver in query_items:
            results[db_id] = {
                "has_update": False,
                "current_version": cur_ver,
                "latest_version": None,
                "status": "error",
                "error": str(req_err) if req_err else "Network error",
            }
        return {"updates": results, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    # Parse XML response
    try:
        root = ET.fromstring(resp_text)
        app_results: dict[str, tuple[str, str | None]] = {}
        for elem in root.iter():
            if elem.tag.endswith("app"):
                appid = elem.get("appid")
                if not appid:
                    continue
                for child in elem:
                    if child.tag.endswith("updatecheck"):
                        st = child.get("status", "unknown")
                        ver = child.get("version")
                        app_results[appid] = (st, ver)

        for db_id, wid, cur_ver in query_items:
            st, latest_ver = app_results.get(wid, ("unknown", None))
            if st == "ok" and latest_ver:
                has_up = latest_ver != cur_ver
                results[db_id] = {
                    "has_update": has_up,
                    "current_version": cur_ver,
                    "latest_version": latest_ver,
                    "status": "update_available" if has_up else "up_to_date",
                }
            elif st == "noupdate":
                results[db_id] = {
                    "has_update": False,
                    "current_version": cur_ver,
                    "latest_version": cur_ver,
                    "status": "up_to_date",
                }
            else:
                results[db_id] = {
                    "has_update": False,
                    "current_version": cur_ver,
                    "latest_version": None,
                    "status": "unknown",
                }
    except Exception as exc:
        logger.warning("Failed to parse update XML: %s", exc)
        for db_id, _, cur_ver in query_items:
            results[db_id] = {
                "has_update": False,
                "current_version": cur_ver,
                "latest_version": None,
                "status": "error",
                "error": str(exc),
            }

    return {"updates": results, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

async def rebuild_missing_extensions() -> None:
    """Silently download and reinstall WebStore extensions whose physical files are missing (e.g., after backup restore)."""
    try:
        from .database import list_extensions
        installed = list_extensions()
    except Exception as exc:
        logger.error("Failed to query extensions for rebuild: %s", exc)
        return

    to_rebuild = []
    for ext in installed:
        if ext.get("source") != "webstore_id" or not ext.get("webstore_id"):
            continue
        p = Path(ext.get("path") or "")
        if not p.is_dir() or not any(p.iterdir()):
            to_rebuild.append(ext)

    if not to_rebuild:
        return

    logger.info("Starting silent rebuild for %d missing webstore extension(s)...", len(to_rebuild))

    for ext in to_rebuild:
        wid = ext["webstore_id"]
        btype = ext.get("browser_type") or "cloakbrowser"
        name = ext.get("name", wid)
        logger.info("Rebuilding missing extension: %s (ID: %s, Browser: %s)", name, wid, btype)
        try:
            success = False
            async for progress in stream_install_from_webstore(wid, browser_type=btype):
                if progress.get("stage") == "installed":
                    success = True
                    break
                elif progress.get("stage") == "error":
                    logger.warning("Rebuild failed for %s: %s", name, progress.get("message"))
                    break
            if success:
                logger.info("Successfully rebuilt extension %s", name)
        except Exception as exc:
            logger.warning("Error while rebuilding extension %s: %s", name, exc)
