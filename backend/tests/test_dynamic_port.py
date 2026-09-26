import json
import socket
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient

from backend import diagnostics, main
import app_entry


def test_healthcheck_returns_app_metadata(app_client: TestClient):
    """GET /api/health returns status, app name, version, and pid."""
    resp = app_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["app"] == "antibrowser-manager"
    assert data["version"] == diagnostics.app_version()
    assert isinstance(data["pid"], int)


def test_status_includes_server_metadata(app_client: TestClient):
    """GET /api/status includes app_version, server_port, server_host, and server_url."""
    # When app.state has custom server values
    main.app.state.server_port = 9050
    main.app.state.server_host = "127.0.0.1"
    main.app.state.server_url = "http://127.0.0.1:9050"

    resp = app_client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app_version"] == diagnostics.app_version()
    assert data["server_port"] == 9050
    assert data["server_host"] == "127.0.0.1"
    assert data["server_url"] == "http://127.0.0.1:9050"

    # Reset
    main.app.state.server_port = None
    main.app.state.server_host = None
    main.app.state.server_url = None


def test_is_port_bindable_behavior():
    """_is_port_bindable returns True for free port and False for occupied port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        occupied_port = sock.getsockname()[1]
        assert not app_entry._is_port_bindable(occupied_port, "127.0.0.1")

    # Once closed, port should be bindable
    assert app_entry._is_port_bindable(occupied_port, "127.0.0.1")


def test_get_dynamic_free_port():
    """_get_dynamic_free_port asks OS for an unused port."""
    port = app_entry._get_dynamic_free_port("127.0.0.1")
    assert isinstance(port, int)
    assert 1024 <= port <= 65535


def test_resolve_server_port_free_port():
    """When preferred port is bindable, use it directly (defaults to 52341)."""
    with patch.object(app_entry, "_is_port_bindable", return_value=True):
        with patch.dict("os.environ", {}, clear=True):
            port, should_run = app_entry._resolve_server_port()
            assert port == 52341
            assert should_run is True

    # When custom PORT env is provided
    with patch.object(app_entry, "_is_port_bindable", return_value=True):
        with patch.dict("os.environ", {"PORT": "9090"}):
            port, should_run = app_entry._resolve_server_port()
            assert port == 9090
            assert should_run is True


def test_resolve_server_port_third_party_occupied():
    """When default port 52341 is occupied by a 3rd party program, allocate dynamic port immediately."""
    with patch.object(app_entry, "_is_port_bindable", return_value=False):
        with patch.object(app_entry, "_probe_manager_health", return_value=None):
            with patch.object(app_entry, "_get_dynamic_free_port", return_value=54321):
                with patch.dict("os.environ", {}, clear=True):
                    port, should_run = app_entry._resolve_server_port()
                    assert port == 54321
                    assert should_run is True


def test_resolve_server_port_same_version_duplicate_instance():
    """When port is occupied by our app with matching version, focus existing window and exit."""
    with patch.object(app_entry, "_is_port_bindable", return_value=False):
        with patch.object(
            app_entry,
            "_probe_manager_health",
            return_value={"app": "antibrowser-manager", "version": "1.0.0", "pid": 1111},
        ):
            with patch("backend.diagnostics.app_version", return_value="1.0.0"):
                with patch.object(app_entry, "_focus_existing_window", return_value=True) as mock_focus:
                    with patch.dict("os.environ", {}, clear=True):
                        port, should_run = app_entry._resolve_server_port()
                        assert port == 52341
                        assert should_run is False
                        assert mock_focus.called


def test_resolve_server_port_upgrade_older_version():
    """When port is occupied by older version, shutdown old instance and take over."""
    with patch.object(app_entry, "_is_port_bindable", return_value=False):
        with patch.object(
            app_entry,
            "_probe_manager_health",
            return_value={"app": "antibrowser-manager", "version": "0.9.0", "pid": 1111},
        ):
            with patch("backend.diagnostics.app_version", return_value="1.0.0"):
                with patch.object(app_entry, "_shutdown_remote_instance", return_value=True) as mock_shutdown:
                    with patch.object(app_entry, "_wait_for_port_release", return_value=True) as mock_wait:
                        with patch.dict("os.environ", {}, clear=True):
                            port, should_run = app_entry._resolve_server_port()
                            assert port == 52341
                            assert should_run is True
                            assert mock_shutdown.called
                            assert mock_wait.called


def test_save_server_info_writes_file(tmp_path):
    """_save_server_info saves port, host, url, and pid to server_info.json."""
    mock_runtime = MagicMock()
    mock_runtime.data_dir = tmp_path
    with patch("backend.runtime.resolve_runtime", return_value=mock_runtime):
        app_entry._save_server_info(8090, "127.0.0.1", "http://127.0.0.1:8090")
        info_file = tmp_path / "server_info.json"
        assert info_file.exists()
        data = json.loads(info_file.read_text(encoding="utf-8"))
        assert data["port"] == 8090
        assert data["host"] == "127.0.0.1"
        assert data["url"] == "http://127.0.0.1:8090"
        assert isinstance(data["pid"], int)
