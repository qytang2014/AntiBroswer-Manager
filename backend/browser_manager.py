"""Launch/stop/track CloakBrowser instances per profile."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
import re
import shutil
import socket
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloakbrowser import launch_persistent_context_async
from cloakbrowser.config import get_binary_path
from cloakbrowser.download import _is_executable, binary_info
from cloakbrowser.license import (
    CloakBrowserLicenseError,
    license_error_for_code,
    read_denial_file,
)

from .runtime import RuntimeConfig, resolve_runtime
from .vnc_manager import VNCManager

logger = logging.getLogger("cloakbrowser.manager.browser")

# Ensure Playwright allows loading extensions by suppressing its default --disable-extensions flag
try:
    import cloakbrowser.config
    if "--disable-extensions" not in cloakbrowser.config.IGNORE_DEFAULT_ARGS:
        cloakbrowser.config.IGNORE_DEFAULT_ARGS.append("--disable-extensions")
except Exception:
    pass

# Preserve acceptDownloads="internal-browser-default" in Playwright's protocol layer
# so Playwright does not intercept downloads with Juggler (Firefox) or CDP allowAndName (Chromium),
# allowing native browser download UI, download panel, and about:downloads history to function.
def _ensure_playwright_internal_download_patch() -> None:
    """Ensure Playwright driver coreBundle.js preserves 'internal-browser-default'."""
    candidate_bundles: list[Path] = []
    try:
        import inspect
        import playwright
        driver_dir = Path(inspect.getfile(playwright)).parent / "driver"
        candidate_bundles.append(driver_dir / "package" / "lib" / "coreBundle.js")
    except Exception:
        pass

    import sys
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        # Standard one-file/one-dir Windows/Linux
        candidate_bundles.append(Path(meipass) / "playwright" / "driver" / "package" / "lib" / "coreBundle.js")
        # macOS BUNDLE (.app) places data files in Contents/Resources
        candidate_bundles.append(Path(meipass).parent / "Resources" / "playwright" / "driver" / "package" / "lib" / "coreBundle.js")

    workspace = Path(__file__).resolve().parent.parent
    for sub in ("dist_native", ".venv-build"):
        cb = workspace / sub / "AntiBrowser-Manager" / "_internal" / "playwright" / "driver" / "package" / "lib" / "coreBundle.js"
        if cb.exists():
            candidate_bundles.append(cb)
        cb2 = workspace / sub / "lib" / "python3.10" / "site-packages" / "playwright" / "driver" / "package" / "lib" / "coreBundle.js"
        if cb2.exists():
            candidate_bundles.append(cb2)

    for core_bundle in candidate_bundles:
        try:
            if not core_bundle.exists():
                continue
            content = core_bundle.read_text(encoding="utf-8")
            if 'if (acceptDownloads === "internal-browser-default")\n    return "internal-browser-default";' in content or \
               'if (acceptDownloads === "internal-browser-default") return "internal-browser-default";' in content:
                continue

            target = 'function toAcceptDownloadsProtocol(acceptDownloads) {\n  if (acceptDownloads === void 0)\n    return void 0;\n  if (acceptDownloads)\n    return "accept";'
            replacement = 'function toAcceptDownloadsProtocol(acceptDownloads) {\n  if (acceptDownloads === void 0)\n    return void 0;\n  if (acceptDownloads === "internal-browser-default")\n    return "internal-browser-default";\n  if (acceptDownloads)\n    return "accept";'
            if target in content:
                core_bundle.write_text(content.replace(target, replacement, 1), encoding="utf-8")
                logger.info("Applied internal-browser-default patch to %s", core_bundle)
            else:
                pattern = re.compile(r'(function\s+toAcceptDownloadsProtocol\s*\(\s*acceptDownloads\s*\)\s*\{\s*if\s*\(\s*acceptDownloads\s*===\s*void 0\s*\)\s*return void 0;)')
                if pattern.search(content):
                    patched = pattern.sub(r'\1\n  if (acceptDownloads === "internal-browser-default") return "internal-browser-default";', content, count=1)
                    core_bundle.write_text(patched, encoding="utf-8")
                    logger.info("Applied regex internal-browser-default patch to %s", core_bundle)
        except Exception as exc:
            logger.debug("Failed to apply Playwright internal download patch to %s: %s", core_bundle, exc)

_ensure_playwright_internal_download_patch()

try:
    from playwright._impl import _browser_type as _pw_bt
    _orig_prepare_ctx_params = _pw_bt.BrowserType._prepare_browser_context_params

    async def _patched_prepare_ctx_params(self: Any, params: dict[str, Any]) -> None:
        raw_accept = params.get("acceptDownloads")
        await _orig_prepare_ctx_params(self, params)
        if raw_accept == "internal-browser-default":
            params["acceptDownloads"] = "internal-browser-default"

    _pw_bt.BrowserType._prepare_browser_context_params = _patched_prepare_ctx_params
except Exception as _patch_exc:
    logger.debug("Could not patch playwright acceptDownloads: %s", _patch_exc)


UPGRADE_URL = "https://cloakbrowser.dev/#pricing"


def is_seat_limit_error(exc: BaseException) -> bool:
    """True if a license error is specifically the concurrency-seat denial (76).

    The wrapper turns exit code 76 into a message containing "session limit
    reached"; the other license codes (invalid/expired key, server unreachable,
    local config) carry different text. Used to attach the upgrade CTA only to
    the out-of-seats case.
    """
    return "session limit reached" in str(exc).lower()


def license_error_detail(exc: BaseException) -> dict[str, str]:
    """Build the structured launch-error payload the frontend renders.

    ``{message, reason, upgrade_url?}`` — reason is "seat_limit" (out of seats,
    with an upgrade CTA) or "license" (bad/expired/revoked key, server
    unreachable, local config). Shared by the synchronous launch-raises path
    (main.py) and the post-handshake close path (_on_browser_closed).
    """
    seat = is_seat_limit_error(exc)
    detail: dict[str, str] = {
        "message": str(exc),
        "reason": "seat_limit" if seat else "license",
    }
    if seat:
        detail["upgrade_url"] = UPGRADE_URL
    return detail


def _cleanup_stale_chromium_locks(user_data_dir: Path | str) -> None:
    """Remove stale Chromium Singleton lock files if the owning process is no longer running."""
    udd = Path(user_data_dir)
    lock_file = udd / "SingletonLock"
    if lock_file.is_symlink() or lock_file.exists():
        try:
            target = os.readlink(lock_file)
            parts = target.rsplit("-", 1)
            if len(parts) == 2 and parts[1].isdigit():
                pid = int(parts[1])
                try:
                    os.kill(pid, 0)
                    # Process is still alive; do not remove locks
                    return
                except (ProcessLookupError, PermissionError):
                    # Process is dead or defunct
                    pass
            for f_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                p = udd / f_name
                if p.is_symlink() or p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
        except Exception:
            pass


def _resolve_downloads_dir(runtime: RuntimeConfig) -> Path:
    """Resolve standard user Downloads directory with safe fallback."""
    candidate = Path.home() / "Downloads"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        fb = runtime.data_dir / "downloads"
        fb.mkdir(parents=True, exist_ok=True)
        return fb


def _configure_chromium_download_prefs(user_data_dir: Path | str, downloads_dir: Path) -> None:
    """Preconfigure Chromium Preferences so downloads go directly to Downloads folder without prompting."""
    try:
        pref_file = Path(user_data_dir) / "Default" / "Preferences"
        data: dict[str, Any] = {}
        if pref_file.exists():
            try:
                data = json.loads(pref_file.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        dl_str = str(downloads_dir)
        download_dict = data.setdefault("download", {})
        download_dict["default_directory"] = dl_str
        download_dict["directory_upgrade"] = True
        download_dict["prompt_for_download"] = False
        data.setdefault("savefile", {})["default_directory"] = dl_str
        bubble_dict = data.setdefault("download_bubble", {})
        bubble_dict["partial_view_enabled"] = True
        pref_file.parent.mkdir(parents=True, exist_ok=True)
        pref_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.debug("Failed to preconfigure Chromium download preferences: %s", exc)


# LRU Cache for proxy test results: cache_key -> (timestamp, result_dict)
_PROXY_TEST_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_PROXY_TEST_LOCKS: dict[str, asyncio.Lock] = {}
_PROXY_CACHE_TTL = 30.0  # seconds


def _is_singbox_proxy(proxy: Any) -> bool:
    """Return True if proxy config represents a sing-box outbound."""
    if isinstance(proxy, dict):
        return proxy.get("type") == "singbox" or "outbounds" in proxy
    if isinstance(proxy, str):
        p = proxy.strip()
        if p.startswith((
            "vless://", "vmess://", "trojan://", "ss://", "shadowsocks://",
            "hysteria2://", "hy2://", "tuic://", "wireguard://",
        )):
            return True
        if p.startswith("{") and p.endswith("}"):
            try:
                data = json.loads(p)
                return isinstance(data, dict) and (data.get("type") == "singbox" or "outbounds" in data)
            except Exception:
                return False
    return False


def _normalize_proxy(raw: Any, proxy_type: str | None = None) -> Any:
    """Convert common proxy formats to standard format or sing-box config dict.

    Accepts:
      - sing-box URI (vless://, vmess://, etc.) -> {"type": "singbox", "config": ...}
      - sing-box JSON dict or JSON string -> {"type": "singbox", "config": ...}
      - sing-box subscription URL -> {"type": "singbox", "config": url}
      - http://user:pass@host:port  (standard proxy)
      - host:port:user:pass
      - host:port
    """
    if not raw:
        return None

    if isinstance(raw, dict):
        if raw.get("type") == "singbox":
            return raw
        if "outbounds" in raw:
            return {"type": "singbox", "config": raw}
        return raw

    if not isinstance(raw, str):
        return raw

    raw = raw.strip()
    if not raw:
        return None

    # Explicit singbox proxy types from frontend
    if proxy_type == "singbox_json" or (raw.startswith("{") and raw.endswith("}")):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                if parsed.get("type") == "singbox":
                    return parsed
                return {"type": "singbox", "config": parsed}
        except Exception:
            pass

    if proxy_type in ("singbox_uri", "singbox_sub") or (
        proxy_type != "standard"
        and raw.startswith((
            "vless://", "vmess://", "trojan://", "ss://", "shadowsocks://",
            "hysteria2://", "hy2://", "tuic://", "wireguard://",
            "anytls://",
        ))
    ):
        return {"type": "singbox", "config": raw}

    # If it's a standard URL but we specifically want it managed by singbox
    if proxy_type == "singbox" and raw.startswith(("http://", "https://", "socks5://", "socks://")):
        return {"type": "singbox", "config": raw}

    # If it's a standard URL with a scheme, return it as-is
    if "://" in raw:
        return raw

    # host:port:user:pass or host:port
    parts = raw.split(":")
    if len(parts) == 4:
        host, port, user, passwd = parts
        return f"http://{user}:{passwd}@{host}:{port}"
    if len(parts) == 2:
        return f"http://{raw}"
    return raw


def _validate_proxy(proxy: Any) -> None:
    """Validate proxy URL or sing-box configuration dict."""
    if proxy is None or proxy == "direct":
        return

    if isinstance(proxy, dict) and proxy.get("type") == "singbox":
        try:
            from backend.singbox.parser import build_singbox_config
            build_singbox_config(proxy["config"])
            return
        except Exception as exc:
            raise ValueError(f"Invalid sing-box configuration: {exc}") from exc

    url = str(proxy)
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", "socks5", "socks"):
        raise ValueError(
            f"Invalid proxy scheme '{parsed.scheme}'. Must be http, https, socks5, or a sing-box node."
        )
    if not parsed.hostname:
        raise ValueError(f"Proxy URL missing hostname: {url}")
    if not parsed.port:
        raise ValueError(f"Proxy URL missing port: {url}")


async def test_proxy(raw_proxy: Any, proxy_type: str | None = None, force: bool = False) -> dict[str, Any]:
    """Connect through a proxy, return exit IP + geo + latency (or an error).

    Includes 30s LRU caching and concurrency locking to avoid resource exhaustion
    from rapid repeated clicks. When force is True or testing direct connection,
    cache is bypassed to ensure live network accuracy.
    """
    is_direct = not raw_proxy or proxy_type == "direct" or raw_proxy == "direct"
    use_cache = not force and not is_direct

    cache_key = f"{proxy_type}:{raw_proxy if isinstance(raw_proxy, str) else json.dumps(raw_proxy, sort_keys=True)}"
    now = time.monotonic()
    if use_cache and cache_key in _PROXY_TEST_CACHE:
        cached_time, cached_result = _PROXY_TEST_CACHE[cache_key]
        if now - cached_time < _PROXY_CACHE_TTL:
            return {**cached_result, "cached": True}

    lock = _PROXY_TEST_LOCKS.setdefault(cache_key, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        if use_cache and cache_key in _PROXY_TEST_CACHE:
            cached_time, cached_result = _PROXY_TEST_CACHE[cache_key]
            if now - cached_time < _PROXY_CACHE_TTL:
                return {**cached_result, "cached": True}

        if is_direct:
            proxy = None
        else:
            proxy = _normalize_proxy(raw_proxy, proxy_type)
            _validate_proxy(proxy)  # raises ValueError on bad format -> 400 in the route
        res = await asyncio.to_thread(_test_proxy_sync, proxy)
        if res.get("ok"):
            _PROXY_TEST_CACHE[cache_key] = (time.monotonic(), res)
        return res


_FAST_SPEED_TEST_URLS = [
    "http://cp.cloudflare.com/generate_204",
    "http://www.gstatic.com/generate_204",
]

_FAST_IP_ECHO_URLS = [
    "https://api.ip.sb/ip",
    "https://icanhazip.com",
    "https://checkip.amazonaws.com",
    "https://ipinfo.io/ip",
]


def _probe_proxy_target(target_proxy_url: str) -> tuple[str | None, int | None, str | None]:
    """Probe proxy for latency (RTT) and exit IP using fast endpoints.

    Returns (exit_ip, latency_ms, error).
    """
    import ipaddress
    import httpx

    latency_ms = None
    exit_ip = None
    last_err = None
    trust_env = False if target_proxy_url is None else True

    # 1. Pure RTT latency check (fast 204 HTTP response, 2.5s timeout)
    for test_url in _FAST_SPEED_TEST_URLS:
        try:
            t0 = time.monotonic()
            resp = httpx.get(
                test_url,
                proxy=target_proxy_url,
                timeout=httpx.Timeout(2.5),
                follow_redirects=True,
                trust_env=trust_env,
            )
            if resp.status_code in (200, 204):
                latency_ms = max(1, round((time.monotonic() - t0) * 1000))
                break
        except Exception as exc:
            last_err = str(exc)
            continue

    # 2. Fast Exit IP resolution (2.5s timeout, avoiding hanging services like api.ipify.org)
    for ip_url in _FAST_IP_ECHO_URLS:
        try:
            t0 = time.monotonic()
            resp = httpx.get(
                ip_url,
                proxy=target_proxy_url,
                timeout=httpx.Timeout(2.5),
                trust_env=trust_env,
            )
            if resp.status_code == 200:
                raw_ip = resp.text.strip()
                ipaddress.ip_address(raw_ip)
                exit_ip = raw_ip
                if latency_ms is None:
                    latency_ms = max(1, round((time.monotonic() - t0) * 1000))
                break
        except Exception as exc:
            last_err = str(exc)
            continue

    return exit_ip, latency_ms, last_err


def _test_proxy_sync(proxy: Any) -> dict[str, Any]:
    from cloakbrowser.geoip import _ensure_geoip_db

    ip = None
    latency_ms = None
    last_err = None

    try:
        if not proxy or proxy == "direct":
            ip, latency_ms, last_err = _probe_proxy_target(None)
        elif isinstance(proxy, dict) and proxy.get("type") == "singbox":
            from backend.singbox_runner import fast_singbox_proxy

            with fast_singbox_proxy(proxy) as target_proxy_url:
                ip, latency_ms, last_err = _probe_proxy_target(target_proxy_url)
        else:
            ip, latency_ms, last_err = _probe_proxy_target(proxy)
    except Exception as exc:  # SOCKS w/o socksio, connection refused, etc.
        logger.warning("Proxy test failed: %s", exc)
        return {"ok": False, "error": f"Could not connect through proxy: {exc}"}

    if not ip:
        return {"ok": False, "error": last_err or "Proxy did not return an exit IP (timeout or blocked)"}
    from backend.geoip_resolver import resolve_ip_geo

    geo = resolve_ip_geo(ip)
    country = geo.get("country")
    city = geo.get("city")
    timezone = geo.get("timezone")
    locale = geo.get("locale")

    return {
        "ok": True,
        "ip": ip,
        "country": country,
        "city": city,
        "timezone": timezone,
        "locale": locale,
        "latency_ms": latency_ms if latency_ms is not None else 0,
        "cached": False,
    }


def _resolve_profile_network_fingerprint_sync(
    proxy: Any,
    profile: dict[str, Any],
) -> tuple[str | None, str | None, list[str]]:
    """Resolve exit IP, timezone, locale, and WebRTC anti-leak args for a profile launch.

    Returns (timezone, locale, extra_webrtc_args).

    Protections:
    1. If geoip is True (default), automatically probes the proxy's (or direct host's)
       actual exit IP and dynamically resolves timezone and locale via offline GeoIP.
       In this mode, dynamic detection always takes precedence, preventing timezone/IP
       mismatches when switching nodes or toggling proxies.
    2. If geoip is False (manual mode), honors user-specified timezone and locale.
    3. Spoofs WebRTC to the exit IP: --fingerprint-webrtc-ip=<exit_ip>.
    4. Forces WebRTC to never leak non-proxied UDP: --force-webrtc-ip-handling-policy=disable_non_proxied_udp.
    """
    from cloakbrowser.geoip import COUNTRY_LOCALE_MAP, _ensure_geoip_db

    extra_args: list[str] = []
    user_launch_args = profile.get("launch_args") or []
    is_auto_geo = bool(profile.get("geoip", True))
    timezone = profile.get("timezone") or None
    locale = profile.get("locale") or None
    exit_ip = None

    has_proxy = bool(proxy and proxy != "direct")

    if has_proxy:
        # Enforce strict WebRTC interface policy: prevent non-proxied UDP on local interfaces
        has_user_policy = any(a.startswith("--force-webrtc-ip-handling-policy") for a in user_launch_args)
        if not has_user_policy:
            extra_args.append("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")

    # Probe exit IP if auto geo is enabled, or if manual timezone/locale is missing
    need_probe = is_auto_geo or timezone is None or locale is None

    if need_probe:
        try:
            if not has_proxy:
                exit_ip, _, _ = _probe_proxy_target(None)
            elif isinstance(proxy, dict) and proxy.get("type") == "singbox":
                from backend.singbox_runner import fast_singbox_proxy

                with fast_singbox_proxy(proxy) as target_proxy_url:
                    exit_ip, _, _ = _probe_proxy_target(target_proxy_url)
            else:
                exit_ip, _, _ = _probe_proxy_target(proxy)

            if exit_ip:
                if has_proxy:
                    has_user_webrtc_ip = any(a.startswith("--fingerprint-webrtc-ip") for a in user_launch_args)
                    if not has_user_webrtc_ip:
                        extra_args.append(f"--fingerprint-webrtc-ip={exit_ip}")
                try:
                    from backend.geoip_resolver import resolve_ip_geo

                    geo = resolve_ip_geo(exit_ip)
                    detected_tz = geo.get("timezone")
                    detected_locale = geo.get("locale")

                    if is_auto_geo:
                        # In auto geo mode, dynamic exit IP detection always takes precedence!
                        if detected_tz:
                            timezone = detected_tz
                        if detected_locale:
                            locale = detected_locale
                    else:
                        # In manual mode, only fill in if user left it blank
                        if timezone is None and detected_tz:
                            timezone = detected_tz
                        if locale is None and detected_locale:
                            locale = detected_locale
                except Exception as geo_exc:
                    logger.warning("Failed to resolve GeoIP from exit IP %s: %s", exit_ip, geo_exc)
        except Exception as exc:
            logger.warning("Failed to pre-probe network fingerprint: %s", exc)

    return timezone, locale, extra_args


def _init_profile_defaults(user_data_dir: Path) -> None:
    """Set up bookmarks and DuckDuckGo search on first launch."""
    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)

    # --- Bookmarks (only on first launch) ---
    bookmarks_path = default_dir / "Bookmarks"
    if not bookmarks_path.exists():
        ts = str(int(time.time() * 1_000_000))  # Chrome timestamp format
        _id = 1

        def bm(name: str, url: str) -> dict:
            nonlocal _id
            _id += 1
            return {"type": "url", "id": str(_id), "name": name, "url": url, "date_added": ts}

        def folder(name: str, children: list) -> dict:
            nonlocal _id
            _id += 1
            return {"type": "folder", "id": str(_id), "name": name, "children": children, "date_added": ts, "date_modified": ts}

        bookmarks = {
            "checksum": "",
            "roots": {
                "bookmark_bar": {
                    "type": "folder", "id": "1", "name": "Bookmarks bar",
                    "date_added": ts, "date_modified": ts,
                    "children": [
                        folder("Detection Tests", [
                            bm("Rebrowser Bot Detector", "https://bot-detector.rebrowser.net/"),
                            bm("Incolumitas", "https://bot.incolumitas.com/"),
                            bm("SannySort", "https://bot.sannysoft.com/"),
                            bm("BrowserScan Bot", "https://www.browserscan.net/bot-detection"),
                            bm("FingerprintJS Demo", "https://demo.fingerprint.com/web-scraping"),
                            bm("Pixelscan", "https://pixelscan.net/fingerprint-check"),
                            bm("CreepJS", "https://abrahamjuliot.github.io/creepjs/"),
                            bm("fingerprint-scan", "https://fingerprint-scan.com/"),
                            bm("DeviceInfo Bot", "https://deviceandbrowserinfo.com/are_you_a_bot"),
                        ]),
                        folder("Fingerprint", [
                            bm("BrowserLeaks Canvas", "https://browserleaks.com/canvas"),
                            bm("BrowserLeaks WebGL", "https://browserleaks.com/webgl"),
                            bm("BrowserLeaks Fonts", "https://browserleaks.com/fonts"),
                            bm("BrowserLeaks JS", "https://browserleaks.com/javascript"),
                            bm("FingerprintJS OSS", "https://fingerprintjs.github.io/fingerprintjs/"),
                            bm("Audio FP", "https://audiofingerprint.openwpm.com/"),
                            bm("DeviceInfo", "https://deviceandbrowserinfo.com/info_device"),
                        ]),
                        folder("Headers & TLS", [
                            bm("httpbin headers", "https://httpbin.org/headers"),
                            bm("httpbin IP", "https://httpbin.org/ip"),
                            bm("TLS Fingerprint", "https://tls.browserleaks.com/"),
                        ]),
                        folder("reCAPTCHA", [
                            bm("Google v3 Demo", "https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php"),
                            bm("2captcha v3", "https://2captcha.com/demo/recaptcha-v3"),
                            bm("Turnstile", "https://peet.ws/turnstile-test/non-interactive.html"),
                        ]),
                    ],
                },
                "other": {"type": "folder", "id": "2", "name": "Other bookmarks", "children": []},
                "synced": {"type": "folder", "id": "3", "name": "Mobile bookmarks", "children": []},
            },
            "version": 1,
        }
        bookmarks_path.write_text(json.dumps(bookmarks, indent=2))
        logger.info("Created default bookmarks for %s", user_data_dir.name)

    # NOTE: the default search engine is NOT set here. The binary is built
    # de-Googled (prepopulated default is "No Search"), and writing
    # default_search_provider_data into Default/Preferences does NOT take — the
    # authoritative value lives in the MAC-protected Default/Secure Preferences,
    # rebuilt from the prepopulated set on every startup. Setting Google as the
    # default requires a live TemplateURLService commit, done once per profile in
    # BrowserManager._ensure_search_engine() (see that method).


CDP_START_ATTEMPTS = 3
CDP_READY_TIMEOUT = 10.0

# Periodic browser preview capture (shown in the edit view of a stopped profile).
# Captured every interval while running + once on stop; written to the profile's
# own user_data_dir so it's removed with the profile.
SCREENSHOT_FILENAME = "last_screenshot.jpg"
SCREENSHOT_INTERVAL = 30.0
SCREENSHOT_JPEG_QUALITY = 55

# One-time default-search-engine setup (see _ensure_search_engine).
SEARCH_ENGINE_MARKER = ".cloak_search_engine"
SEARCH_ENGINE_MAX_ATTEMPTS = 3
SEARCH_ENGINE_NAME = "Google"
SEARCH_ENGINE_KEYWORD = "google.com"
SEARCH_ENGINE_URL = "https://www.google.com/search?ie={inputEncoding}&q=%s"

# Read the live default search engine straight from the settings WebUI backend.
_ACTIVE_DEFAULT_JS = """async () => {
  const cr = await import('chrome://resources/js/cr.js');
  const l = await cr.sendWithPromise('getSearchEnginesList');
  const a = (l.defaults || []).find(e => e.default);
  return a ? {name: a.name, keyword: a.keyword} : null;
}"""

_HAS_GOOGLE_JS = """async () => {
  const cr = await import('chrome://resources/js/cr.js');
  const l = await cr.sendWithPromise('getSearchEnginesList');
  const all = [...(l.defaults || []), ...(l.others || []), ...(l.extensions || [])];
  return all.some(e => e.keyword === 'google.com' || (e.name && e.name.toLowerCase() === 'google'));
}"""

# Click the "Add" button that opens the add-search-engine dialog. We can't seed a
# search engine by writing files: a hand-written Web Data row carries an invalid
# url_hash (an HMAC we can't forge) and Chrome deletes it on load (strictly so on
# Windows). Only Chrome may create the row, so we drive the real Add dialog.
_CLICK_ADD_JS = """() => {
  let clicked = false;
  const walk = (root) => root.querySelectorAll('*').forEach(el => {
    if (el.shadowRoot) walk(el.shadowRoot);
    if (el.id === 'addSearchEngine' || (el.tagName === 'CR-BUTTON'
        && (/^Add$/i.test((el.textContent || '').trim()) || (el.textContent || '').trim() === '添加')
        && (/Add Site Search/i.test(el.getAttribute('aria-label') || '') || (el.getAttribute('aria-label') || '').includes('添加')))) {
      el.click(); clicked = true;
    }
  });
  walk(document);
  return clicked;
}"""
# Whether the dialog's Add action button is enabled (all fields validated).
_ADD_ENABLED_JS = """() => {
  let enabled = false;
  const walk = (root) => root.querySelectorAll('*').forEach(el => {
    if (el.shadowRoot) walk(el.shadowRoot);
    if ((el.id === 'actionButton' || (el.tagName === 'CR-BUTTON' && (/^Add$/i.test((el.textContent || '').trim()) || (el.textContent || '').trim() === '添加')))
        && el.closest('cr-dialog')) enabled = !el.disabled;
  });
  walk(document);
  return enabled;
}"""
# Click the (enabled) dialog Add button to commit the new engine.
_SUBMIT_ADD_JS = """() => {
  let clicked = false;
  const walk = (root) => root.querySelectorAll('*').forEach(el => {
    if (el.shadowRoot) walk(el.shadowRoot);
    if ((el.id === 'actionButton' || (el.tagName === 'CR-BUTTON' && (/^Add$/i.test((el.textContent || '').trim()) || (el.textContent || '').trim() === '添加')))
        && el.closest('cr-dialog') && !el.disabled) { el.click(); clicked = true; }
  });
  walk(document);
  return clicked;
}"""
# Open Google's "More actions" menu, then click "Make default". Exact label
# check matches Google without hitting "Google AI Mode".
_MAKE_GOOGLE_DEFAULT_JS = """() => {
  const walk = (root, fn) => root.querySelectorAll('*').forEach(el => {
    if (el.shadowRoot) walk(el.shadowRoot, fn);
    fn(el);
  });
  walk(document, el => {
    const label = ((el.getAttribute && el.getAttribute('aria-label')) || '').trim();
    if (el.tagName === 'CR-ICON-BUTTON' && label.includes('Google') && !label.includes('AI')) el.click();
  });
  return new Promise(resolve => setTimeout(() => {
    let clicked = false;
    walk(document, el => {
      const text = (el.textContent || '').trim();
      if ((el.id === 'makeDefault' || (el.tagName === 'BUTTON' && (/^Make default$/i.test(text) || text === '设为默认选项')))
          && !el.disabled) { el.click(); clicked = true; }
    });
    resolve(clicked);
  }, 400));
}"""


class ProfileBusyError(RuntimeError):
    """The profile's browser or on-disk state is in use by another operation."""


