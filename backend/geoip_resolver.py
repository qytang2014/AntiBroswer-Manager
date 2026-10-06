"""GeoIP resolution with online-first priority (aligned with BrowserScan / IPinfo) and local GeoLite2 fallback."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("backend.geoip_resolver")

_GEO_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_GEO_CACHE_TTL = 3600.0  # 1 hour cache


def resolve_ip_geo(ip: str | None, timeout: float = 2.0) -> dict[str, Any]:
    """Resolve geographic information (country, city, timezone, locale) for an IPv4/IPv6 address.

    Online-first strategy:
    1. Check memory cache.
    2. Query ipinfo.io ({ip}/json) which aligns with BrowserScan.net.
    3. Fallback to offline MaxMind GeoLite2 database if online query fails, times out, or offline.
    """
    empty_result = {"country": None, "city": None, "timezone": None, "locale": None}
    if not ip or not isinstance(ip, str):
        return empty_result

    clean_ip = ip.strip()
    if not clean_ip or clean_ip in ("127.0.0.1", "localhost", "::1"):
        return empty_result

    now = time.monotonic()
    if clean_ip in _GEO_CACHE:
        cached_time, cached_val = _GEO_CACHE[clean_ip]
        if now - cached_time < _GEO_CACHE_TTL:
            return dict(cached_val)

    from cloakbrowser.geoip import COUNTRY_LOCALE_MAP, _ensure_geoip_db

    # 1. Try online ipinfo.io (matches BrowserScan.net)
    try:
        url = f"https://ipinfo.io/{clean_ip}/json"
        resp = httpx.get(url, timeout=httpx.Timeout(timeout), follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
            country = data.get("country")
            city = data.get("city")
            tz = data.get("timezone")
            locale = COUNTRY_LOCALE_MAP.get(country, "en-US") if country else None
            if country or tz:
                res = {
                    "country": country or None,
                    "city": city or None,
                    "timezone": tz or None,
                    "locale": locale or None,
                }
                _GEO_CACHE[clean_ip] = (now, res)
                return res
    except Exception as exc:
        logger.debug("Online GeoIP query for %s failed (%s), falling back to offline GeoLite2", clean_ip, exc)

    # 2. Offline fallback: local MaxMind GeoLite2
    try:
        import geoip2.database

        with geoip2.database.Reader(_ensure_geoip_db()) as reader:
            city_resp = reader.city(clean_ip)
            country = city_resp.country.iso_code
            city = city_resp.city.name
            tz = city_resp.location.time_zone
            locale = COUNTRY_LOCALE_MAP.get(country, "en-US") if country else None
            res = {
                "country": country or None,
                "city": city or None,
                "timezone": tz or None,
                "locale": locale or None,
            }
            _GEO_CACHE[clean_ip] = (now, res)
            return res
    except Exception as exc:
        logger.debug("Offline GeoLite2 lookup failed for %s: %s", clean_ip, exc)

    return empty_result
