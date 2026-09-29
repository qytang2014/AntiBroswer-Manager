"""Shared test fixtures for backend tests."""

from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure tests on Linux outside Docker never default to root /data if unmocked
_test_data_dir = Path(tempfile.gettempdir()) / "antibrowser_test_data"
_test_data_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("ANTIBROWSER_MANAGER_DATA_DIR", str(_test_data_dir))

# ---------------------------------------------------------------------------
# Mock cloakbrowser BEFORE any backend module is imported.
# browser_manager.py does `from cloakbrowser import launch_persistent_context_async`
# at module level, and main.py imports BrowserManager which triggers it.
# main.py:381 also does `from cloakbrowser.config import CHROMIUM_VERSION`.
# ---------------------------------------------------------------------------

try:
    import cloakbrowser
    _mock_cloakbrowser = cloakbrowser
except ImportError:
    _proxy_repo = Path(__file__).resolve().parents[3] / "CloakBrowser-Proxy"
    if _proxy_repo.exists() and str(_proxy_repo) not in sys.path:
        sys.path.insert(0, str(_proxy_repo))
    _mock_cloakbrowser = types.ModuleType("cloakbrowser")
    _mock_cloakbrowser.__path__ = [str(_proxy_repo / "cloakbrowser")] if (_proxy_repo / "cloakbrowser").exists() else []
    sys.modules.setdefault("cloakbrowser", _mock_cloakbrowser)

_mock_cloakbrowser.launch_persistent_context_async = AsyncMock()  # type: ignore[attr-defined]

try:
    import cloakbrowser.config as _real_config
    _real_config.CHROMIUM_VERSION = "0.0.0-test"
    _real_config.get_chromium_version = lambda: "0.0.0-test"
    sys.modules["cloakbrowser.config"] = _real_config
except Exception:
    _mock_config = types.ModuleType("cloakbrowser.config")
    _mock_config.CHROMIUM_VERSION = "0.0.0-test"  # type: ignore[attr-defined]
    _mock_config.get_chromium_version = lambda: "0.0.0-test"  # type: ignore[attr-defined]
    _mock_config.get_cache_dir = lambda: Path("/tmp")  # type: ignore[attr-defined]
    _mock_config.DOWNLOAD_BASE_URL = "https://mock.download.com"
    _mock_config.PLATFORM_CHROMIUM_VERSIONS = {}
    _mock_config.get_archive_ext = lambda: ".tar.gz"
    _mock_config.get_archive_name = lambda: "mock.tar.gz"
    _mock_config.get_binary_dir = lambda: Path("/tmp/mock_bin")
    _mock_config.get_binary_path = lambda *a, **kw: Path("/tmp/mock_bin/mock")
    _mock_config.get_download_url = lambda *a, **kw: "https://mock.download.com"
    _mock_config.get_effective_version = lambda *a, **kw: "0.0.0-test"
    _mock_config.get_fallback_download_url = lambda *a, **kw: "https://mock.download.com"
    _mock_config.get_platform_tag = lambda: "darwin_arm64"
    sys.modules["cloakbrowser.config"] = _mock_config

try:
    import cloakbrowser.download as _real_download
    sys.modules["cloakbrowser.download"] = _real_download
except Exception:
    _mock_download = types.ModuleType("cloakbrowser.download")
    _mock_download.ensure_binary = MagicMock()  # type: ignore[attr-defined]
    _mock_download.DOWNLOAD_TIMEOUT = 30
    _mock_download._extract_archive = MagicMock()
    _mock_download._is_executable = MagicMock(return_value=True)
    _mock_download._pro_binary_ready = MagicMock(return_value=False)
    _mock_download._verify_download_checksum = MagicMock(return_value=True)
    _mock_download._verify_pro_download = MagicMock(return_value=True)
    _mock_download._write_pro_version_marker = MagicMock()
    _mock_download._write_version_marker = MagicMock()
    _mock_download.binary_info = MagicMock(return_value={})
    sys.modules["cloakbrowser.download"] = _mock_download

_mock_license = types.ModuleType("cloakbrowser.license")
_mock_license.resolve_license_key = lambda key=None: key  # type: ignore[attr-defined]
_mock_license.validate_license = lambda key: None  # type: ignore[attr-defined]
_mock_license.get_pro_latest_version = lambda channel=None: None  # type: ignore[attr-defined]
# browser_manager.py surfaces license/seat denials — it imports these at module
# level, so the mock must expose them or collection fails with ImportError.
_mock_license.CloakBrowserLicenseError = type(  # type: ignore[attr-defined]
    "CloakBrowserLicenseError", (RuntimeError,), {}
)
_mock_license.license_error_for_code = lambda code: None  # type: ignore[attr-defined]
_mock_license.read_denial_file = lambda path: None  # type: ignore[attr-defined]
sys.modules["cloakbrowser.license"] = _mock_license



from backend import database as db  # noqa: E402
from backend.runtime import RuntimeConfig  # noqa: E402


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point database module at a temp directory and init schema."""
    db_file = tmp_path / "profiles.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    from backend import extension_manager
    fake_ext_dir = tmp_path / "extensions"
    fake_ext_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(extension_manager, "EXTENSIONS_DIR", fake_ext_dir)
    db.init_db()
    return tmp_path


@pytest.fixture()
def sample_profile(tmp_db: Path):
    """Create and return a sample profile dict."""
    return db.create_profile(name="Test Profile", fingerprint_seed=12345)


@pytest.fixture()
def app_client(tmp_db: Path, monkeypatch: pytest.MonkeyPatch):
    """FastAPI TestClient with mocked DB and browser manager."""
    from backend import main

    # API tests exercise the existing Linux Docker contract on every host OS.
    dummy_runtime = RuntimeConfig("linux", "docker", "vnc", tmp_db)
    monkeypatch.setattr(main.browser_mgr, "runtime", dummy_runtime)
    monkeypatch.setattr("backend.runtime.resolve_runtime", lambda *a, **kw: dummy_runtime)
    monkeypatch.setattr("backend.settings_store.resolve_runtime", lambda *a, **kw: dummy_runtime)
    monkeypatch.setattr("backend.backup.manager.resolve_runtime", lambda *a, **kw: dummy_runtime)
    monkeypatch.setattr("backend.backup.credentials.resolve_runtime", lambda *a, **kw: dummy_runtime)
    monkeypatch.setattr("backend.backup.archiver.resolve_runtime", lambda *a, **kw: dummy_runtime)
    monkeypatch.setattr(main.browser_mgr.vnc, "enabled", True)

    # Patch lifespan-called methods to avoid host KasmVNC/process requirements.
    monkeypatch.setattr(main.browser_mgr.vnc, "validate_available", MagicMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    monkeypatch.setattr(main.browser_mgr.vnc, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr, "license_key", None)
    main.browser_mgr.resolve_binary_status()

    from starlette.testclient import TestClient

    with TestClient(main.app) as client:
        yield client
