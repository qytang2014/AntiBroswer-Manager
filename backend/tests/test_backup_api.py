"""Tests for Backup & Restore REST API routes."""

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
