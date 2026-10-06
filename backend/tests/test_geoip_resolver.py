"""Unit tests for unified GeoIP resolver module."""

from unittest.mock import MagicMock, patch
import httpx
import pytest

from backend import geoip_resolver


@pytest.fixture(autouse=True)
def clear_cache():
    geoip_resolver._GEO_CACHE.clear()
    yield
    geoip_resolver._GEO_CACHE.clear()


def test_resolve_ip_geo_invalid_and_loopback():
    assert geoip_resolver.resolve_ip_geo(None) == {"country": None, "city": None, "timezone": None, "locale": None}
    assert geoip_resolver.resolve_ip_geo("") == {"country": None, "city": None, "timezone": None, "locale": None}
    assert geoip_resolver.resolve_ip_geo("127.0.0.1") == {"country": None, "city": None, "timezone": None, "locale": None}
    assert geoip_resolver.resolve_ip_geo("localhost") == {"country": None, "city": None, "timezone": None, "locale": None}


def test_resolve_ip_geo_online_ipinfo_success():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "ip": "12.77.62.190",
        "city": "Dallas",
        "region": "Texas",
        "country": "US",
        "timezone": "America/Chicago",
    }

    with patch("httpx.get", return_value=fake_resp) as mock_get:
        geo = geoip_resolver.resolve_ip_geo("12.77.62.190")
        assert geo["country"] == "US"
        assert geo["city"] == "Dallas"
        assert geo["timezone"] == "America/Chicago"
        assert geo["locale"] == "en-US"
        mock_get.assert_called_once()


def test_resolve_ip_geo_online_failure_fallback_to_geolite2():
    with patch("httpx.get", side_effect=httpx.ConnectTimeout("timeout")):
        geo = geoip_resolver.resolve_ip_geo("12.77.62.190")
        # Offline GeoLite2 resolves 12.77.62.190 as Detroit
        assert geo["country"] == "US"
        assert geo["city"] == "Detroit"
        assert geo["timezone"] == "America/Detroit"
        assert geo["locale"] == "en-US"


def test_resolve_ip_geo_cache_hit():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "ip": "8.8.8.8",
        "city": "Mountain View",
        "country": "US",
        "timezone": "America/Los_Angeles",
    }

    with patch("httpx.get", return_value=fake_resp) as mock_get:
        geo1 = geoip_resolver.resolve_ip_geo("8.8.8.8")
        assert geo1["timezone"] == "America/Los_Angeles"
        assert mock_get.call_count == 1

        # Second call should hit memory cache without calling httpx.get
        geo2 = geoip_resolver.resolve_ip_geo("8.8.8.8")
        assert geo2["timezone"] == "America/Los_Angeles"
        assert mock_get.call_count == 1
