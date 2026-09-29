import asyncio
import io
import json
from pathlib import Path
import zipfile
import pytest

from backend.camoufox_downloader import (
    scan_all_installed_camoufox_kernels,
    get_camoufox_kernel_list,
    stream_download_camoufox,
    _dict_to_available_version,
)
import backend.camoufox_downloader as cd
from backend.kernel_manager import stream_download_kernel


def test_scan_all_installed_camoufox_aliases_in_managed_dir(tmp_path: Path, monkeypatch):
    browsers_dir = tmp_path / "browsers"
    official_dir = browsers_dir / "official"
    version_dir = official_dir / "152.0.4-beta.31-7b8d12d6"
    version_dir.mkdir(parents=True)

    # Create dummy Camoufox.app executable
    app_bin = version_dir / "Camoufox.app" / "Contents" / "MacOS" / "camoufox"
    app_bin.parent.mkdir(parents=True)
    app_bin.write_bytes(b"dummy binary")

    # Point downloader to tmp_path
    monkeypatch.setattr(cd, "_camoufox_data_dir", tmp_path)
    monkeypatch.setattr(cd.cm, "BROWSERS_DIR", browsers_dir)

    scanned = scan_all_installed_camoufox_kernels()

    # Verify all aliases exist in scanned mapping
    assert "152.0.4-beta.31-7b8d12d6" in scanned
    assert "152.0.4-beta.31" in scanned
    assert "v152.0.4-beta.31" in scanned
    assert "152.0.4" not in scanned
    assert "beta.31" not in scanned

    item = scanned["152.0.4-beta.31"]
    assert item["binary_path"] == str(app_bin)
    assert item["version"] == "152.0.4"
    assert item["build"] == "beta.31"


def test_get_camoufox_kernel_list_matches_with_sha_suffix(tmp_path: Path, monkeypatch):
    browsers_dir = tmp_path / "browsers"
    version_dir = browsers_dir / "official" / "152.0.4-beta.31-7b8d12d6"
    version_dir.mkdir(parents=True)

    app_bin = version_dir / "camoufox"
    app_bin.write_bytes(b"dummy executable")

    (version_dir / "version.json").write_text(
        json.dumps({"version": "152.0.4", "build": "beta.31", "prerelease": False})
    )

    monkeypatch.setattr(cd, "_camoufox_data_dir", tmp_path)
    monkeypatch.setattr(cd.cm, "BROWSERS_DIR", browsers_dir)

    # Mock catalog
    mock_item = {
        "version": "152.0.4",
        "build": "beta.31",
        "display": "v152.0.4-beta.31",
        "url": "https://example.com/camoufox.zip",
        "asset_size": 1024,
        "sha256": "7b8d12d61de9a9fbd3ce9c034399ba5307e44f4d8951873cc53ad39d20957737",
        "is_prerelease": False,
    }
    monkeypatch.setattr(cd, "fetch_camoufox_available_versions", lambda force_refresh=False: [_dict_to_available_version(mock_item)])

    kernels = get_camoufox_kernel_list()
    assert len(kernels) >= 1
    matched = next((k for k in kernels if "152.0.4-beta.31" in k["version"]), None)
    assert matched is not None
    assert matched["installed"] is True
    assert matched["binary_path"] == str(app_bin)


@pytest.mark.asyncio
async def test_stream_download_camoufox_reuses_existing_kernel_without_download(tmp_path: Path, monkeypatch):
    """Verify that when a Camoufox kernel is already present on disk, it is directly reused without downloading."""
    browsers_dir = tmp_path / "browsers"
    existing_dir = browsers_dir / "official" / "152.0.4-beta.31-7b8d12d6"
    existing_dir.mkdir(parents=True)
    existing_bin = existing_dir / "camoufox"
    existing_bin.write_bytes(b"pre-existing working binary")

    monkeypatch.setattr(cd, "_camoufox_data_dir", tmp_path)
    monkeypatch.setattr(cd.cm, "BROWSERS_DIR", browsers_dir)

    # If any network call is attempted, fail immediately
    class FailingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Network client should not be called when kernel already exists locally!")

    monkeypatch.setattr(cd.httpx, "AsyncClient", FailingClient)

    events = []
    async for event in stream_download_camoufox("152.0.4-beta.31"):
        events.append(event)

    last_event = events[-1]
    assert last_event["stage"] == "completed"
    assert "直接复用" in last_event["message"]
    assert last_event["binary_path"] == str(existing_bin)


