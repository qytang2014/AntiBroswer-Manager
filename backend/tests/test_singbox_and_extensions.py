"""Unit tests for sing-box proxy integration, caching, and Chrome extensions management."""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from fastapi.testclient import TestClient

from backend import database as db
from backend.browser_manager import (
    _normalize_proxy,
    _validate_proxy,
    test_proxy as run_test_proxy,
    _PROXY_TEST_CACHE,
)
from backend.extension_manager import (
    extract_webstore_id,
    install_extension_from_bytes,
    remove_extension,
    POPULAR_EXTENSIONS,
)
from backend.main import app


# conftest.py provides app_client and tmp_db fixtures


def test_normalize_and_validate_singbox_proxy():
    # 1. Sing-box URI
    vless_uri = (
        "vless://00000000-0000-0000-0000-000000000000@1.2.3.4:443"
        "?type=ws&security=tls&path=%2Fws#test"
    )
    norm = _normalize_proxy(vless_uri)
    assert isinstance(norm, dict)
    assert norm.get("type") == "singbox"
    assert norm.get("config") == vless_uri
    _validate_proxy(norm)

    # 2. Sing-box JSON string
    json_str = json.dumps({
        "outbounds": [
            {
                "type": "vless",
                "tag": "proxy",
                "server": "1.2.3.4",
                "server_port": 443,
                "uuid": "00000000-0000-0000-0000-000000000000",
            }
        ]
    })
    norm_json = _normalize_proxy(json_str, proxy_type="singbox_json")
    assert isinstance(norm_json, dict)
    assert norm_json.get("type") == "singbox"
    _validate_proxy(norm_json)

    # 3. Standard HTTP proxy
    std_proxy = "http://user:pass@1.2.3.4:8080"
    norm_std = _normalize_proxy(std_proxy)
    assert norm_std == std_proxy
    _validate_proxy(norm_std)


@pytest.mark.asyncio
async def test_proxy_test_caching():
    proxy_uri = "vless://00000000-0000-0000-0000-000000000000@example.com:443#test-cache"
    _PROXY_TEST_CACHE.clear()

    mock_result = {
        "ok": True,
        "ip": "1.1.1.1",
        "country": "US",
        "city": "Dallas",
        "latency_ms": 50,
        "cached": False,
    }

    with patch("backend.browser_manager._test_proxy_sync", return_value=mock_result) as mock_sync:
        # First call: executes sync
        res1 = await run_test_proxy(proxy_uri, "singbox_uri")
        assert res1["ok"] is True
        assert res1["ip"] == "1.1.1.1"
        assert res1["cached"] is False
        assert mock_sync.call_count == 1

        # Second call immediately: hits LRU cache, does not call sync again!
        res2 = await run_test_proxy(proxy_uri, "singbox_uri")
        assert res2["ok"] is True
        assert res2["cached"] is True
        assert mock_sync.call_count == 1


def test_extension_manager_unpack_and_db(tmp_db):
    # Create a mock zip extension with manifest.json
    manifest_data = {
        "manifest_version": 3,
        "name": "Test Extension",
        "version": "1.2.3",
        "description": "A test chrome extension",
    }
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest_data))
    zip_bytes = zip_buffer.getvalue()

    # Install extension
    import asyncio
    ext = asyncio.run(install_extension_from_bytes(zip_bytes, "test.zip", source="upload"))
    assert ext["name"] == "Test Extension"
    assert ext["version"] == "1.2.3"
    assert Path(ext["path"]).is_dir()

    # List and verify in DB
    all_exts = db.list_extensions()
    assert any(e["id"] == ext["id"] for e in all_exts)

    # Delete extension
    removed = remove_extension(ext["id"])
    assert removed is True
    assert not Path(ext["path"]).exists()


def test_webstore_id_extractor():
    url1 = "https://chromewebstore.google.com/detail/ublock-origin/cjpalhdlnbpafiamejdnhcphjbkeiagm"
    assert extract_webstore_id(url1) == "cjpalhdlnbpafiamejdnhcphjbkeiagm"

    raw_id = "cjpalhdlnbpafiamejdnhcphjbkeiagm"
    assert extract_webstore_id(raw_id) == "cjpalhdlnbpafiamejdnhcphjbkeiagm"

    assert extract_webstore_id("invalid-id-here") is None


def test_extensions_api(app_client):
    # Popular list
    resp = app_client.get("/api/extensions/popular")
    assert resp.status_code == 200
    popular = resp.json()
    assert len(popular) > 0
    names = [p["name"] for p in popular]
    assert "Bitwarden Password Manager" in names
    assert "floccus bookmarks sync" in names
    assert "MetaMask" not in names
    assert "Proxy SwitchyOmega" not in names

    # List extensions
    resp = app_client.get("/api/extensions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_search_webstore_api(app_client):
    from unittest.mock import patch

    mock_html = """
    <div data-item-id="nngceckbapebfimnlniiiahkandclblb">
        <h2>Bitwarden Password Manager</h2>
        <img src="https://lh3.googleusercontent.com/icon.png" />
        <p>A secure and free password manager for all of your devices.</p>
    </div>
    """
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        resp = app_client.get("/api/extensions/webstore/search?q=bitwarden")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["id"] == "nngceckbapebfimnlniiiahkandclblb"
        assert results[0]["name"] == "Bitwarden Password Manager"
        assert "password manager" in results[0]["description"].lower()


def test_search_webstore_network_error(app_client):
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectTimeout("Timeout")):
        resp = app_client.get("/api/extensions/webstore/search?q=something_nonexistent_xyz")
        assert resp.status_code == 502
        assert "网络错误: 无法连接到 Chrome 应用商店" in resp.json()["detail"]


