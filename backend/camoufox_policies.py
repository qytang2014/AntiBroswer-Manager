"""Camoufox policy and search engine management.

Camoufox by default ships an aggressive anti-fingerprinting enterprise policy that:
1. Uninstalls webcompat@mozilla.org, google@search.mozilla.org, and bing@search.mozilla.org,
   which severely breaks web compatibility on major websites.
2. Removes all standard search engines (Google, Bing, DuckDuckGo) and installs a dummy
   engine named "None" pointing to "http://127.0.0.1" with PreventInstalls=True.
   This causes any address bar search to fail or attempt navigating to localhost.

This module sanitizes and manages Camoufox's policies and profile preferences so that:
- The user's preset default search engine (Google, Bing, or custom) functions normally.
- Address bar keyword search works seamlessly.
- webcompat and built-in search integrations remain active for full web compatibility.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .runtime import resolve_runtime

logger = logging.getLogger("cloakbrowser.manager.camoufox_policies")

SEARCH_ENGINE_NAME = "Google"
SEARCH_ENGINE_URL = "https://www.google.com/search?ie={inputEncoding}&q=%s"


def resolve_camoufox_distribution_dir(exe_path: Path) -> Path:
    """Find or create the distribution directory for a Camoufox binary."""
    p_str = str(exe_path)
    if "Camoufox.app" in p_str or "Contents/MacOS" in p_str:
        dist = exe_path.parent.parent / "Resources" / "distribution"
    else:
        dist = exe_path.parent / "distribution"
    dist.mkdir(parents=True, exist_ok=True)
    return dist


def sanitize_camoufox_policies(
    dist_dir: Path,
    default_engine_name: str = SEARCH_ENGINE_NAME,
    default_engine_url: str | None = None,
) -> bool:
    """Sanitize and write policies.json in dist_dir to support search and webcompat."""
    pol_file = dist_dir / "policies.json"
    data: dict[str, Any] = {}
    if pol_file.exists():
        try:
            with open(pol_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning("Failed to parse existing policies.json at %s: %s", pol_file, exc)
            data = {}

    policies = data.setdefault("policies", {})

    # 1. Extensions.Uninstall: Ensure webcompat, google, and bing search extensions are NOT uninstalled
    exts = policies.setdefault("Extensions", {})
    uninstall = exts.get("Uninstall", [])
    if isinstance(uninstall, list):
        exts["Uninstall"] = [
            e
            for e in uninstall
            if e
            not in (
                "webcompat@mozilla.org",
                "google@search.mozilla.org",
                "bing@search.mozilla.org",
            )
        ]

    # 2. Configure default search engine
    engine_name = default_engine_name or SEARCH_ENGINE_NAME
    engine_url = default_engine_url or SEARCH_ENGINE_URL
    # Firefox OpenSearch URLTemplate uses {searchTerms} instead of %s
    ff_url_template = engine_url.replace("%s", "{searchTerms}")

    search_engines = policies.setdefault("SearchEngines", {})
    search_engines["PreventInstalls"] = False
    search_engines["Default"] = engine_name

    # Remove any destructive remove list or fake "None" engine
    if "Remove" in search_engines:
        search_engines["Remove"] = [
            r
            for r in search_engines.get("Remove", [])
            if str(r).lower() != engine_name.lower() and str(r).lower() not in ("google", "bing", "duckduckgo")
        ]
        if not search_engines["Remove"]:
            del search_engines["Remove"]

    add_list = search_engines.get("Add", [])
    if not isinstance(add_list, list):
        add_list = []
    # Filter out any "None" dummy engine
    add_list = [e for e in add_list if isinstance(e, dict) and e.get("Name") != "None"]

    # Ensure our target engine is defined in Add if custom URL or not default built-in
    existing = next(
        (e for e in add_list if isinstance(e, dict) and e.get("Name") == engine_name),
        None,
    )
    if existing:
        existing["URLTemplate"] = ff_url_template
        existing["Method"] = "GET"
    else:
        add_list.append({
            "Name": engine_name,
            "URLTemplate": ff_url_template,
            "Method": "GET",
            "Description": f"{engine_name} Search",
        })
    search_engines["Add"] = add_list

    try:
        with open(pol_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as exc:
        logger.warning("Failed to write sanitized Camoufox policies.json at %s: %s", pol_file, exc)
        return False


def sanitize_camoufox_profile_search_cache(
    user_data_dir: Path,
    target_engine_name: str = SEARCH_ENGINE_NAME,
) -> None:
    """Clean stale dummy search engine prefs or search cache in a profile directory."""
    if not user_data_dir.exists():
        return

    # 1. Clean stale prefs in prefs.js
    prefs_js = user_data_dir / "prefs.js"
    if prefs_js.exists():
        try:
            content = prefs_js.read_text(encoding="utf-8")
            stale_keys = (
                "removeSearchEngines",
                'setDefaultSearchEngine", "None"',
                "extensionsUninstall",
                'placeholderName", "None"',
            )
            lines = content.splitlines()
            cleaned_lines = [
                line for line in lines if not any(k in line for k in stale_keys)
            ]
            if len(cleaned_lines) != len(lines):
                prefs_js.write_text("\n".join(cleaned_lines) + "\n", encoding="utf-8")
                logger.info("Cleaned %d stale search policy pref lines in %s", len(lines) - len(cleaned_lines), prefs_js)
        except Exception as exc:
            logger.warning("Failed to sanitize prefs.js at %s: %s", prefs_js, exc)

    # 2. Reset search.json.mozlz4 if it contains the dummy "None" engine (indicated by small size < 500B)
    search_moz = user_data_dir / "search.json.mozlz4"
    if search_moz.exists():
        try:
            if search_moz.stat().st_size < 500:
                search_moz.unlink(missing_ok=True)
                logger.info("Removed stale dummy search engine cache %s", search_moz)
        except Exception as exc:
            logger.warning("Failed to inspect/remove search.json.mozlz4 at %s: %s", search_moz, exc)


def get_camoufox_recommended_fonts(target_os: str = "macos") -> list[str]:
    """Return essential system fonts that must remain accessible to the browser.

    This prevents Camoufox's setFontList mechanism from locking out standard system
    fonts (especially monospace fonts used by code/hashes), which would otherwise cause
    fallback to decorative/symbol fonts and render text as gibberish glyphs.
    """
    if target_os == "macos":
        return [
            "Menlo",
            "Monaco",
            "Courier New",
            "Courier",
            "Arial",
            "Helvetica Neue",
            "Times New Roman",
            "PingFang SC",
            "Hiragino Sans GB",
        ]
    elif target_os == "windows":
        return [
            "Consolas",
            "Courier New",
            "Arial",
            "Times New Roman",
            "Segoe UI",
            "Calibri",
            "Microsoft YaHei",
        ]
    return [
        "monospace",
        "sans-serif",
        "serif",
        "DejaVu Sans",
        "Liberation Sans",
        "Liberation Mono",
    ]


def get_camoufox_user_prefs(
    profile: dict[str, Any],
    target_os: str = "macos",
    timezone: str | None = None,
    locale: str | None = None,
    downloads_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Build Firefox user preferences for search, compatibility, fonts, and network fingerprint."""
    engine_name = profile.get("search_engine_name") or SEARCH_ENGINE_NAME
    resolved_dl = str(downloads_dir or (Path.home() / "Downloads"))

    prefs: dict[str, Any] = {
        # Enable address bar search using the configured default search engine
        "keyword.enabled": True,
        "browser.urlbar.suggest.searches": True,
        "browser.urlbar.suggest.engines": True,
        "browser.urlbar.maxRichResults": 10,
        "browser.search.defaultenginename": engine_name,
        "browser.urlbar.placeholderName": engine_name,
        # Native download settings: ensure Firefox downloads trigger directly and save to Downloads
        "browser.download.folderList": 2,
        "browser.download.dir": resolved_dl,
        "browser.download.downloadDir": resolved_dl,
        "browser.download.defaultFolder": resolved_dl,
        "browser.download.useDownloadDir": True,
        "browser.download.manager.showWhenStarting": False,
        "browser.download.panel.shown": True,
        "browser.download.alwaysOpenPanel": True,
        "browser.download.autohideButton": False,
        "browser.download.forbid_open_with": False,
        "browser.download.improvements_to_download_panel": True,
        "browser.download.manager.addToRecentDocs": True,
        "browser.helperApps.alwaysAsk.force": False,
        "browser.helperApps.neverAsk.saveToDisk": (
            "application/octet-stream,application/zip,application/x-zip-compressed,"
            "application/x-tar,application/gzip,application/x-gzip,application/x-bzip2,"
            "application/x-7z-compressed,application/x-rar-compressed,application/pdf,"
            "application/x-download,application/vnd.android.package-archive,"
            "application/x-apple-diskimage,application/x-msdownload,application/exe,"
            "application/x-exe,application/dos-exe,application/x-winexe,"
            "text/plain,text/csv,image/png,image/jpeg,image/gif,image/webp,"
            "video/mp4,audio/mpeg,application/json,application/xml"
        ),
        "browser.helperApps.neverAsk.openFile": (
            "application/octet-stream,application/zip,application/x-zip-compressed,"
            "application/x-tar,application/gzip,application/x-gzip,application/x-bzip2,"
            "application/x-7z-compressed,application/x-rar-compressed,application/pdf,"
            "application/x-download,application/vnd.android.package-archive,"
            "application/x-apple-diskimage,application/x-msdownload,application/exe,"
            "application/x-exe,application/dos-exe,application/x-winexe,"
            "text/plain,text/csv,image/png,image/jpeg,image/gif,image/webp,"
            "video/mp4,audio/mpeg,application/json,application/xml"
        ),
        "pdfjs.disabled": True,
        # Web compatibility: restore standard HTML5 features
        "dom.iframe_lazy_loading.enabled": True,
        # Media devices & WebRTC probe smoothness: avoid hanging on permission dialogs during tests
        "media.navigator.permission.disabled": True,
        "media.navigator.enabled": True,
    }

    # Explicit fallback font families to prevent font/glyph corruption (乱码) across platforms
    if target_os == "macos":
        prefs.update({
            "font.name.monospace.x-western": "Courier New",
            "font.name.sans-serif.x-western": "Arial",
            "font.name.serif.x-western": "Times New Roman",
            "font.name.monospace.zh-CN": "PingFang SC",
            "font.name.sans-serif.zh-CN": "PingFang SC",
            "font.name.serif.zh-CN": "Songti SC",
        })
    elif target_os == "windows":
        prefs.update({
            "font.name.monospace.x-western": "Consolas",
            "font.name.sans-serif.x-western": "Arial",
            "font.name.serif.x-western": "Times New Roman",
            "font.name.monospace.zh-CN": "Microsoft YaHei",
            "font.name.sans-serif.zh-CN": "Microsoft YaHei",
        })
    else:
        prefs.update({
            "font.name.monospace.x-western": "monospace",
            "font.name.sans-serif.x-western": "sans-serif",
            "font.name.serif.x-western": "serif",
        })

    # Timezone preference for Roverfox/Camoufox engine
    if timezone:
        prefs["roverfox.s.timezone_0"] = timezone

    # Language/locale preferences
    if locale:
        lang = locale.split("-")[0]
        prefs["intl.accept_languages"] = f"{locale}, {lang}"

    # Third-party cookie behavior matching profile config
    if profile.get("allow_3p_cookies", True):
        prefs["network.cookie.cookieBehavior"] = 0
    else:
        prefs["network.cookie.cookieBehavior"] = 4

    return prefs


def sanitize_all_installed_camoufox_kernels(
    default_engine_name: str = SEARCH_ENGINE_NAME,
    default_engine_url: str | None = None,
) -> int:
    """Scan and sanitize policies.json for all installed Camoufox browser binaries."""
    sanitized_count = 0
    candidate_roots = [
        resolve_runtime().data_dir / "kernels" / "camoufox" / "browsers",
    ]
    try:
        from camoufox.pkgman import INSTALL_DIR
        candidate_roots.append(INSTALL_DIR / "browsers")
    except Exception:
        pass

    for root in candidate_roots:
        if not root.exists():
            continue
        # Find all policies.json files under root
        for pol_file in root.rglob("policies.json"):
            if "distribution" in pol_file.parts:
                if sanitize_camoufox_policies(pol_file.parent, default_engine_name, default_engine_url):
                    sanitized_count += 1

    return sanitized_count