@pytest.mark.asyncio
async def test_stream_download_kernel_reuses_existing_chromium_without_download(tmp_path: Path, monkeypatch):
    """Verify that when a Chromium kernel already exists locally, stream_download_kernel reuses it directly."""
    import backend.kernel_manager as km

    mock_bin_dir = tmp_path / "chromium-145.0.7632.109.2"
    mock_bin_dir.mkdir(parents=True)
    mock_bin = mock_bin_dir / "chrome"
    mock_bin.write_bytes(b"dummy chrome")
    mock_bin.chmod(0o755)

    monkeypatch.setattr(km, "get_binary_dir", lambda version, pro=False: mock_bin_dir)
    monkeypatch.setattr(km, "get_binary_path", lambda version, pro=False: mock_bin)
    monkeypatch.setattr(km, "_is_executable", lambda p: True)

    class FailingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Network client should not be called when Chromium kernel exists locally!")

    monkeypatch.setattr(km.httpx, "AsyncClient", FailingClient)

    events = []
    async for event in stream_download_kernel(version="145.0.7632.109.2", tier="free"):
        events.append(event)

    last_event = events[-1]
    assert last_event["stage"] == "completed"
    assert "直接复用" in last_event["message"]
    assert last_event["binary_path"] == str(mock_bin)


@pytest.mark.asyncio
async def test_stream_download_camoufox_preserves_existing_on_failure(tmp_path: Path, monkeypatch):
    """Verify that an interrupted or failed download NEVER deletes an existing working installation."""
    browsers_dir = tmp_path / "browsers"
    existing_dir = browsers_dir / "official" / "152.0.4-beta.30-other"
    existing_dir.mkdir(parents=True)
    existing_bin = existing_dir / "camoufox"
    existing_bin.write_bytes(b"pre-existing other version")

    monkeypatch.setattr(cd, "_camoufox_data_dir", tmp_path)
    monkeypatch.setattr(cd.cm, "BROWSERS_DIR", browsers_dir)

    mock_item = {
        "version": "152.0.4",
        "build": "beta.31",
        "display": "v152.0.4-beta.31",
        "url": "https://example.com/camoufox-fail.zip",
        "asset_size": 1000,
        "sha256": "7b8d12d61de9a9fbd3ce9c034399ba5307e44f4d8951873cc53ad39d20957737",
        "is_prerelease": False,
    }
    monkeypatch.setattr(cd, "fetch_camoufox_available_versions", lambda force_refresh=False: [_dict_to_available_version(mock_item)])

    # Mock httpx to raise connection error
    class MockStreamContext:
        async def __aenter__(self):
            raise ConnectionResetError("Remote end closed connection without response")
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        def stream(self, method, url, **kwargs):
            return MockStreamContext()

    monkeypatch.setattr(cd.httpx, "AsyncClient", MockClient)

    events = []
    async for event in stream_download_camoufox("152.0.4-beta.31"):
        events.append(event)

    last_event = events[-1]
    assert last_event["stage"] == "error"
    assert "下载失败" in last_event["message"]

    # CRITICAL: Verify existing installation is completely untouched!
    assert existing_dir.exists()
    assert existing_bin.exists()
    assert existing_bin.read_bytes() == b"pre-existing other version"


@pytest.mark.asyncio
async def test_stream_download_camoufox_success_pipeline(tmp_path: Path, monkeypatch):
    """Verify download, SHA check, atomic extraction, permissions, and deployment."""
    browsers_dir = tmp_path / "browsers"
    monkeypatch.setattr(cd, "_camoufox_data_dir", tmp_path)
    monkeypatch.setattr(cd.cm, "BROWSERS_DIR", browsers_dir)

    # Create dummy zip with a camoufox binary
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("camoufox", b"#!/bin/sh\necho camoufox")
    zip_bytes = zip_buf.getvalue()

    import hashlib
    sha256 = hashlib.sha256(zip_bytes).hexdigest()

    mock_item = {
        "version": "152.0.4",
        "build": "beta.31",
        "display": "v152.0.4-beta.31",
        "url": "https://example.com/camoufox-good.zip",
        "asset_size": len(zip_bytes),
        "sha256": sha256,
        "is_prerelease": False,
    }
    monkeypatch.setattr(cd, "fetch_camoufox_available_versions", lambda force_refresh=False: [_dict_to_available_version(mock_item)])

    class MockResponse:
        status_code = 200
        headers = {"content-length": str(len(zip_bytes))}
        async def aiter_bytes(self, chunk_size=131072):
            yield zip_bytes

    class MockStreamContext:
        async def __aenter__(self):
            return MockResponse()
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        def stream(self, method, url, **kwargs):
            return MockStreamContext()

    monkeypatch.setattr(cd.httpx, "AsyncClient", MockClient)

    events = []
    async for event in stream_download_camoufox("152.0.4-beta.31"):
        events.append(event)

    stages = [e["stage"] for e in events]
    assert "connecting" in stages
    assert "downloading" in stages
    assert "verifying" in stages
    assert "extracting" in stages
    assert "completed" in stages

    last_event = events[-1]
    assert last_event["stage"] == "completed"
    assert last_event["binary_path"] is not None

    deployed_bin = Path(last_event["binary_path"])
    assert deployed_bin.exists()
    assert (deployed_bin.parent / "version.json").exists()
