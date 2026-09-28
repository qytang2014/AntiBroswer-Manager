"""Tests for automated backup scheduler and temporary directory cleanup."""

import asyncio
import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from backend.backup import credentials
from backend.backup.manager import BackupManager
from backend.backup.scheduler import run_backup_scheduler


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_scheduler_skips_when_encryption_password_missing(tmp_path: Path, monkeypatch):
    class DummyRuntime:
        def __init__(self, d):
            self.data_dir = d

    monkeypatch.setattr("backend.backup.manager.resolve_runtime", lambda: DummyRuntime(tmp_path))
    monkeypatch.setattr("backend.backup.credentials.resolve_runtime", lambda: DummyRuntime(tmp_path))

    mgr = BackupManager()
    mgr.create_backup = AsyncMock()

    settings = {
        "backup": {
            "backend": "webdav",
            "webdav_url": "https://example.com/dav",
            "auto_backup_interval_hours": 1,
            "encrypt_enabled": True,  # but no encrypt_password in credentials!
        }
    }
    monkeypatch.setattr("backend.backup.scheduler.load_settings", lambda: settings)

    # Run scheduler briefly
    task = asyncio.create_task(run_backup_scheduler(mgr, check_interval_seconds=0))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    # Should NOT have called create_backup
    assert not mgr.create_backup.called


@pytest.mark.anyio
async def test_scheduler_failure_backoff(tmp_path: Path, monkeypatch):
    class DummyRuntime:
        def __init__(self, d):
            self.data_dir = d

    monkeypatch.setattr("backend.backup.manager.resolve_runtime", lambda: DummyRuntime(tmp_path))
    monkeypatch.setattr("backend.backup.credentials.resolve_runtime", lambda: DummyRuntime(tmp_path))

    mgr = BackupManager()
    mgr.create_backup = AsyncMock()
    # Simulate a failure 2 minutes ago
    mgr.last_backup_error_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=2)

    settings = {
        "backup": {
            "backend": "webdav",
            "webdav_url": "https://example.com/dav",
            "auto_backup_interval_hours": 1,
            "encrypt_enabled": False,
        }
    }
    monkeypatch.setattr("backend.backup.scheduler.load_settings", lambda: settings)

    task = asyncio.create_task(run_backup_scheduler(mgr, check_interval_seconds=0))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    # Should NOT have called create_backup due to backoff
    assert not mgr.create_backup.called


def test_cleanup_stale_temp_dirs(tmp_path: Path, monkeypatch):
    class DummyRuntime:
        def __init__(self, d):
            self.data_dir = d

    monkeypatch.setattr("backend.backup.manager.resolve_runtime", lambda: DummyRuntime(tmp_path))

    # Create stale temporary directories in data_dir
    stale_1 = tmp_path / "_tmp_backup_abc123"
    stale_1.mkdir()
    (stale_1 / "leftover.tar.gz").write_text("data")

    stale_2 = tmp_path / "_tmp_restore_xyz789"
    stale_2.mkdir()
    (stale_2 / "staged.txt").write_text("data")

    legit_file = tmp_path / "profiles.db"
    legit_file.write_text("important")

    mgr = BackupManager()
    mgr.cleanup_stale_temp_dirs()

    # Stale tmp folders should be gone
    assert not stale_1.exists()
    assert not stale_2.exists()
    # Legitimate files must remain untouched
    assert legit_file.exists()
