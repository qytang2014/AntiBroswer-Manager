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


def test_pack_relativizes_profile_and_extension_paths(tmp_path: Path, monkeypatch):
    """Archiver.pack() must strip host machine absolute paths, writing portable relative paths."""
    data_dir = tmp_path / "my_host_data"
    data_dir.mkdir()

    class DummyRuntime:
        def __init__(self, d):
            self.data_dir = d

    monkeypatch.setattr("backend.backup.archiver.resolve_runtime", lambda: DummyRuntime(data_dir))
    monkeypatch.setattr("backend.backup.archiver.load_settings", lambda: {})

    db_path = data_dir / "profiles.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE profiles (
            id TEXT PRIMARY KEY,
            browser_type TEXT,
            user_data_dir TEXT,
            extension_paths TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE extensions (
            id TEXT PRIMARY KEY,
            path TEXT,
            browser_type TEXT
        )
    """)
    host_udd = str(data_dir / "profiles" / "camoufox" / "p1")
    host_ext_path = str(data_dir / "extensions" / "firefox" / "ext-1")
    conn.execute(
        "INSERT INTO profiles VALUES ('p1', 'camoufox', ?, ?)",
        (host_udd, json.dumps([host_ext_path])),
    )
    conn.execute(
        "INSERT INTO extensions VALUES ('ext-1', ?, 'camoufox')",
        (host_ext_path,),
    )
    conn.commit()
    conn.close()

    tar_dest = tmp_path / "portable_backup.tar.gz"
    archiver.pack(tar_dest)

    # Extract to target directory
    target_extract = tmp_path / "target_extract"
    archiver.unpack(tar_dest, target_extract)

    # Inspect the packaged database inside the archive
    chk_conn = sqlite3.connect(str(target_extract / "profiles.db"))
    chk_conn.row_factory = sqlite3.Row
    p_row = chk_conn.execute("SELECT * FROM profiles WHERE id = 'p1'").fetchone()
    # Path inside archive must be relative, not containing data_dir
    assert p_row["user_data_dir"] == "profiles/camoufox/p1"
    assert json.loads(p_row["extension_paths"]) == ["extensions/firefox/ext-1"]

    e_row = chk_conn.execute("SELECT * FROM extensions WHERE id = 'ext-1'").fetchone()
    assert e_row["path"] == "extensions/firefox/ext-1"
    chk_conn.close()


def test_relativize_staged_database_closes_connection(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    staged_db = tmp_path / "staged.db"

    conn = sqlite3.connect(str(staged_db))
    conn.execute("CREATE TABLE profiles (id TEXT, browser_type TEXT, user_data_dir TEXT, extension_paths TEXT)")
    conn.execute("INSERT INTO profiles VALUES ('p1', 'camoufox', ?, '[]')", (str(data_dir / "profiles" / "camoufox" / "p1"),))
    conn.commit()
    conn.close()

    real_connect = sqlite3.connect
    tracked_connections: list[object] = []

    class _ConnProxy:
        def __init__(self, wrapped: sqlite3.Connection):
            object.__setattr__(self, "_wrapped", wrapped)
            object.__setattr__(self, "closed", False)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        def __setattr__(self, name, value):
            if name in {"_wrapped", "closed"}:
                object.__setattr__(self, name, value)
                return
            setattr(self._wrapped, name, value)

        def close(self):
            self.closed = True
            return self._wrapped.close()

    def tracked_connect(*args, **kwargs):
        proxy = _ConnProxy(real_connect(*args, **kwargs))
        tracked_connections.append(proxy)
        return proxy

    monkeypatch.setattr(archiver.sqlite3, "connect", tracked_connect)
    archiver._relativize_staged_database(staged_db, data_dir)

    assert tracked_connections
    assert tracked_connections[0].closed is True
