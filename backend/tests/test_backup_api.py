"""Tests for Backup & Restore REST API routes."""

from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from starlette.testclient import TestClient

from backend import main


def test_backup_config_get_and_update(app_client: TestClient):
    # GET config default
    resp = app_client.get("/api/backup/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "backend" in data
    assert "encrypt_enabled" in data
    assert "auto_backup_interval_hours" in data

    # PUT config update
    payload = {
        "backend": "webdav",
        "webdav_url": "https://dav.example.com/dav",
        "webdav_username": "testuser",
        "webdav_password": "mypassword123",
        "encrypt_enabled": True,
        "encrypt_password": "encpassword456",
        "auto_backup_interval_hours": 24,
        "retain_count": 5,
    }
    update_resp = app_client.put("/api/backup/config", json=payload)
    assert update_resp.status_code == 200
    updated_data = update_resp.json()
    assert updated_data["backend"] == "webdav"
    assert updated_data["webdav_url"] == "https://dav.example.com/dav"
    assert updated_data["webdav_username"] == "testuser"
    assert updated_data["encrypt_enabled"] is True
    assert updated_data["encrypt_password_set"] is True
    assert updated_data["auto_backup_interval_hours"] == 24
    assert updated_data["retain_count"] == 5
    # Passwords must NEVER be returned in response!
    assert "webdav_password" not in updated_data
    assert "encrypt_password" not in updated_data


def test_backup_test_connection_endpoint(app_client: TestClient):
    with patch.object(main.backup_mgr, "test_connection", new_callable=AsyncMock) as mock_test:
        mock_test.return_value = (True, None)
        resp = app_client.post("/api/backup/test-connection", json={"backend": "webdav", "webdav_url": "http://127.0.0.1"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "error": None}

        mock_test.return_value = (False, "Auth failed")
        resp_err = app_client.post("/api/backup/test-connection", json={"backend": "webdav", "webdav_url": "http://127.0.0.1"})
        assert resp_err.status_code == 200
        assert resp_err.json() == {"ok": False, "error": "Auth failed"}


def test_backup_now_and_list_endpoints(app_client: TestClient):
    with patch.object(main.backup_mgr, "create_backup", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = "task-test-123"
        resp = app_client.post("/api/backup/now", json={"include_browser_state": False})
        assert resp.status_code == 200
        assert resp.json() == {"task_id": "task-test-123"}

    with patch.object(main.backup_mgr, "list_backups", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [
            {
                "name": "antibrowser-backup-20260925-120000-config.tar.gz.enc",
                "size_bytes": 10240,
                "created_at": "2026-09-25T12:00:00Z",
                "mode": "config",
                "encrypted": True,
                "checksum": "present",
            }
        ]
        list_resp = app_client.get("/api/backup/list")
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert len(items) == 1
        assert items[0]["name"] == "antibrowser-backup-20260925-120000-config.tar.gz.enc"
        assert items[0]["encrypted"] is True


def test_restore_fails_when_browsers_are_running(app_client: TestClient):
    # Simulate a running profile
    main.browser_mgr.running["test-prof-id"] = object()  # type: ignore
    try:
        resp = app_client.post("/api/backup/restore", json={"filename": "backup.tar.gz"})
        assert resp.status_code == 400
        assert "close all running profiles" in resp.json()["detail"].lower()
    finally:
        main.browser_mgr.running.clear()


@pytest.mark.asyncio
async def test_run_restore_success(tmp_path: Path, monkeypatch):
    import shutil
    import sqlite3
    from backend.backup import archiver

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    conn = sqlite3.connect(str(data_dir / "profiles.db"))
    conn.execute("CREATE TABLE test_tab (id INT, val TEXT)")
    conn.execute("INSERT INTO test_tab VALUES (1, 'val1')")
    conn.commit()
    conn.close()

    (data_dir / "settings.json").write_text("{}", encoding="utf-8")

    class DummyRuntime:
        def __init__(self, d):
            self.data_dir = d

    monkeypatch.setattr("backend.backup.manager.resolve_runtime", lambda: DummyRuntime(data_dir))
    monkeypatch.setattr("backend.backup.archiver.resolve_runtime", lambda: DummyRuntime(data_dir))
    monkeypatch.setattr("backend.settings_store.resolve_runtime", lambda: DummyRuntime(data_dir))
    monkeypatch.setattr("backend.database.DB_PATH", data_dir / "profiles.db")

    # Create a valid backup tarball
    backup_tar = tmp_path / "test_backup.tar.gz"
    archiver.pack(backup_tar, include_browser_state=False)

    class MockStorage:
        async def download_file(self, filename, local_path, progress_callback=None):
            if filename.endswith(".sha256"):
                raise FileNotFoundError("no sidecar")
            shutil.copy2(backup_tar, local_path)

    monkeypatch.setattr("backend.backup.manager.get_storage_backend", lambda cfg: MockStorage())

    events = []
    def mock_publish(task_id, ev):
        events.append(ev)

    monkeypatch.setattr(main.backup_mgr, "_publish_event", mock_publish)

    await main.backup_mgr._run_restore("task-restore-1", "test_backup.tar.gz", None)

    errors = [ev for ev in events if ev.get("stage") == "error"]
    assert not errors, f"Restore failed with error: {errors}"

    completed = [ev for ev in events if ev.get("stage") == "complete"]
    assert len(completed) == 1
    assert completed[0]["status"] == "completed"


def test_backup_env_var_fallback(tmp_path: Path, monkeypatch):
    class DummyRuntime:
        def __init__(self, d):
            self.data_dir = d

    monkeypatch.setattr("backend.backup.manager.resolve_runtime", lambda: DummyRuntime(tmp_path))
    monkeypatch.setattr("backend.settings_store.resolve_runtime", lambda: DummyRuntime(tmp_path))
    monkeypatch.setenv("ANTIBROWSER_BACKUP_BACKEND", "webdav")
    monkeypatch.setenv("ANTIBROWSER_BACKUP_WEBDAV_URL", "https://env-dav.example.com/dav")
    monkeypatch.setenv("ANTIBROWSER_BACKUP_WEBDAV_USERNAME", "env_user")

    cfg = main.backup_mgr.get_config()
    assert cfg["backend"] == "webdav"
    assert cfg["webdav_url"] == "https://env-dav.example.com/dav"
    assert cfg["webdav_username"] == "env_user"


def test_legacy_data_migration(tmp_path: Path):
    from backend.runtime import migrate_legacy_data_dir

    fake_home = tmp_path / "home"
    legacy_dir = fake_home / "Library" / "Application Support" / "CloakBrowser Manager"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "settings.json").write_text('{"backup": {"backend": "s3", "s3_bucket": "migrated-bucket"}}', encoding="utf-8")
    (legacy_dir / "profiles.db").write_text("fake db content", encoding="utf-8")

    target_dir = fake_home / "Library" / "Application Support" / "AntiBrowser-Manager"
    assert not target_dir.exists()

    migrate_legacy_data_dir(target_dir, host_os="macos", home=fake_home)
    assert (target_dir / "settings.json").exists()
    assert (target_dir / "profiles.db").exists()
    assert "migrated-bucket" in (target_dir / "settings.json").read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_restore_preserves_archive_backup_when_active_empty(tmp_path: Path, monkeypatch):
    import json, shutil, sqlite3
    from backend.backup import archiver

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    conn = sqlite3.connect(str(data_dir / "profiles.db"))
    conn.execute("CREATE TABLE test_tab (id INT)")
    conn.commit()
    conn.close()

    # The archive contains a configured WebDAV backup
    archived_settings = {"backup": {"backend": "webdav", "webdav_url": "https://archived-dav.com/dav"}}
    (data_dir / "settings.json").write_text(json.dumps(archived_settings), encoding="utf-8")

    class DummyRuntime:
        def __init__(self, d):
            self.data_dir = d

    monkeypatch.setattr("backend.backup.manager.resolve_runtime", lambda: DummyRuntime(data_dir))
    monkeypatch.setattr("backend.backup.archiver.resolve_runtime", lambda: DummyRuntime(data_dir))
    monkeypatch.setattr("backend.settings_store.resolve_runtime", lambda: DummyRuntime(data_dir))
    monkeypatch.setattr("backend.database.DB_PATH", data_dir / "profiles.db")

    backup_tar = tmp_path / "test_backup.tar.gz"
    archiver.pack(backup_tar, include_browser_state=False)

    # Now clear active settings to simulate fresh install or empty active backup
    (data_dir / "settings.json").write_text("{}", encoding="utf-8")

    class MockStorage:
        async def download_file(self, filename, local_path, progress_callback=None):
            if filename.endswith(".sha256"):
                raise FileNotFoundError("no sidecar")
            shutil.copy2(backup_tar, local_path)

    monkeypatch.setattr("backend.backup.manager.get_storage_backend", lambda cfg: MockStorage())
    monkeypatch.setattr(main.backup_mgr, "_publish_event", lambda tid, ev: None)

    await main.backup_mgr._run_restore("task-restore-empty", "test_backup.tar.gz", None)

    restored = json.loads((data_dir / "settings.json").read_text(encoding="utf-8"))
    assert "backup" in restored
    assert restored["backup"].get("backend") == "webdav"
    assert restored["backup"].get("webdav_url") == "https://archived-dav.com/dav"


def test_backup_status_endpoint(app_client, monkeypatch):
    """Verify GET /api/backup/status returns active task or idle state correctly."""
    # When no task is running
    res = app_client.get("/api/backup/status")
    assert res.status_code == 200
    data = res.json()
    assert data["active"] is False
    assert data["task"] is None

    # Simulate an active task
    main.backup_mgr._tasks["test-active-1"] = {
        "task_id": "test-active-1",
        "type": "backup",
        "stage": "archiving",
        "percent": 50,
        "message": "Archiving...",
        "status": "running",
        "error": None,
    }

    res_active = app_client.get("/api/backup/status")
    assert res_active.status_code == 200
    data_active = res_active.json()
    assert data_active["active"] is True
    assert data_active["task"]["task_id"] == "test-active-1"
    assert data_active["task"]["percent"] == 50

    # Cleanup test task
    main.backup_mgr._tasks.pop("test-active-1", None)

