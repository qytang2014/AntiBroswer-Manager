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


def test_resolve_ip_geo_online_failure_fallback_to_geolite2(tmp_path):
    """Offline fallback must work without network access.

    The real GeoLite2-City.mmdb (~70 MB) is downloaded on first use; unit tests
    must not depend on that download or CI becomes flaky whenever the mirror
    is unreachable. Mock the database lookup instead.
    """
    fake_city = MagicMock()
    fake_city.country.iso_code = "US"
    fake_city.city.name = "Detroit"
    fake_city.location.time_zone = "America/Detroit"

    fake_reader = MagicMock()
    fake_reader.__enter__.return_value = fake_reader
    fake_reader.city.return_value = fake_city

    fake_db = tmp_path / "GeoLite2-City.mmdb"
    fake_db.touch()

    with (
        patch("httpx.get", side_effect=httpx.ConnectTimeout("timeout")),
        patch("cloakbrowser.geoip._ensure_geoip_db", return_value=fake_db),
        patch("geoip2.database.Reader", return_value=fake_reader) as mock_reader,
    ):
        geo = geoip_resolver.resolve_ip_geo("12.77.62.190")

    assert geo["country"] == "US"
    assert geo["city"] == "Detroit"
    assert geo["timezone"] == "America/Detroit"
    assert geo["locale"] == "en-US"
    mock_reader.assert_called_once_with(fake_db)


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
