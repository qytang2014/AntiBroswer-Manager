"""Tests for backup packaging and unpacking operations."""

import io
import json
import sqlite3
import tarfile
from pathlib import Path
import pytest

from backend.backup import archiver


def test_pack_and_unpack_roundtrip(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Mock runtime data_dir
    class DummyRuntime:
        def __init__(self, d):
            self.data_dir = d

    monkeypatch.setattr("backend.backup.archiver.resolve_runtime", lambda: DummyRuntime(data_dir))
    monkeypatch.setattr("backend.backup.archiver.load_settings", lambda: {"release_channel": "stable"})

    # Setup dummy database
    db_path = data_dir / "profiles.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE test_tab (id INT, val TEXT)")
    conn.execute("INSERT INTO test_tab VALUES (1, 'val1')")
    conn.commit()
    conn.close()

    # Setup dummy extensions
    ext_dir = data_dir / "extensions" / "chromium" / "ext1"
    ext_dir.mkdir(parents=True)
    (ext_dir / "manifest.json").write_text("{}", encoding="utf-8")

    # Pack
    tar_dest = tmp_path / "backup.tar.gz"
    manifest = archiver.pack(tar_dest, include_browser_state=False)

    assert tar_dest.exists()
    assert manifest["version"] == 1
    assert manifest["mode"] == "config"

    # Unpack to clean directory
    extract_dir = tmp_path / "extracted"
    extracted_manifest = archiver.unpack(tar_dest, extract_dir)

    assert extracted_manifest == manifest
    assert (extract_dir / "profiles.db").exists()
    assert (extract_dir / "settings.json").exists()
    assert (extract_dir / "extensions" / "chromium" / "ext1" / "manifest.json").exists()

    # Verify extracted database integrity
    chk_conn = sqlite3.connect(str(extract_dir / "profiles.db"))
    row = chk_conn.execute("SELECT val FROM test_tab WHERE id = 1").fetchone()
    chk_conn.close()
    assert row[0] == "val1"


def test_unpack_malicious_path_traversal_fails(tmp_path: Path):
    tar_path = tmp_path / "malicious.tar.gz"

    with tarfile.open(tar_path, "w:gz") as tar:
        # Create an entry attempting to write outside target dir
        info = tarfile.TarInfo(name="../escape.txt")
        data = b"malicious content"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    extract_dir = tmp_path / "safe_extract"
    with pytest.raises(ValueError, match="Malicious archive member detected"):
        archiver.unpack(tar_path, extract_dir)
