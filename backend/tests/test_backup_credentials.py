"""Tests for backup credentials storage and fallback mechanisms."""

from pathlib import Path
from backend.backup import credentials


def test_fallback_store_encryption_roundtrip(tmp_path: Path, monkeypatch):
    class DummyRuntime:
        def __init__(self, d):
            self.data_dir = d

    monkeypatch.setattr("backend.backup.credentials.resolve_runtime", lambda: DummyRuntime(tmp_path))

    store = {"webdav_password": "nas_password_123", "encrypt_password": "backup_pass_456"}
    credentials._save_fallback_store(store)

    loaded = credentials._load_fallback_store()
    assert loaded == store
    assert (tmp_path / ".backup_secrets.enc").exists()


def test_credential_helpers(tmp_path: Path, monkeypatch):
    class DummyRuntime:
        def __init__(self, d):
            self.data_dir = d

    monkeypatch.setattr("backend.backup.credentials.resolve_runtime", lambda: DummyRuntime(tmp_path))

    credentials.set_credential("test_backup_key", "secret_value_999")
    assert credentials.has_credential("test_backup_key")
    assert credentials.get_credential("test_backup_key") == "secret_value_999"

    credentials.delete_credential("test_backup_key")
    assert not credentials.has_credential("test_backup_key")
    assert credentials.get_credential("test_backup_key") is None