def test_install_webstore_network_error(app_client):
    with patch("httpx.AsyncClient.stream", side_effect=httpx.ConnectTimeout("Timeout")):
        resp = app_client.post("/api/extensions/install-webstore", json={"id_or_url": "nngceckbapebfimnlniiiahkandclblb"})
        assert resp.status_code == 400
        assert "网络错误: 无法连接到 Chrome 应用商店" in resp.json()["detail"]


def test_install_webstore_stream_api(app_client):
    with patch("httpx.AsyncClient.stream", side_effect=httpx.ConnectTimeout("Timeout")):
        resp = app_client.get("/api/extensions/install-webstore-stream?id_or_url=nngceckbapebfimnlniiiahkandclblb")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        body = resp.text
        assert "connecting" in body
        assert "error" in body
        assert "网络错误: 无法连接到 Chrome 应用商店" in body


@pytest.mark.asyncio
async def test_stream_install_resumable_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import contextlib
    from backend import extension_manager
    from backend.extension_manager import stream_install_from_webstore
    from backend import database as db

    fake_ext_dir = tmp_path / "extensions"
    fake_ext_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(extension_manager, "EXTENSIONS_DIR", fake_ext_dir)
    monkeypatch.setattr(db, "create_extension", MagicMock(return_value={
        "id": "abcdefghijklmnopabcdefghijklmnop",
        "name": "Resumable Extension",
        "version": "1.0.0",
        "description": "",
        "icon_url": None,
        "path": str(fake_ext_dir / "abcdefghijklmnopabcdefghijklmnop"),
        "source": "webstore_id",
        "webstore_id": "abcdefghijklmnopabcdefghijklmnop",
        "created_at": "2026-01-01T00:00:00Z",
    }))

    manifest_data = {
        "manifest_version": 3,
        "name": "Resumable Extension",
        "version": "1.0.0",
    }
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest_data))
    full_bytes = zip_buffer.getvalue()
    midpoint = len(full_bytes) // 2

    call_count = 0

    @contextlib.asynccontextmanager
    async def mock_stream(method, url, headers=None, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()

        if call_count == 1:
            # First attempt: returns first half, then raises TransportError
            resp.status_code = 200
            resp.headers = {"content-length": str(len(full_bytes))}
            async def aiter_bytes(chunk_size=65536):
                yield full_bytes[:midpoint]
                raise httpx.TransportError("Network disconnect mid-download")
            resp.aiter_bytes = aiter_bytes
            yield resp
        else:
            # Second attempt: client sends Range header, server returns 206
            assert headers and f"bytes={midpoint}-" in headers.get("Range", "")
            resp.status_code = 206
            resp.headers = {
                "content-range": f"bytes {midpoint}-{len(full_bytes) - 1}/{len(full_bytes)}",
                "content-length": str(len(full_bytes) - midpoint),
            }
            async def aiter_bytes(chunk_size=65536):
                yield full_bytes[midpoint:]
            resp.aiter_bytes = aiter_bytes
            yield resp

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        events = []
        async for ev in stream_install_from_webstore("abcdefghijklmnopabcdefghijklmnop"):
            events.append(ev)

        stages = [e["stage"] for e in events]
        assert "connecting" in stages
        assert "downloading" in stages
        assert "unpacking" in stages
        assert "completed" in stages

        completed = next(e for e in events if e["stage"] == "completed")
        assert completed["extension"]["name"] == "Resumable Extension"


def test_probe_proxy_target():
    from backend.browser_manager import _probe_proxy_target

    with patch("httpx.get") as mock_get:
        def side_effect(url, **kwargs):
            mock_resp = MagicMock()
            if "generate_204" in url:
                mock_resp.status_code = 204
                return mock_resp
            if "api.ip.sb" in url:
                mock_resp.status_code = 200
                mock_resp.text = "1.2.3.4\n"
                return mock_resp
            mock_resp.status_code = 500
            return mock_resp

        mock_get.side_effect = side_effect
        ip, latency, err = _probe_proxy_target("http://127.0.0.1:1080")
        assert ip == "1.2.3.4"
        assert latency is not None
        assert latency >= 1
        assert err is None


def test_resolve_profile_network_fingerprint_sync():
    from backend.browser_manager import _resolve_profile_network_fingerprint_sync

    mock_city = MagicMock()
    mock_city.location.time_zone = "America/Chicago"
    mock_city.country.iso_code = "US"
    mock_reader = MagicMock()
    mock_reader.__enter__.return_value.city.return_value = mock_city

    with patch("backend.browser_manager._probe_proxy_target", return_value=("8.8.8.8", 50, None)), \
         patch("geoip2.database.Reader", return_value=mock_reader):
        # 1. Profile with empty timezone/locale -> auto-matched from exit IP
        profile_auto = {"timezone": None, "locale": None, "geoip": True, "launch_args": []}
        tz, loc, args = _resolve_profile_network_fingerprint_sync("http://127.0.0.1:1080", profile_auto)
        assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in args
        assert "--fingerprint-webrtc-ip=8.8.8.8" in args
        assert tz == "America/Chicago"
        assert loc == "en-US"

        # 2. Profile with explicit timezone and locale -> user preference preserved
        profile_manual = {
            "timezone": "Europe/London",
            "locale": "en-GB",
            "geoip": False,
            "launch_args": [],
        }
        tz_m, loc_m, args_m = _resolve_profile_network_fingerprint_sync("http://127.0.0.1:1080", profile_manual)
        assert tz_m == "Europe/London"
        assert loc_m == "en-GB"
        assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in args_m

        # 3. Profile without proxy -> no probe, no WebRTC args
        tz_none, loc_none, args_none = _resolve_profile_network_fingerprint_sync(None, profile_auto)
        assert args_none == []


def test_kernel_manager_list_and_binary_ready():
    from backend.kernel_manager import list_available_kernels, is_binary_ready

    data = list_available_kernels()
    assert isinstance(data, dict)
    assert isinstance(data["kernels"], list)
    assert len(data["kernels"]) >= 1
    assert data["current_platform"] in [
        "darwin-arm64", "darwin-x64", "linux-x64", "windows-x64",
        "darwin_arm64", "darwin_x64", "linux_x64", "windows_x64",
        "unknown"
    ]
    assert data["current_tier"] in ["pro", "free", "keyless"]
    assert isinstance(data["installed"], bool)

    # is_binary_ready should return bool and not throw or trigger download
    ready = is_binary_ready()
    assert isinstance(ready, bool)


def test_kernel_api_endpoints(app_client):
    # 1. GET /api/kernels
    resp = app_client.get("/api/kernels")
    assert resp.status_code == 200
    data = resp.json()
    assert "current_platform" in data
    assert "current_tier" in data
    assert "installed" in data
    assert "kernels" in data
    assert isinstance(data["kernels"], list)

    # 2. DELETE non-existent kernel
    resp_del = app_client.delete("/api/kernels/non_existent_version_999")
    assert resp_del.status_code == 404


@pytest.mark.asyncio
async def test_check_extensions_updates(monkeypatch: pytest.MonkeyPatch):
    from backend import extension_manager
    from backend import database as db

    fake_extensions = [
        {
            "id": "ext1",
            "name": "Extension One",
            "version": "1.0.0",
            "source": "webstore_id",
            "webstore_id": "abcdefghijklmnopabcdefghijklmnop",
        },
        {
            "id": "ext2",
            "name": "Extension Two",
            "version": "2.0.0",
            "source": "webstore_id",
            "webstore_id": "bcdefghijklmnopabcdefghijklmnopa",
        },
        {
            "id": "ext3",
            "name": "Extension Three",
            "version": "3.0.0",
            "source": "upload",
            "webstore_id": None,
        },
    ]

    monkeypatch.setattr(db, "list_extensions", lambda: fake_extensions)

    xml_response = """<?xml version="1.0" encoding="UTF-8"?>
    <gupdate xmlns="http://www.google.com/update2/response" protocol="2.0">
        <app appid="abcdefghijklmnopabcdefghijklmnop">
            <updatecheck status="ok" version="1.2.0" codebase="https://example.com/ext1.crx"/>
        </app>
        <app appid="bcdefghijklmnopabcdefghijklmnopa">
            <updatecheck status="noupdate"/>
        </app>
    </gupdate>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = xml_response

    async def mock_get(self, url, **kwargs):
        return mock_resp

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await extension_manager.check_extensions_updates()
    assert "updates" in result
    assert "checked_at" in result

    updates = result["updates"]
    assert updates["ext1"]["has_update"] is True
    assert updates["ext1"]["latest_version"] == "1.2.0"
    assert updates["ext1"]["status"] == "update_available"

    assert updates["ext2"]["has_update"] is False
    assert updates["ext2"]["latest_version"] == "2.0.0"
    assert updates["ext2"]["status"] == "up_to_date"

    assert updates["ext3"]["has_update"] is False
    assert updates["ext3"]["status"] == "unsupported"


def test_check_extensions_updates_api(app_client, monkeypatch: pytest.MonkeyPatch):
    from backend import database as db

    monkeypatch.setattr(db, "list_extensions", lambda: [])

    resp = app_client.post("/api/extensions/check-updates")
    assert resp.status_code == 200
    data = resp.json()
    assert "updates" in data
    assert "checked_at" in data