@dataclass
class RunningProfile:
    profile_id: str
    context: Any  # Playwright BrowserContext
    cdp_port: int
    display: int | None = None
    ws_port: int | None = None
    user_data_dir: Path | None = None
    screenshot_task: Any = None  # asyncio.Task for the periodic screenshot loop
    capture_preview: bool = True
    # Path to the wrapper's per-launch denial file (set by launch_persistent_
    # context_async on the returned context). Read on close to tell a seat/
    # license denial apart from a real crash or a user-initiated close.
    denial_path: str | None = None
    singbox_proc: Any = None
    kernel_version: str | None = None
    is_fallback: bool = False



class BrowserManager:
    def __init__(
        self,
        runtime_config: RuntimeConfig | None = None,
        license_key: str | None = None,
        release_channel: str | None = None,
        licenses: list[dict] | None = None,
    ):
        self.runtime = runtime_config or resolve_runtime()
        # App-wide default license (for backwards compatibility) and full licenses list.
        self.license_key = license_key
        self.licenses = licenses or []
        self.release_channel = release_channel
        # Resolved at startup by resolve_binary_status(); read by GET /api/status.
        self.license_tier = "keyless"
        self.license_plan: str | None = None
        self.binary_version: str | None = None
        self.binary_installed: bool = False
        self.running: dict[str, RunningProfile] = {}
        # Last launch failure per profile, surfaced on the status poll and cleared
        # on the next launch. Holds post-handshake denials (out of seats, bad key)
        # that land AFTER launch() already returned 200 — the browser boots, gets
        # denied ~1s later, and self-closes, so there's no HTTP response to carry
        # the reason. get_status() returns this so the frontend can show it.
        self._last_errors: dict[str, dict[str, str]] = {}
        self._launching: set[str] = set()  # profile IDs currently being launched
        # Reservations held while a context is closing (stop(), a self-exit, a
        # failed launch's cleanup). Counted per reservation so one operation's
        # cleanup can never release another's; see _reserve_stopping().
        self._stopping: dict[str, int] = {}
        # Profiles whose user_data_dir is reserved by a filesystem operation
        # (duplicate / reset / delete). launch() refuses these; see hold_stopped().
        self._held: set[str] = set()
        self._initializing: set[str] = set()  # profile IDs in one-time first-launch setup
        self.vnc = VNCManager(self.runtime.viewer_mode == "vnc")
        self._lock = asyncio.Lock()
        self._cdp_ports: set[int] = set()
        self._auto_launch_task: asyncio.Task | None = None

    def resolve_binary_status(self) -> None:
        """Resolve the license tier + binary version and check if the binary is installed.

        Non-blocking check — does NOT download the binary at startup so startup is instant
        and never blocks FastAPI or causes connection refused on port 8080.
        Users can download kernels on demand via the Kernel Manager.
        """
        from cloakbrowser.config import CHROMIUM_VERSION, get_chromium_version
        from cloakbrowser.license import (
            get_pro_latest_version,
            resolve_license_key,
            validate_license,
        )
        from .kernel_manager import is_binary_ready

        try:
            keyless_version = get_chromium_version()
        except Exception:
            keyless_version = CHROMIUM_VERSION

        tier = "keyless"
        version = keyless_version

        effective_key = self.license_key or next(
            (lic.get("key") for lic in self.licenses if lic.get("is_default") and lic.get("key")),
            None,
        ) or next(
            (lic.get("key") for lic in self.licenses if lic.get("key")),
            None,
        )
        if effective_key and not self.license_key:
            self.license_key = effective_key

        key = resolve_license_key(effective_key)
        if key:
            try:
                info = validate_license(key)
            except Exception as exc:
                info = None
                logger.warning("License validation failed: %s", exc)
            if info and info.valid:
                tier = "free" if info.plan == "free" else "pro"
                self.license_plan = info.plan
                try:
                    version = get_pro_latest_version(self.release_channel) or keyless_version
                except Exception as exc:
                    logger.warning("Could not resolve Pro version: %s", exc)
            elif key.strip().startswith("cb_") or len(key.strip()) >= 8:
                # If remote server validation was unreachable/failed (e.g. offline, proxy, transient error),
                # optimistically grant "pro" tier so user is not blocked from downloading the Pro kernel.
                # The kernel download stream itself enforces token authentication with the download server.
                tier = "pro"
                try:
                    version = get_pro_latest_version(self.release_channel) or keyless_version
                except Exception as exc:
                    logger.warning("Could not resolve Pro version: %s", exc)

        self.license_tier = tier
        self.binary_version = version
        self.binary_installed = self.is_binary_ready()
        if self.binary_installed:
            logger.info("Binary ready: tier=%s version=%s", tier, version)
        else:
            logger.info("No Chromium binary installed yet: tier=%s version=%s (can be downloaded via Kernel Manager)", tier, version)

    def is_binary_ready(self) -> bool:
        from .kernel_manager import is_binary_ready, list_available_kernels
        # 1. Check if the target/preferred binary is ready
        if is_binary_ready(version=self.binary_version, pro=(self.license_tier == "pro")):
            return True
        # 2. Check if ANY installed binary is ready on disk (fallback)
        data = list_available_kernels()
        return bool(data.get("installed", False))

    async def launch(self, profile: dict[str, Any]) -> RunningProfile:
        """Launch a browser instance using the configured host runtime."""
        browser_type = profile.get("browser_type") or "cloakbrowser"
        if browser_type == "camoufox":
            import camoufox.multiversion as cm
            import camoufox.pkgman as cp
            from .runtime import resolve_runtime

            _cam_data_dir = resolve_runtime().data_dir / "kernels" / "camoufox"
            cp.INSTALL_DIR = _cam_data_dir
            cm.BROWSERS_DIR = _cam_data_dir / "browsers"
            if not cm.list_installed():
                raise RuntimeError("Camoufox (Firefox) 内核未下载，请先点击顶部『内核管理』下载内核后再启动浏览器。")
        else:
            if not self.is_binary_ready():
                raise RuntimeError("CloakBrowser (Chromium) 内核未下载，请先点击顶部『内核管理』下载内核后再启动浏览器。")

        profile_id = profile["id"]

        # Per-launch context so any launch failure carries the inputs that
        # produced it. Proxy credentials are redacted; never log the key.
        from . import diagnostics

        logger.info(
            "Launching profile %s: seed=%s proxy=%s tier=%s plan=%s runtime=%s",
            profile_id,
            profile.get("fingerprint_seed"),
            diagnostics.redact_proxy(profile.get("proxy")),
            self.license_tier,
            self.license_plan or "-",
            self.runtime.runtime_mode,
        )

        async with self._lock:
            if profile_id in self._held:
                raise ProfileBusyError(
                    f"Profile {profile_id} is busy: its browser state is being copied or reset"
                )
            if profile_id in self._stopping:
                # The previous browser is still closing. Starting another Chrome
                # on the same directory now would fight it for the profile — and
                # in Docker mode the launch would even delete its Singleton lock.
                raise ProfileBusyError(f"Profile {profile_id} is still closing; retry shortly")
            if profile_id in self.running or profile_id in self._launching:
                raise RuntimeError(f"Profile {profile_id} is already running")
            self._launching.add(profile_id)
            # Fresh attempt — drop any stale denial from a previous launch so the
            # status poll doesn't keep showing an old "out of seats" message.
            self._last_errors.pop(profile_id, None)

        display: int | None = None
        ws_port: int | None = None
        cdp_port: int | None = None
        context: Any | None = None
        try:
            if self.runtime.viewer_mode == "vnc":
                display, ws_port = await self.vnc.allocate()

            from .database import user_data_dir_for

            browser_type = profile.get("browser_type") or "cloakbrowser"
            canonical_udd = Path(user_data_dir_for(profile["id"], browser_type))
            raw_udd = profile.get("user_data_dir")
            if not raw_udd:
                user_data_dir = canonical_udd
                profile["user_data_dir"] = str(canonical_udd)
            else:
                try:
                    p_udd = Path(raw_udd)
                    if not p_udd.exists() and not str(p_udd).startswith(str(self.runtime.data_dir)):
                        user_data_dir = canonical_udd
                        profile["user_data_dir"] = str(canonical_udd)
                    else:
                        user_data_dir = p_udd
                except Exception:
                    user_data_dir = canonical_udd
                    profile["user_data_dir"] = str(canonical_udd)

            # Docker can leave stale locks after an unclean container exit. Native
            # mode must let Chromium arbitrate profile ownership itself.
            if self.runtime.runtime_mode == "docker":
                for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                    (user_data_dir / lock_file).unlink(missing_ok=True)

            _init_profile_defaults(user_data_dir)

            extra_launch_args = profile.get("extra_launch_args") or {}
            if isinstance(extra_launch_args, dict) and browser_type in extra_launch_args:
                user_launch_args = extra_launch_args.get(browser_type) or []
            else:
                user_launch_args = profile.get("launch_args") or []
            conflicting_debug_args = [
                arg for arg in user_launch_args
                if arg.startswith(("--remote-debugging-port", "--remote-debugging-address"))
            ]
            if conflicting_debug_args:
                raise ValueError(
                    "Manager owns remote debugging configuration; remove: "
                    + ", ".join(conflicting_debug_args)
                )

            user_ignore_args = []
            normal_launch_args = []
            for arg in user_launch_args:
                arg_clean = arg.strip()
                if arg_clean.lower().startswith("ignore:"):
                    flag = arg_clean[7:].strip()
                    if flag:
                        user_ignore_args.append(flag)
                elif arg_clean.lower().startswith("ignore "):
                    flag = arg_clean[7:].strip()
                    if flag:
                        user_ignore_args.append(flag)
                else:
                    normal_launch_args.append(arg_clean)

            # 1. Resolve requested kernel version and apply Option A fallback if missing
            requested_kernel = profile.get("browser_version") or None
            effective_kernel = requested_kernel
            is_fallback = False

            if browser_type == "camoufox":
                import camoufox.pkgman as cp
                import camoufox.multiversion as cm
                from .runtime import resolve_runtime
                from .camoufox_downloader import scan_all_installed_camoufox_kernels

                _cam_data_dir = resolve_runtime().data_dir / "kernels" / "camoufox"
                cp.INSTALL_DIR = _cam_data_dir
                cm.BROWSERS_DIR = _cam_data_dir / "browsers"

                scanned_map = scan_all_installed_camoufox_kernels()
                installed_camoufox = []
                try:
                    installed_camoufox = cm.list_installed()
                except Exception:
                    pass

                if not scanned_map and not installed_camoufox:
                    raise RuntimeError("本地未安装任何 Camoufox 内核，请先前往『内核管理』下载 Camoufox 内核。")

                matched_binary = None
                matched_version = None
                if requested_kernel:
                    clean_req = requested_kernel.lstrip("vV").strip()
                    if clean_req in scanned_map:
                        matched_binary = scanned_map[clean_req]["binary_path"]
                        matched_version = scanned_map[clean_req].get("folder_name") or clean_req
                    else:
                        for inst in installed_camoufox:
                            v_obj = inst.version
                            full_str = getattr(v_obj, "full_string", f"{v_obj.version}-{v_obj.build}")
                            if clean_req in (str(v_obj.version), str(v_obj.build), full_str, inst.path.name) or clean_req.startswith(str(v_obj.version)):
                                matched_version = full_str
                                try:
                                    matched_binary = str(cp.launch_path(inst.path))
                                except Exception:
                                    pass
                                break

                if matched_binary:
                    effective_kernel = matched_binary
                elif matched_version:
                    effective_kernel = matched_version
                else:
                    active_item = None
                    for item in scanned_map.values():
                        if item.get("is_active"):
                            active_item = item
                            break
                    if not active_item and scanned_map:
                        active_item = next(iter(scanned_map.values()))

                    if active_item:
                        fallback_kernel = active_item["binary_path"]
                        fallback_name = active_item.get("folder_name") or active_item.get("version", "unknown")
                    elif installed_camoufox:
                        active_inst = next((inst for inst in installed_camoufox if inst.is_active), installed_camoufox[0])
                        v_obj = active_inst.version
                        fallback_name = getattr(v_obj, "full_string", f"{v_obj.version}-{v_obj.build}")
                        try:
                            fallback_kernel = str(cp.launch_path(active_inst.path))
                        except Exception:
                            fallback_kernel = fallback_name
                    else:
                        raise RuntimeError("本地未安装任何 Camoufox 内核，请先前往『内核管理』下载 Camoufox 内核。")

                    if requested_kernel:
                        logger.warning(
                            "Profile %s 绑定的 Camoufox 内核 %s 未在本地安装，已自动回退到系统可用内核 %s",
                            profile_id,
                            requested_kernel,
                            fallback_name,
                        )
                        is_fallback = True
                    effective_kernel = fallback_kernel
            else:
                if requested_kernel:
                    is_ready = False
                    for pro_candidate in (False, True):
                        bp = get_binary_path(requested_kernel, pro=pro_candidate)
                        if bp.exists() and _is_executable(bp):
                            is_ready = True
                            break

                    if not is_ready:
                        info = binary_info()
                        fallback_kernel = info.get("version")
                        logger.warning(
                            "Profile %s 绑定的内核 %s 未在本地安装，已自动回退到系统当前默认可用内核 %s",
                            profile_id,
                            requested_kernel,
                            fallback_kernel,
                        )
                        effective_kernel = fallback_kernel
                        is_fallback = True

            # 2. Launch arguments version compatibility validation
            for arg in normal_launch_args:
                if arg.startswith("--proxy-server=") and "@" in arg:
                    check_kernel = requested_kernel or effective_kernel
                    if check_kernel and any(check_kernel.startswith(f"{v}.") for v in ("144", "145", "146", "147")):
                        raise ValueError(
                            f"Chromium {check_kernel} 内核不支持在命令行参数中直接传递代理密码 ({arg})。"
                            "请在 Profile 的『网络代理』设置项中配置代理，系统将自动进行安全的代理鉴权。"
                        )

            # 3. Determine if the effective kernel is a Free/Keyless build or Pro build.
            # If it's a Free build (such as 145 or platform default free build), run with license_key = None.
            # This completely exempts the launch from Pro license validation, expiration, and seat concurrency limits!
            profile_license_key = None
            if profile.get("license_id"):
                lic = next((l for l in self.licenses if l.get("id") == profile.get("license_id")), None)
                if lic:
                    profile_license_key = lic.get("key")

            is_pro_binary = False
            if effective_kernel:
                bp_pro = get_binary_path(effective_kernel, pro=True)
                if bp_pro.exists() and _is_executable(bp_pro):
                    is_pro_binary = True
            elif profile_license_key:
                is_pro_binary = True

            effective_license_key = profile_license_key if is_pro_binary else None

            # One-time per profile (opt-out via set_google_default): make Google
            # the default search engine. Runs before the user-facing launch;
            # reports "initializing" via get_status while it works (one short
            # headless launch). Never fatal.
            if profile.get("browser_type") == "camoufox":
                await self._ensure_camoufox_search_engine(
                    profile_id,
                    user_data_dir,
                    profile,
                    browser_version=effective_kernel,
                )
            elif profile.get("set_google_default", True):
                await self._ensure_search_engine(
                    profile_id,
                    user_data_dir,
                    profile,
                    browser_version=effective_kernel,
                    license_key=effective_license_key,
                )

            if display is not None and ws_port is not None:
                await self.vnc.start_vnc(
                    display,
                    ws_port,
                    width=profile.get("screen_width", 1920),
                    height=profile.get("screen_height", 1080),
                )

            try:
                import cloakbrowser.config
                for ia in user_ignore_args:
                    if ia not in cloakbrowser.config.IGNORE_DEFAULT_ARGS:
                        cloakbrowser.config.IGNORE_DEFAULT_ARGS.append(ia)
                if profile.get("extension_paths"):
                    if "--disable-extensions" not in cloakbrowser.config.IGNORE_DEFAULT_ARGS:
                        cloakbrowser.config.IGNORE_DEFAULT_ARGS.append("--disable-extensions")
                # On native macOS/Windows, OS provides standard application sandbox;
                # suppressing launcher's forced --no-sandbox eliminates unsupported-flags infobar
                # and prevents initial CDP handshake stalls on unpatched kernels.
                if self.runtime.is_native and self.runtime.host_os in ("macos", "windows"):
                    has_explicit_no_sandbox = any(a.strip() == "--no-sandbox" for a in user_launch_args)
                    if not has_explicit_no_sandbox and "--no-sandbox" not in cloakbrowser.config.IGNORE_DEFAULT_ARGS:
                        cloakbrowser.config.IGNORE_DEFAULT_ARGS.append("--no-sandbox")
            except Exception:
                pass

            extra_args = self._build_fingerprint_args(profile)
            extra_args += normal_launch_args
            extra_args.append("--remote-debugging-address=127.0.0.1")
            # Reopen the tabs the user had open when the profile was last stopped.
            # Chrome's persistent session is saved on disk but only restored when told to.
            if profile.get("restore_session", True):
                extra_args.append("--restore-last-session")

            # Coherent platform version & GPU defaults for CloakBrowser on macOS/Windows
            if profile.get("browser_type") != "camoufox":
                if not any(a.startswith("--fingerprint-platform-version") for a in extra_args):
                    if self.runtime.host_os == "macos":
                        import platform as _py_plat
                        mac_ver = _py_plat.mac_ver()[0] or "15.7.0"
                        extra_args.append(f"--fingerprint-platform-version={mac_ver}")
                    else:
                        extra_args.append("--fingerprint-platform-version=10.0.0")

                if self.runtime.host_os == "macos":
                    if not any(a.startswith("--fingerprint-gpu-renderer") for a in extra_args):
                        extra_args.append("--fingerprint-gpu-renderer=ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)")
                    if not any(a.startswith("--fingerprint-gpu-vendor") for a in extra_args):
                        extra_args.append("--fingerprint-gpu-vendor=Google Inc. (Apple)")


            raw_proxy = profile.get("proxy") or None
            proxy = _normalize_proxy(raw_proxy, profile.get("proxy_type")) if raw_proxy else None

            if proxy:
                _validate_proxy(proxy)
            else:
                # Explicitly bypass OS system proxy for true direct connection
                if not any(a.startswith("--no-proxy-server") or a.startswith("--proxy-server") for a in extra_args):
                    extra_args.append("--no-proxy-server")

            # Resolve network fingerprint (WebRTC, Timezone, Locale) safely without leaking local IP
            resolved_tz, resolved_locale, net_args = await asyncio.to_thread(
                _resolve_profile_network_fingerprint_sync, proxy, profile
            )
            # Avoid --test-type: Chromium's platform_util (ShowItemInFolder, OpenItem)
            # deliberately suppresses Finder/Explorer interaction when --test-type is present.
            # Infobars are cleanly avoided via native sandbox preservation and --disable-infobars.

            extra_args.extend(net_args)
            if profile.get("user_agent"):
                extra_args.append(f"--user-agent={str(profile['user_agent']).strip()}")

            raw_ext_paths = profile.get("extension_paths") or []
            sanitized_ext_paths = []
            for ep in raw_ext_paths:
                if isinstance(ep, str) and not ep.startswith(str(self.runtime.data_dir)) and ("/extensions/" in ep or "\\extensions\\" in ep):
                    try:
                        ep_p = Path(ep)
                        if not ep_p.exists():
                            eng = ep_p.parent.name
                            eid = ep_p.name
                            if eng in ("firefox", "chromium"):
                                candidate = self.runtime.data_dir / "extensions" / eng / eid
                            else:
                                candidate = self.runtime.data_dir / "extensions" / eid
                            if candidate.exists():
                                sanitized_ext_paths.append(str(candidate))
                                continue
                    except Exception:
                        pass
                sanitized_ext_paths.append(ep)

            downloads_dir = _resolve_downloads_dir(self.runtime)
            launch_options: dict[str, Any] = {
                "user_data_dir": str(user_data_dir),
                "headless": False,
                "accept_downloads": "internal-browser-default",
                "proxy": proxy,
                "args": extra_args,
                "timezone": resolved_tz,
                "locale": resolved_locale,
                "humanize": bool(profile.get("humanize", False)),
                "human_preset": profile.get("human_preset", "default"),
                "geoip": False if proxy else bool(profile.get("geoip", False)),
                "color_scheme": profile.get("color_scheme") or None,
                "extension_paths": sanitized_ext_paths,
                "license_key": effective_license_key,
                "browser_version": effective_kernel,
                "release_channel": self.release_channel,
            }
            if display is not None:
                launch_options["viewport"] = {
                    "width": profile.get("screen_width", 1920),
                    "height": profile.get("screen_height", 1080) - 133,
                }
                launch_options["env"] = {**os.environ, "DISPLAY": f":{display}"}

            _singbox_proc = None
            _singbox_http_url = None
            effective_proxy = proxy
            if profile.get("browser_type") == "camoufox" and isinstance(proxy, str):
                from urllib.parse import urlparse
                parsed_p = urlparse(proxy)
                if parsed_p.scheme in ("socks5", "socks") and (parsed_p.username or parsed_p.password):
                    effective_proxy = {"type": "singbox", "config": proxy}

            if isinstance(effective_proxy, dict) and effective_proxy.get("type") == "singbox":
                try:
                    from backend.singbox.manager import handle_singbox_proxy
                    _singbox_proc, _local_url, _http_url = await asyncio.to_thread(handle_singbox_proxy, effective_proxy)
                    if _local_url:
                        launch_options["proxy"] = {"server": _local_url}
                        _singbox_http_url = _http_url
                except Exception as exc:
                    raise RuntimeError(f"Failed to start sing-box proxy: {exc}") from exc

            last_cdp_error: Exception | None = None
            try:
                if profile.get("browser_type") == "camoufox":
                    from playwright.async_api import async_playwright
                    from camoufox.async_api import AsyncNewBrowser
                    pw = await async_playwright().start()

                    # Camoufox is Firefox-based. Convert proxy to its expected dict format.
                    # Ensure username and password are clean and separated for Playwright Firefox.
                    cam_proxy = None
                    raw_cam_proxy = launch_options.get("proxy")
                    if isinstance(raw_cam_proxy, dict) and "server" in raw_cam_proxy:
                        cam_proxy = dict(raw_cam_proxy)
                    elif isinstance(raw_cam_proxy, str):
                        cam_proxy = {"server": raw_cam_proxy}

                    if cam_proxy and isinstance(cam_proxy.get("server"), str):
                        server_str = cam_proxy["server"]
                        if "@" in server_str:
                            from urllib.parse import urlparse, unquote
                            parsed_s = urlparse(server_str)
                            clean_srv = f"{parsed_s.scheme}://{parsed_s.hostname}"
                            if parsed_s.port:
                                clean_srv += f":{parsed_s.port}"
                            cam_proxy["server"] = clean_srv
                            if parsed_s.username and "username" not in cam_proxy:
                                cam_proxy["username"] = unquote(parsed_s.username)
                            if parsed_s.password and "password" not in cam_proxy:
                                cam_proxy["password"] = unquote(parsed_s.password)

                    # Determine target OS to match the host platform and maintain fingerprint coherence
                    target_os = "macos" if self.runtime.host_os == "macos" else ("linux" if self.runtime.host_os == "linux" else "windows")

                    # Timezone and locale: inject via camoufox's config/locale params,
                    # NOT via Chromium CLI flags.
                    cam_config: dict[str, Any] = {
                        # Disable font spacing perturbation to eliminate font/glyph corruption (乱码)
                        "fonts:spacing_seed": 0,
                    }
                    if resolved_tz:
                        cam_config["timezone"] = resolved_tz
                    if resolved_locale:
                        cam_config["locale:all"] = resolved_locale
                        loc_parts = resolved_locale.split("-")
                        cam_config["locale:language"] = loc_parts[0]
                        if len(loc_parts) > 1:
                            cam_config["locale:region"] = loc_parts[1]

                    # User-Agent coherence:
                    # When user explicitly configured a user_agent, respect it.
                    # Otherwise, generate Camoufox's authentic User-Agent matching the target OS and clean kernel version.
                    # Note: We cleanly extract the numeric release version to avoid path leaks, and use Camoufox identity
                    # which prevents bot detectors (e.g. fingerprint-scan.com) from triggering the hardcoded
                    # `indexOf('Firefox') !== -1` early-return that causes fonts: NA and +5 medium penalty.
                    if profile.get("user_agent"):
                        custom_ua = str(profile["user_agent"]).strip()
                        cam_config["navigator.userAgent"] = custom_ua
                        cam_config["headers.User-Agent"] = custom_ua
                        try:
                            from camoufox.fingerprints import _app_version_from_user_agent
                            derived_app_ver = _app_version_from_user_agent(custom_ua)
                            if derived_app_ver:
                                cam_config["navigator.appVersion"] = derived_app_ver
                        except Exception:
                            pass
                    else:
                        eff_str = str(effective_kernel or "")
                        # Robustly extract numeric semver from version or path (e.g. '152.0' from '/.../official/152.0')
                        v_match = re.search(r"(\d+(?:\.\d+)+)", eff_str)
                        if v_match:
                            eff_clean = v_match.group(1)
                            ff_major = eff_clean.split(".")[0]
                        else:
                            eff_clean = "152.0"
                            ff_major = "152"
                        if target_os == "macos":
                            platform_str = "Macintosh; Intel Mac OS X 10.15"
                        elif target_os == "windows":
                            platform_str = "Windows NT 10.0; Win64; x64"
                        else:
                            platform_str = "X11; Linux x86_64"
                        native_ua = f"Mozilla/5.0 ({platform_str}; rv:{ff_major}.0) Gecko/20100101 Camoufox/{eff_clean}"
                        cam_config["navigator.userAgent"] = native_ua
                        cam_config["headers.User-Agent"] = native_ua

                    # Hardware & WebGL & Privacy configurations
                    if profile.get("cpu_cores"):
                        cam_config["navigator.hardwareConcurrency"] = int(profile["cpu_cores"])

                    webgl_vendor = profile.get("webgl_vendor")
                    webgl_renderer = profile.get("webgl_renderer")
                    if not webgl_vendor and webgl_renderer:
                        r_lower = str(webgl_renderer).lower()
                        if any(k in r_lower for k in ("nvidia", "geforce", "rtx", "gtx")):
                            webgl_vendor = "NVIDIA Corporation"
                        elif any(k in r_lower for k in ("intel", "iris", "arc")):
                            webgl_vendor = "Intel Inc."
                        elif any(k in r_lower for k in ("amd", "radeon")):
                            webgl_vendor = "AMD"
                        elif any(k in r_lower for k in ("apple", "m1", "m2", "m3", "m4")):
                            webgl_vendor = "Apple"

                    if webgl_vendor:
                        cam_config["webGl:vendor"] = str(webgl_vendor)
                    if webgl_renderer:
                        cam_config["webGl:renderer"] = str(webgl_renderer)

                    # Deterministic seeds and noise control
                    seed = int(profile.get("fingerprint_seed") or 0)
                    if not profile.get("canvas_noise", False):
                        cam_config["canvas:seed"] = 0
                    elif seed:
                        cam_config["canvas:seed"] = seed

                    if profile.get("audio_noise", True) is False:
                        cam_config["audio:seed"] = 0
                    elif seed:
                        cam_config["audio:seed"] = seed

                    if profile.get("do_not_track", False):
                        cam_config["navigator.doNotTrack"] = "1"

                    # WebRTC IP spoofing matching the proxy exit IP
                    webrtc_ip = None
                    for arg in net_args:
                        if arg.startswith("--fingerprint-webrtc-ip="):
                            webrtc_ip = arg.split("=", 1)[1]
                            break
                    if webrtc_ip:
                        cam_config["webrtc:ipv4"] = webrtc_ip

                    # Screen & Window geometry coherence:
                    # Provide a fully consistent set of dimensions so Camoufox doesn't merge
                    # mismatched random secondary screen values (e.g. availWidth: 960 vs width: 1920).
                    # Window outer dimensions must strictly fit within the available screen area
                    # to prevent the fatal 'window.outerWidth > screen.availWidth' anomaly.
                    sw = profile.get("screen_width")
                    sh = profile.get("screen_height")
                    if sw and sh:
                        sw = int(sw)
                        sh = int(sh)
                        cam_config["screen.width"] = sw
                        cam_config["screen.height"] = sh
                        cam_config["screen.availWidth"] = sw
                        cam_config["screen.availLeft"] = 0
                        if target_os == "macos":
                            cam_config["screen.availTop"] = 25
                            cam_config["screen.availHeight"] = max(sh - 25, 500)
                            cam_config["screen.colorDepth"] = 30
                            cam_config["screen.pixelDepth"] = 30
                        elif target_os == "windows":
                            cam_config["screen.availTop"] = 0
                            cam_config["screen.availHeight"] = max(sh - 40, 500)
                            cam_config["screen.colorDepth"] = 24
                            cam_config["screen.pixelDepth"] = 24
                        else:
                            cam_config["screen.availTop"] = 0
                            cam_config["screen.availHeight"] = sh
                            cam_config["screen.colorDepth"] = 24
                            cam_config["screen.pixelDepth"] = 24

                        avail_w = cam_config["screen.availWidth"]
                        avail_h = cam_config["screen.availHeight"]
                        cam_config["window.outerWidth"] = min(avail_w, 1440 if avail_w >= 1440 else avail_w)
                        cam_config["window.outerHeight"] = min(avail_h, 920 if avail_h >= 920 else avail_h)
                        cam_config["window.screenX"] = 0
                        cam_config["window.screenY"] = cam_config["screen.availTop"]

                    # Media devices: guarantee mock devices to avoid empty device tell
                    cam_config.setdefault("mediaDevices:enabled", True)
                    cam_config.setdefault("mediaDevices:micros", 1)
                    cam_config.setdefault("mediaDevices:webcams", 1)
                    cam_config.setdefault("mediaDevices:speakers", 0)

                    camoufox_options: dict[str, Any] = {
                        "headless": launch_options.get("headless", False),
                        "persistent_context": True,
                        "user_data_dir": launch_options["user_data_dir"],
                        "accept_downloads": "internal-browser-default",
                        "enable_cache": True,
                        "os": target_os,
                        # Suppress the noisy "proxy without geoip" LeakWarning because
                        # we've already resolved timezone/locale via geoip ourselves.
                        "i_know_what_im_doing": True,
                    }
                    cf_os = {"macos": "mac", "windows": "win", "linux": "lin"}.get(target_os, "mac")
                    try:
                        from camoufox.utils import sample_webgl, sample_webgl_for_screen, merge_into
                        webgl_fp = None
                        if webgl_vendor and webgl_renderer:
                            try:
                                webgl_fp = sample_webgl(cf_os, str(webgl_vendor), str(webgl_renderer))
                                camoufox_options["webgl_config"] = (str(webgl_vendor), str(webgl_renderer))
                            except Exception:
                                webgl_fp = None
                        if webgl_fp is None:
                            webgl_fp = sample_webgl_for_screen(cf_os, sw or 1920, sh or 1080)

                        webgl_fp.pop("webGl2Enabled", None)
                        if webgl_vendor:
                            webgl_fp["webGl:vendor"] = str(webgl_vendor)
                        if webgl_renderer:
                            webgl_fp["webGl:renderer"] = str(webgl_renderer)

                        # Fix Camoufox mock bug: parameter 34047 (MAX_TEXTURE_MAX_ANISOTROPY_EXT) is None in database,
                        # causing contradiction with supported EXT_texture_filter_anisotropic extension
                        if "webGl:parameters" in webgl_fp and isinstance(webgl_fp["webGl:parameters"], dict):
                            webgl_fp["webGl:parameters"]["34047"] = 16
                        if "webGl2:parameters" in webgl_fp and isinstance(webgl_fp["webGl2:parameters"], dict):
                            webgl_fp["webGl2:parameters"]["34047"] = 16
                        merge_into(cam_config, webgl_fp)
                        if webgl_vendor and webgl_renderer:
                            camoufox_options["webgl_config"] = (str(webgl_vendor), str(webgl_renderer))
                    except Exception as exc:
                        logger.debug("Failed to pre-sample webgl config: %s", exc)

                    if effective_kernel:
                        # If effective_kernel is a file path, pass executable_path.
                        # If it is a version identifier (e.g. '152.0.4'), pass browser.
                        eff_str = str(effective_kernel)
                        if "/" in eff_str or "\\" in eff_str:
                            camoufox_options["executable_path"] = eff_str
                            # Fix Camoufox bug where explicitly passing executable_path on macOS
                            # causes it to look for properties.json beside the executable instead of in Resources
                            if target_os == "macos" and "Camoufox.app/Contents/MacOS" in eff_str:
                                macos_dir = Path(eff_str).parent
                                res_dir = macos_dir.parent / "Resources"
                                mac_prop = macos_dir / "properties.json"
                                res_prop = res_dir / "properties.json"
                                if res_prop.exists() and not mac_prop.exists():
                                    try:
                                        import shutil
                                        shutil.copy2(res_prop, mac_prop)
                                    except Exception as e:
                                        logger.warning("Failed to copy properties.json for Camoufox: %s", e)
                        else:
                            camoufox_options["browser"] = eff_str.lstrip("vV")
                    if cam_proxy is not None:
                        camoufox_options["proxy"] = cam_proxy
                    if cam_config:
                        camoufox_options["config"] = cam_config
                    if resolved_locale:
                        camoufox_options["locale"] = resolved_locale
                    if resolved_tz:
                        # timezone_id is Playwright's standard param that controls the actual
                        # JS timezone in the browser (Intl.DateTimeFormat, new Date(), etc.).
                        # config['timezone'] above sets the fingerprint; this makes it real.
                        camoufox_options["timezone_id"] = resolved_tz
                    if profile.get("extension_paths"):
                        camoufox_options["addons"] = launch_options["extension_paths"]
                    if display is not None:
                        camoufox_options["env"] = launch_options.get("env")
                        camoufox_options["virtual_display"] = f":{display}"

                    # Fonts: Only pass custom fonts if user explicitly configured custom fonts list.
                    # Otherwise, DO NOT set camoufox_options["fonts"], letting Camoufox automatically
                    # generate its rich, 200+ OS font subset (preventing Fonts: NA / 0 fonts detected).
                    from .camoufox_policies import get_camoufox_user_prefs
                    custom_fonts = profile.get("fonts") or profile.get("custom_fonts")
                    if isinstance(custom_fonts, list) and custom_fonts:
                        camoufox_options["fonts"] = custom_fonts

                    # User preferences for search engine, keyword search, cookies, fonts, and session restore
                    cam_user_prefs = get_camoufox_user_prefs(
                        profile,
                        target_os=target_os,
                        timezone=resolved_tz,
                        locale=resolved_locale,
                        downloads_dir=downloads_dir,
                    )
                    if cam_proxy and isinstance(cam_proxy.get("server"), str) and "socks" in cam_proxy["server"]:
                        cam_user_prefs["network.proxy.socks_remote_dns"] = True
                        cam_user_prefs["network.proxy.socks_version"] = 5

                    if webrtc_ip:
                        cam_user_prefs["network.dns.disableIPv6"] = True

                    if profile.get("do_not_track", False):
                        cam_user_prefs["privacy.donottrackheader.enabled"] = True
                        cam_user_prefs["privacy.donottrackheader.value"] = 1

                    if profile.get("restore_session", True):
                        cam_user_prefs["browser.startup.page"] = 3
                    else:
                        cam_user_prefs["browser.startup.page"] = 0
                        cam_user_prefs["browser.startup.homepage"] = "about:blank"

                    # Merge user-defined custom Firefox preferences (about:config)
                    custom_firefox_prefs = profile.get("firefox_user_prefs")
                    if isinstance(custom_firefox_prefs, dict):
                        cam_user_prefs.update(custom_firefox_prefs)

                    camoufox_options["firefox_user_prefs"] = cam_user_prefs

                    # Pass non-Chromium user-defined args to Camoufox (e.g. -mute-audio)
                    camoufox_args = [
                        arg for arg in user_launch_args
                        if not arg.startswith(("--remote-debugging", "--fingerprint", "ignore:"))
                    ]
                    if camoufox_args:
                        camoufox_options["args"] = camoufox_args

                    try:
                        context = await AsyncNewBrowser(pw, **camoufox_options)
                        context._playwright_instance = pw
                        cdp_port = 0

                        # In Camoufox, closing the last window/tab does not emit context.close.
                        # Listen to page close events and automatically close context when all pages are closed.
                        async def _check_camoufox_empty():
                            await asyncio.sleep(0.15)
                            active = [p for p in context.pages if not p.is_closed()]
                            if not active:
                                try:
                                    await context.close()
                                except Exception:
                                    pass

                        def _on_camoufox_page(p):
                            p.on("close", lambda *_: asyncio.create_task(_check_camoufox_empty()))

                        context.on("page", _on_camoufox_page)
                        for pg in context.pages:
                            _on_camoufox_page(pg)
                    except Exception as exc:
                        await pw.stop()
                        raise RuntimeError(f"Camoufox 启动失败: {exc}") from exc
                else:
                    _cleanup_stale_chromium_locks(user_data_dir)
                    _configure_chromium_download_prefs(user_data_dir, downloads_dir)
                    for attempt in range(1, CDP_START_ATTEMPTS + 1):
                        cdp_port = self._reserve_cdp_port()

                        launch_options["args"] = [
                            *extra_args,
                            f"--remote-debugging-port={cdp_port}",
                        ]
                        try:
                            context = await launch_persistent_context_async(**launch_options)
                            denial_path = getattr(context, "_cloak_denial_path", None)
                            lic = self._denial_error(denial_path)
                            if lic is not None:
                                raise lic
                            await self._wait_for_cdp(cdp_port, denial_path=denial_path)
                            break
                        except asyncio.CancelledError:
                            if context is not None:
                                await self._close_context(context, profile_id)
                            self._release_cdp_port(cdp_port)
                            context = None
                            cdp_port = None
                            raise
                        except Exception as exc:
                            last_cdp_error = exc
                            dp = getattr(context, "_cloak_denial_path", None) if context is not None else None
                            if context is not None:
                                await self._close_context(context, profile_id)
                            self._release_cdp_port(cdp_port)
                            context = None
                            cdp_port = None
                            if isinstance(exc, CloakBrowserLicenseError):
                                raise
                            lic = self._denial_error(dp)
                            if lic is not None:
                                raise lic from exc
                            logger.warning(
                                "Browser/CDP startup attempt %d/%d failed for %s: %s",
                                attempt,
                                CDP_START_ATTEMPTS,
                                profile_id,
                                exc,
                            )
                    else:
                        raise RuntimeError(
                            f"Unable to start verified CDP for profile {profile_id}"
                        ) from last_cdp_error

                if context is None or cdp_port is None:
                    raise RuntimeError(f"Browser startup did not complete for profile {profile_id}")
            except BaseException as exc:
                if _singbox_proc is not None:
                    _singbox_proc.terminate()

                # A TargetClosedError immediately upon launch usually indicates the browser process
                # exited cleanly but prematurely. When switching from a newer kernel (e.g. 151)
                # to an older kernel (e.g. 145), Chromium's profile downgrade protection kicks in
                # and aborts the startup. Surface a helpful error message instead of a generic one.
                if is_fallback is False:
                    err_str = str(exc) + (str(exc.__cause__) if exc.__cause__ else "")
                    if "Target page, context or browser has been closed" in err_str:
                        raise RuntimeError(
                            f"启动失败: 内核降级导致数据不兼容。该 Profile 曾由高版本内核启动，"
                            f"现无法被旧版内核 ({effective_kernel}) 加载。请切回高版本内核或新建环境。"
                        ) from exc

                raise

            if self.runtime.viewer_mode == "vnc":
                # Capture copied text so the Manager clipboard endpoint can read it.
                clipboard_init_js = """
                    window.__clipboardText = '';
                    document.addEventListener('copy', () => {
                        const sel = window.getSelection();
                        if (sel) window.__clipboardText = sel.toString();
                    });
                    document.addEventListener('keydown', (e) => {
                        if ((e.ctrlKey || e.metaKey) && e.key === 'c' && !e.altKey && !e.shiftKey) {
                            const sel = window.getSelection();
                            if (sel && sel.toString()) window.__clipboardText = sel.toString();
                        }
                    });
                """
                await context.add_init_script(clipboard_init_js)
                for page in context.pages:
                    try:
                        await page.evaluate(clipboard_init_js)
                    except Exception as exc:
                        logger.debug("Clipboard init failed on existing page: %s", exc)

            # Inject hardware & privacy overrides for generic unpatched Chromium profiles.
            # CloakBrowser natively implements these via C++ flags (--fingerprint-hardware-concurrency,
            # --fingerprint-device-memory, --fingerprint-gpu-renderer, etc.), so avoid detectable
            # JavaScript prototype monkey patching.
            if profile.get("browser_type") not in ("camoufox", "cloakbrowser"):
                init_overrides: list[str] = []
                native_getter_helper = """
                    const _makeNativeGetter = (val, name) => {
                        const fn = () => val;
                        Object.defineProperty(fn, 'name', { value: 'get ' + name, configurable: true });
                        fn.toString = () => 'function get ' + name + '() { [native code] }';
                        return fn;
                    };
                """
                has_getter_helper = False

                if profile.get("cpu_cores"):
                    if not has_getter_helper:
                        init_overrides.append(native_getter_helper)
                        has_getter_helper = True
                    cores = int(profile["cpu_cores"])
                    init_overrides.append(
                        f"Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', {{ get: _makeNativeGetter({cores}, 'hardwareConcurrency'), configurable: true, enumerable: true }});"
                    )
                if profile.get("memory_gb"):
                    if not has_getter_helper:
                        init_overrides.append(native_getter_helper)
                        has_getter_helper = True
                    mem = int(profile["memory_gb"])
                    init_overrides.append(
                        f"Object.defineProperty(Navigator.prototype, 'deviceMemory', {{ get: _makeNativeGetter({mem}, 'deviceMemory'), configurable: true, enumerable: true }});"
                    )
                if profile.get("do_not_track"):
                    if not has_getter_helper:
                        init_overrides.append(native_getter_helper)
                        has_getter_helper = True
                    init_overrides.append(
                        "Object.defineProperty(Navigator.prototype, 'doNotTrack', { get: _makeNativeGetter('1', 'doNotTrack'), configurable: true, enumerable: true });"
                    )
                if profile.get("user_agent"):
                    if not has_getter_helper:
                        init_overrides.append(native_getter_helper)
                        has_getter_helper = True
                    ua_val = json.dumps(str(profile["user_agent"]).strip())
                    init_overrides.append(
                        f"Object.defineProperty(Navigator.prototype, 'userAgent', {{ get: _makeNativeGetter({ua_val}, 'userAgent'), configurable: true, enumerable: true }});"
                    )
                wv = profile.get("webgl_vendor")
                wr = profile.get("webgl_renderer")
                if not wv and wr:
                    r_lower = str(wr).lower()
                    if any(k in r_lower for k in ("nvidia", "geforce", "rtx", "gtx")):
                        wv = "NVIDIA Corporation"
                    elif any(k in r_lower for k in ("intel", "iris", "arc")):
                        wv = "Intel Inc."
                    elif any(k in r_lower for k in ("amd", "radeon")):
                        wv = "AMD"
                    elif any(k in r_lower for k in ("apple", "m1", "m2", "m3", "m4")):
                        wv = "Apple"
                if wv or wr:
                    v = json.dumps(wv) if wv else "null"
                    r = json.dumps(wr) if wr else "null"
                    init_overrides.append(f"""
                        (() => {{
                            const v = {v};
                            const r = {r};
                            const patch = (proto) => {{
                                if (!proto || !proto.getParameter) return;
                                const orig = proto.getParameter;
                                const patched = function getParameter(param) {{
                                    if (v && param === 37445) return v;
                                    if (r && param === 37446) return r;
                                    if (param === 34047) {{
                                        const res = orig.apply(this, arguments);
                                        return (res !== null && res !== undefined) ? res : 16;
                                    }}
                                    return orig.apply(this, arguments);
                                }};
                                Object.defineProperty(patched, 'name', {{ value: 'getParameter', configurable: true }});
                                patched.toString = () => 'function getParameter() {{ [native code] }}';
                                proto.getParameter = patched;
                            }};
                            if (typeof WebGLRenderingContext !== 'undefined') patch(WebGLRenderingContext.prototype);
                            if (typeof WebGL2RenderingContext !== 'undefined') patch(WebGL2RenderingContext.prototype);
                        }})();
                    """)
                if init_overrides:
                    try:
                        override_js = ";\n".join(init_overrides)
                        await context.add_init_script(override_js)
                        for page in context.pages:
                            try:
                                await page.evaluate(override_js)
                            except Exception:
                                pass
                    except Exception as exc:
                        logger.warning("Failed to inject hardware/privacy init script for profile %s: %s", profile_id, exc)

            running = RunningProfile(
                profile_id=profile_id,
                context=context,
                cdp_port=cdp_port,
                display=display,
                ws_port=ws_port,
                user_data_dir=user_data_dir,
                capture_preview=bool(profile.get("capture_preview", True)),
                denial_path=getattr(context, "_cloak_denial_path", None),
                singbox_proc=_singbox_proc,
                kernel_version=effective_kernel,
                is_fallback=is_fallback,
            )
            context.on(
                "close",
                lambda *_: asyncio.ensure_future(self._on_browser_closed(running)),
            )

            async with self._lock:
                self.running[profile_id] = running
                self._launching.discard(profile_id)

            # Periodically snapshot the page so the edit view (and the native
            # running view) can show the last frame. Runs even when the browser
            # is closed from inside VNC, where an on-close capture is impossible.
            # Per-profile opt-out via capture_preview.
            if running.capture_preview:
                running.screenshot_task = asyncio.ensure_future(
                    self._screenshot_loop(profile_id)
                )

            logger.info(
                "Launched profile %s (runtime=%s, display=%s, ws_port=%s, cdp_port=%d)",
                profile_id,
                self.runtime.runtime_mode,
                f":{display}" if display is not None else "native",
                ws_port,
                cdp_port,
            )
            return running

        except BaseException:
            # Stay "active" until the half-launched browser is really gone: swap
            # _launching for _stopping under the lock so is_active() never sees a
            # gap while a context may still be open, then clear it after cleanup.
            async with self._lock:
                self._launching.discard(profile_id)
                self._reserve_stopping(profile_id)
            try:
                if context is not None:
                    await self._close_context(context, profile_id)
                if cdp_port is not None:
                    self._release_cdp_port(cdp_port)
                if display is not None:
                    await self.vnc.stop_vnc(display)
            finally:
                self._release_stopping(profile_id)
            raise

    async def _ensure_search_engine(
        self,
        profile_id: str,
        user_data_dir: Path,
        profile: dict[str, Any] | None = None,
        browser_version: str | None = None,
        license_key: str | None = None,
    ) -> None:
        """Make configured search engine (default Google) the default search engine, once per profile.

        Marker-gated so it runs only on a profile's first launch. Reports
        "initializing" via get_status while it works. Never fatal: on failure the
        profile still launches (with the binary's de-Googled "No Search" default).
        """
        name = (profile and profile.get("search_engine_name")) or SEARCH_ENGINE_NAME
        keyword = (profile and profile.get("search_engine_keyword")) or SEARCH_ENGINE_KEYWORD
        url = (profile and profile.get("search_engine_url")) or SEARCH_ENGINE_URL

        marker = user_data_dir / SEARCH_ENGINE_MARKER
        state = marker.read_text().strip() if marker.exists() else ""
        if state == keyword or (state == "google" and keyword == SEARCH_ENGINE_KEYWORD):
            return
        attempts = 0
        if state.startswith("failed:"):
            try:
                attempts = int(state.split(":", 1)[1])
            except ValueError:
                attempts = 0
            if attempts >= SEARCH_ENGINE_MAX_ATTEMPTS:
                return  # gave up earlier — stop burning launches on every start

        self._initializing.add(profile_id)
        try:
            _cleanup_stale_chromium_locks(user_data_dir)
            await self._setup_google_default(
                user_data_dir,
                name=name,
                keyword=keyword,
                url=url,
                browser_version=browser_version,
                license_key=license_key,
            )
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(f"{keyword}\n")
            logger.info(
                "Set %s as default search engine for %s", name, user_data_dir.name
            )
        except CloakBrowserLicenseError:
            # A license denial (out of seats, bad key, …) isn't a search-engine
            # failure — don't burn a retry on the marker; abort the launch so the
            # API surfaces the real reason.
            raise
        except Exception as exc:
            attempts += 1
            try:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(f"failed:{attempts}\n")
            except OSError:
                pass
            log = logger.error if attempts >= SEARCH_ENGINE_MAX_ATTEMPTS else logger.warning
            log(
                "Default-search-engine setup failed for %s (attempt %d/%d, launching anyway): %s",
                user_data_dir.name,
                attempts,
                SEARCH_ENGINE_MAX_ATTEMPTS,
                exc,
            )
        finally:
            self._initializing.discard(profile_id)

    async def _setup_google_default(
        self,
        user_data_dir: Path,
        name: str = SEARCH_ENGINE_NAME,
        keyword: str = SEARCH_ENGINE_KEYWORD,
        url: str = SEARCH_ENGINE_URL,
        browser_version: str | None = None,
        license_key: str | None = None,
    ) -> None:
        """Add search engine via the settings UI, then commit it as the default.

        Single headless launch, no file seeding. A plain Preferences write can't
        set the default (the authoritative value is MAC-protected in Secure
        Preferences, rebuilt from the prepopulated set every startup), and a
        hand-written Web Data keyword row is deleted on load for its invalid,
        un-forgeable url_hash (strictly so on Windows). So we drive the real Add
        dialog — Chrome creates the row with a valid hash — then "Make default".
        Every later launch then carries the engine via the profile's own files.
        """
        ctx = await self._headless_launch(
            user_data_dir,
            browser_version=browser_version,
            license_key=license_key,
        )
        try:
            page = await ctx.new_page()
            await page.goto("chrome://settings/searchEngines")
            await asyncio.sleep(2)

            # Check if keyword is already active default
            active = await page.evaluate(_ACTIVE_DEFAULT_JS)
            if active and active.get("keyword") == keyword:
                await page.close()
                return

            has_engine = await page.evaluate(f"""async () => {{
                const cr = await import('chrome://resources/js/cr.js');
                const l = await cr.sendWithPromise('getSearchEnginesList');
                const all = [...(l.defaults || []), ...(l.others || []), ...(l.extensions || [])];
                return all.some(e => e.keyword === '{keyword}' || (e.name && e.name.toLowerCase() === '{name.lower()}'));
            }}""")

            if not has_engine:
                if not await page.evaluate(_CLICK_ADD_JS):
                    raise RuntimeError("could not open the Add search engine dialog")
                await asyncio.sleep(1.2)

                # Real .fill() emits trusted events so the dialog's async field
                # validation runs and enables the Add button; a synthetic value-set
                # does not. Playwright pierces the cr-input's open shadow root.
                name_input = page.locator('cr-input#searchEngine input, cr-input[label="Name"] input, cr-input[label*="名称"] input').first
                shortcut_input = page.locator('cr-input#keyword input, cr-input[label="Shortcut"] input, cr-input[label*="快捷"] input').first
                url_input = page.locator('cr-input#queryUrl input, cr-input[label^="URL"] input, cr-input[label*="网址"] input').first

                await name_input.fill(name)
                await shortcut_input.fill(keyword)
                await url_input.fill(url)

                enabled = False
                for _ in range(12):
                    await asyncio.sleep(0.25)
                    if await page.evaluate(_ADD_ENABLED_JS):
                        enabled = True
                        break
                if not enabled:
                    raise RuntimeError("Add dialog stayed disabled after fill")

                if not await page.evaluate(_SUBMIT_ADD_JS):
                    raise RuntimeError("could not submit the Add dialog")
                await asyncio.sleep(1.2)

            make_default_js = f"""() => {{
              const walk = (root, fn) => root.querySelectorAll('*').forEach(el => {{
                if (el.shadowRoot) walk(el.shadowRoot, fn);
                fn(el);
              }});
              walk(document, el => {{
                if (el.tagName === 'CR-ICON-BUTTON') {{
                  const label = ((el.getAttribute && el.getAttribute('aria-label')) || '').trim();
                  let row = el;
                  while (row && row.tagName !== 'SETTINGS-SEARCH-ENGINE-ENTRY' && row.tagName !== 'TR') {{
                    row = row.parentNode || row.host;
                  }}
                  const text = row ? (row.textContent || '') : label;
                  if ((text.includes('{name}') || text.includes('{keyword}') || label.includes('{name}') || label.includes('{keyword}')) && !label.includes('AI')) {{
                    el.click();
                  }}
                }}
              }});
              return new Promise(resolve => setTimeout(() => {{
                let clicked = false;
                walk(document, el => {{
                  const text = (el.textContent || '').trim();
                  if ((el.id === 'makeDefault' || (el.tagName === 'BUTTON' && (/^Make default$/i.test(text) || text === '设为默认选项' || text.includes('默认'))))
                      && !el.disabled) {{ el.click(); clicked = true; }}
                }});
                resolve(clicked);
              }}, 400));
            }}"""
            clicked = await page.evaluate(make_default_js)
            await asyncio.sleep(1)
            active = await page.evaluate(_ACTIVE_DEFAULT_JS)
            if not (active and active.get("keyword") == keyword):
                raise RuntimeError(
                    f"make-default did not take (clicked={clicked}, active={active})"
                )
            # Close the page before closing context to avoid saving chrome://settings/searchEngines into session
            await page.close()
        finally:
            await self._close_context(ctx, "search-init")
        await asyncio.sleep(0.5)

        # Clean up any session files created during headless search-engine setup
        # so the user's real browser launch starts with a clean new tab, NOT the settings page
        sessions_dir = user_data_dir / "Default" / "Sessions"
        if sessions_dir.exists():
            shutil.rmtree(sessions_dir, ignore_errors=True)

    async def _ensure_camoufox_search_engine(
        self,
        profile_id: str,
        user_data_dir: Path,
        profile: dict[str, Any],
        browser_version: str | None = None,
    ) -> None:
        """Sanitize policies.json and profile search engine state for Camoufox."""
        def _sync_setup():
            from .camoufox_policies import (
                resolve_camoufox_distribution_dir,
                sanitize_camoufox_policies,
                sanitize_camoufox_profile_search_cache,
            )
            try:
                from camoufox.pkgman import launch_path
                cam_exe = None
                if browser_version:
                    try:
                        from camoufox.multiversion import find_installed_version
                        found_ver = find_installed_version(browser_version.lstrip("vV"))
                        if found_ver:
                            cam_exe = Path(launch_path(found_ver))
                    except Exception:
                        pass
                if not cam_exe:
                    cam_exe = Path(launch_path())

                dist_dir = resolve_camoufox_distribution_dir(cam_exe)
                engine_name = profile.get("search_engine_name") or SEARCH_ENGINE_NAME
                engine_url = profile.get("search_engine_url")
                sanitize_camoufox_policies(dist_dir, engine_name, engine_url)
                sanitize_camoufox_profile_search_cache(user_data_dir, engine_name)
            except Exception as exc:
                logger.warning(
                    "Camoufox search engine / policy setup warning for %s: %s",
                    profile_id,
                    exc,
                )

        await asyncio.to_thread(_sync_setup)

    async def _headless_launch(
        self,
        user_data_dir: Path,
        browser_version: str | None = None,
        license_key: str | None = None,
    ) -> Any:
        """Short headless launch used only by the one-time search-engine setup."""
        for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            (user_data_dir / lock_file).unlink(missing_ok=True)
        return await launch_persistent_context_async(
            user_data_dir=str(user_data_dir),
            headless=True,
            browser_version=browser_version,
            license_key=license_key,
            release_channel=self.release_channel,
        )

    async def _capture_screenshot(self, running: RunningProfile) -> None:
        """Write a compressed JPEG of the profile's current page to disk.

        Best-effort: a live page and user_data_dir are required. Written to a
        temp file then atomically renamed so the endpoint never serves a
        half-written image. Callers wrap this; it may raise on a dead/navigating
        page.
        """
        if running.user_data_dir is None:
            return
        pages = list(running.context.pages)
        if not pages:
            return
        page = pages[-1]  # most recently opened tab ≈ what the user is viewing
        dest = running.user_data_dir / SCREENSHOT_FILENAME
        tmp = running.user_data_dir / (SCREENSHOT_FILENAME + ".tmp")
        await page.screenshot(
            path=str(tmp), type="jpeg", quality=SCREENSHOT_JPEG_QUALITY
        )
        os.replace(tmp, dest)

    async def _screenshot_loop(self, profile_id: str) -> None:
        """Capture a preview every SCREENSHOT_INTERVAL while the profile runs."""
        try:
            while self.running.get(profile_id) is not None:
                await asyncio.sleep(SCREENSHOT_INTERVAL)
                running = self.running.get(profile_id)
                if running is None:
                    break
                try:
                    await self._capture_screenshot(running)
                except Exception as exc:
                    logger.debug(
                        "Preview screenshot failed for %s: %s", profile_id, exc
                    )
        except asyncio.CancelledError:
            pass

    async def _close_context(self, context: Any, profile_id: str) -> None:
        try:
            await context.close()
            pw = getattr(context, "_playwright_instance", None)
            if pw:
                await pw.stop()
        except Exception as exc:
            logger.warning("Error closing context for %s: %s", profile_id, exc)

    async def _dispose_running(
        self,
        running: RunningProfile,
        *,
        close_context: bool,
    ) -> None:
        if running.screenshot_task is not None:
            running.screenshot_task.cancel()

        # Stop sing-box proxy immediately so proxy ports and processes are released reliably
        if running.singbox_proc is not None:
            try:
                running.singbox_proc.terminate()
            except Exception as exc:
                logger.warning("Error terminating singbox for %s: %s", running.profile_id, exc)

        if close_context:
            await self._close_context(running.context, running.profile_id)

        if running.display is not None:
            try:
                await self.vnc.stop_vnc(running.display)
            except Exception as exc:
                logger.warning("Error stopping VNC for %s: %s", running.profile_id, exc)

        self._release_cdp_port(running.cdp_port)

    async def _on_browser_closed(self, running: RunningProfile):
        """Release resources after a browser crash or user-initiated close.

        A post-handshake license denial (out of seats, bad/expired key) lands
        HERE, not at launch: the browser boots, launch() returns 200, then the
        binary self-exits ~1s later. It leaves the reason in a denial file the
        wrapper minted; read it so the status poll can tell the user why the
        profile just vanished instead of silently flipping back to stopped.

        Takes the specific RunningProfile (not just its id): a late close event
        from a superseded launch must not pop/dispose a healthy relaunch that now
        owns the same profile_id, nor stamp a stale denial onto it.
        """
        profile_id = running.profile_id
        async with self._lock:
            if self.running.get(profile_id) is not running:
                return  # superseded — a newer launch owns this profile now
            # Record the denial and pop under the SAME lock so it can't race with
            # a concurrent launch() clearing _last_errors at its start.
            self._record_denial_if_any(profile_id, running.denial_path)
            self.running.pop(profile_id, None)
            # Same contract as stop(): active until the dispose is really done.
            self._reserve_stopping(profile_id)

        logger.info("Browser closed for profile %s, cleaning up", profile_id)
        try:
            await self._dispose_running(running, close_context=True)
        finally:
            self._release_stopping(profile_id)

    def _denial_error(self, denial_path: str | None) -> CloakBrowserLicenseError | None:
        """Read the wrapper's denial file → a license error, or None.

        Destructive read (consumes the file) but cached in-process, so it's safe
        even if the wrapper's guard already consumed it. Non-license closes (real
        crash, user closed the tab) leave no file → None.
        """
        if not denial_path:
            return None
        try:
            code = read_denial_file(denial_path)
        except Exception as exc:  # never let cleanup fail on a read error
            logger.debug("Denial-file read failed: %s", exc)
            return None
        return license_error_for_code(code) if code is not None else None

    def _record_denial_if_any(self, profile_id: str, denial_path: str | None) -> None:
        """If the close was a license denial, stash it for the status poll."""
        lic = self._denial_error(denial_path)
        if lic is None:
            return
        self._last_errors[profile_id] = license_error_detail(lic)
        logger.warning("Profile %s closed on a license denial: %s", profile_id, lic)

    async def stop(self, profile_id: str):
        """Stop a running browser instance and release all owned resources."""
        # Pop before close so the close event observes an already-clean state.
        # _stopping keeps the profile "active" for is_active() until the context
        # is really closed: Chrome is still flushing its profile dir in between.
        async with self._lock:
            running = self.running.pop(profile_id, None)
            if running:
                self._reserve_stopping(profile_id)

        if not running:
            return

        logger.info("Stopping profile %s", profile_id)
        try:
            # Final preview capture while the context is still alive (the on-close
            # path can't screenshot — the browser is already gone by then).
            if running.capture_preview:
                try:
                    await self._capture_screenshot(running)
                except Exception as exc:
                    logger.debug(
                        "Final preview screenshot failed for %s: %s", profile_id, exc
                    )
            await self._dispose_running(running, close_context=True)
        finally:
            self._release_stopping(profile_id)

    def _reserve_stopping(self, profile_id: str) -> None:
        """Mark a context-close in progress for the profile (counted)."""
        self._stopping[profile_id] = self._stopping.get(profile_id, 0) + 1

    def _release_stopping(self, profile_id: str) -> None:
        """Release ONE close reservation; the profile stays active while others remain."""
        left = self._stopping.get(profile_id, 0) - 1
        if left > 0:
            self._stopping[profile_id] = left
        else:
            self._stopping.pop(profile_id, None)

    def is_active(self, profile_id: str) -> bool:
        """True while a browser owns the profile dir: launching, running or still
        closing. ``running`` alone is not enough — launch() registers there only
        at the very end, and stop() pops it before the context is closed."""
        return (
            profile_id in self.running
            or profile_id in self._launching
            or profile_id in self._stopping
        )

    @asynccontextmanager
    async def hold_stopped(self, profile_id: str):
        """Exclusive access to a stopped profile's on-disk state for the block.

        Refuses with ProfileBusyError if a browser is launching, running or
        closing for the profile, or another hold is active. While held, launch()
        refuses the profile. Every operation that reads or rewrites a
        user_data_dir (duplicate, reset, delete) takes this, so a launch and a
        filesystem operation can never interleave on the same directory.
        """
        async with self._lock:
            if self.is_active(profile_id):
                raise ProfileBusyError(f"Profile {profile_id} is running or changing state")
            if profile_id in self._held:
                raise ProfileBusyError(
                    f"Profile {profile_id} is busy: its browser state is being copied or reset"
                )
            self._held.add(profile_id)
        try:
            yield
        finally:
            self._held.discard(profile_id)

    def get_status(self, profile_id: str) -> dict[str, Any]:
        """Get running status and viewer capabilities for a profile."""
        running = self.running.get(profile_id)
        if running:
            state = "running"
        elif profile_id in self._initializing:
            state = "initializing"
        else:
            state = "stopped"
        status = {
            "status": state,
            "runtime_mode": self.runtime.runtime_mode,
            "viewer_mode": self.runtime.viewer_mode,
            "vnc_ws_port": running.ws_port if running else None,
            "display": (
                f":{running.display}"
                if running and running.display is not None
                else None
            ),
            "cdp_url": (
                f"/api/profiles/{profile_id}/cdp"
                if (running and getattr(running, "cdp_port", 0) > 0)
                else None
            ),
            # Set when the last launch closed on a license denial (post-handshake
            # out-of-seats / bad key). Only meaningful while stopped; cleared on
            # the next launch. {message, reason, upgrade_url?} or None.
            "last_error": None if running else self._last_errors.get(profile_id),
        }
        return status

    async def cleanup_all(self):
        """Stop all running profiles. Called on shutdown."""
        async with self._lock:
            profile_ids = list(self.running.keys())

        for pid in profile_ids:
            await self.stop(pid)

        if self.runtime.viewer_mode == "vnc":
            await self.vnc.cleanup_all()

        try:
            from backend.singbox.process import cleanup_stale_singbox
            cleanup_stale_singbox()
        except Exception as exc:
            logger.debug("Failed cleaning up singbox on shutdown: %s", exc)

    async def cleanup_stale(self):
        """Kill orphan display and proxy processes from previous runs."""
        if self.runtime.viewer_mode == "vnc":
            await self.vnc.cleanup_stale()

        try:
            from backend.singbox.process import cleanup_stale_singbox
            cleanup_stale_singbox()
        except Exception as exc:
            logger.debug("Failed cleaning up stale singbox processes on startup: %s", exc)

    async def auto_launch_all(self):
        """Launch all profiles with auto_launch=True. Called on startup."""
        if not self.is_binary_ready():
            logger.info("Skipping auto-launch: Chromium binary is not installed yet.")
            return

        from . import database as db

        profiles = db.list_profiles()
        auto_profiles = [p for p in profiles if p.get("auto_launch")]
        if not auto_profiles:
            logger.info("No profiles configured for auto-launch")
            return

        logger.info("Auto-launching %d profile(s)...", len(auto_profiles))
        for profile in auto_profiles:
            try:
                await asyncio.wait_for(self.launch(profile), timeout=60)
                logger.info("Auto-launched profile %s (%s)", profile["name"], profile["id"])
            except Exception as exc:
                logger.error(
                    "Auto-launch failed for profile %s (%s): %s",
                    profile["name"], profile["id"], exc,
                )
        logger.info("Auto-launch complete: %d running", len(self.running))

    def _reserve_cdp_port(self) -> int:
        """Reserve an OS-selected loopback port for one managed browser."""
        for _ in range(20):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                port = int(sock.getsockname()[1])
            if port not in self._cdp_ports:
                self._cdp_ports.add(port)
                return port
        raise RuntimeError("Unable to reserve a unique CDP port")

    def _release_cdp_port(self, port: int) -> None:
        self._cdp_ports.discard(port)

    @staticmethod
    async def _fetch_cdp_version(port: int) -> dict[str, Any]:
        def fetch() -> dict[str, Any]:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version",
                timeout=1,
            ) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise RuntimeError("CDP version response is not an object")
            return payload

        return await asyncio.to_thread(fetch)

    async def _wait_for_cdp(
        self,
        port: int,
        timeout: float = CDP_READY_TIMEOUT,
        denial_path: str | None = None,
    ) -> None:
        """Wait for and verify Chromium's debugger endpoint on the reserved port.

        If ``denial_path`` is given, the wrapper's denial file is checked each
        poll: a seat/license denial makes the browser never serve CDP, so bail
        immediately with the real reason instead of waiting out ``timeout``.
        """
        deadline = asyncio.get_running_loop().time() + timeout
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            lic = self._denial_error(denial_path)
            if lic is not None:
                raise lic
            try:
                version = await self._fetch_cdp_version(port)
                websocket_url = str(version.get("webSocketDebuggerUrl") or "")
                if f":{port}/" not in websocket_url:
                    raise RuntimeError(
                        f"CDP endpoint returned an unexpected debugger URL: {websocket_url!r}"
                    )
                await self._reset_cdp_download_behavior(port)
                return
            except CloakBrowserLicenseError:
                raise
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.1)
        # One last check — the denial may have landed on the final poll.
        lic = self._denial_error(denial_path)
        if lic is not None:
            raise lic
        raise TimeoutError(f"CDP endpoint on 127.0.0.1:{port} was not ready") from last_error

    async def _reset_cdp_download_behavior(self, port: int, download_dir: Path | None = None) -> None:
        """Reset Chromium CDP download behavior to default native behavior without DevTools event hijacking."""
        dl_path = str(download_dir or _resolve_downloads_dir(self.runtime))
        try:
            import websockets
            version = await self._fetch_cdp_version(port)
            ws_url = str(version.get("webSocketDebuggerUrl") or "")
            if not ws_url:
                return
            async with websockets.connect(ws_url, close_timeout=1.5) as ws:
                await ws.send(json.dumps({
                    "id": 9991,
                    "method": "Browser.setDownloadBehavior",
                    "params": {
                        "behavior": "default",
                        "downloadPath": dl_path,
                        "eventsEnabled": False,
                    },
                }))
                try:
                    await asyncio.wait_for(ws.recv(), timeout=1.5)
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("Failed to set CDP download behavior for port %d: %s", port, exc)

    def _attach_download_handler(self, context: Any, download_dir: Path | None = None) -> None:
        """Listen for download events on context/pages and guarantee files are persisted to Downloads."""
        target_dir = download_dir or _resolve_downloads_dir(self.runtime)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        async def _handle_download(download: Any) -> None:
            try:
                filename = getattr(download, "suggested_filename", None) or "download"
                target = target_dir / filename
                if target.exists() and target.stat().st_size > 0:
                    logger.info("File %s already exists with size %d; skipping duplicate save", target, target.stat().st_size)
                    return
                if target.exists():
                    stem = target.stem
                    suffix = target.suffix
                    c = 1
                    while (target_dir / f"{stem} ({c}){suffix}").exists():
                        c += 1
                    target = target_dir / f"{stem} ({c}){suffix}"
                await download.save_as(str(target))
                logger.info("Saved downloaded file %s to %s", filename, target)
            except Exception as exc:
                logger.debug("Download save handler completed or skipped: %s", exc)

        try:
            context.on("page", lambda p: p.on("download", lambda dl: asyncio.ensure_future(_handle_download(dl))))
            for p in getattr(context, "pages", []):
                p.on("download", lambda dl: asyncio.ensure_future(_handle_download(dl)))
        except Exception as exc:
            logger.debug("Failed to attach download listener to context: %s", exc)

    def _build_fingerprint_args(self, profile: dict[str, Any]) -> list[str]:
        """Build extra Chromium args from profile fingerprint settings."""
        args: list[str] = []
        if self.runtime.viewer_mode == "vnc":
            args.append("--use-angle=swiftshader")

        seed = profile.get("fingerprint_seed")
        if seed is not None:
            args.append(f"--fingerprint={seed}")

        # Persona is always determined by the runtime, not editable profile data.
        platform = "macos" if self.runtime.host_os == "macos" else "windows"
        args.append(f"--fingerprint-platform={platform}")

        # Noise perturbation control:
        # Default canvas noise perturbation triggers canvasIntegrity bot signals
        # (pixelRoundTripChanged and textSerializationRoundTripChanged) in modern detectors.
        # Passing --fingerprint-noise=false disables synthetic noise and produces clean canvas reads.
        if not profile.get("canvas_noise", False):
            args.append("--fingerprint-noise=false")

        # Apple GPU models are selected automatically by the seeded macOS
        # persona. Windows vendor-family overrides are incoherent on macOS.
        gpu_family = profile.get("gpu_family", "auto")
        if self.runtime.host_os != "macos":
            if gpu_family == "nvidia":
                args.append("--fingerprint-gpu-vendor=NVIDIA")
            elif gpu_family == "intel":
                args.append("--fingerprint-gpu-vendor=Intel")
            elif profile.get("webgl_vendor") or profile.get("webgl_renderer"):
                wv_combined = f"{profile.get('webgl_vendor') or ''} {profile.get('webgl_renderer') or ''}".lower()
                if any(k in wv_combined for k in ("nvidia", "geforce", "rtx", "gtx")):
                    args.append("--fingerprint-gpu-vendor=NVIDIA")
                elif any(k in wv_combined for k in ("intel", "iris", "arc")):
                    args.append("--fingerprint-gpu-vendor=Intel")
                elif any(k in wv_combined for k in ("amd", "radeon")):
                    args.append("--fingerprint-gpu-vendor=AMD")

        # Native hardware concurrency & device memory
        cpu_cores = profile.get("cpu_cores")
        if cpu_cores:
            args.append(f"--fingerprint-hardware-concurrency={int(cpu_cores)}")
        memory_gb = profile.get("memory_gb")
        if memory_gb:
            args.append(f"--fingerprint-device-memory={int(memory_gb)}")

        # WebGL renderer override
        wr = profile.get("webgl_renderer")
        if wr:
            args.append(f"--fingerprint-gpu-renderer={str(wr).strip()}")

        wv = profile.get("webgl_vendor")
        if wv and self.runtime.host_os == "macos":
            args.append(f"--fingerprint-gpu-vendor={str(wv).strip()}")


        if profile.get("do_not_track", False):
            args.append("--enable-do-not-track")

        if profile.get("allow_3p_cookies", False):
            args.append("--fingerprint-allow-3p-cookies")

        sw = profile.get("screen_width")
        sh = profile.get("screen_height")
        if sw:
            args.append(f"--fingerprint-screen-width={sw}")
        if sh:
            args.append(f"--fingerprint-screen-height={sh}")

        return args
