import json
import sqlite3
import pytest
from pathlib import Path
from backend import database as db
from backend.backup import archiver


def test_canonicalize_extension_path(tmp_db: Path):
    ext_root = tmp_db / "extensions"

    # 1. Relative chromium path
    res = db.canonicalize_extension_path("extensions/chromium/my-ext-id", "cloakbrowser")
    assert res == str(ext_root / "chromium" / "my-ext-id")

    # 2. Relative firefox path
    res = db.canonicalize_extension_path("extensions/firefox/my-fox-id", "camoufox")
    assert res == str(ext_root / "firefox" / "my-fox-id")

    # 3. Legacy relative path without engine
    res_fox = db.canonicalize_extension_path("extensions/legacy-ext", "camoufox")
    assert res_fox == str(ext_root / "firefox" / "legacy-ext")

    res_chrome = db.canonicalize_extension_path("extensions/legacy-ext", "cloakbrowser")
    assert res_chrome == str(ext_root / "chromium" / "legacy-ext")

    # 4. Foreign macOS path
    foreign_mac = "/Users/alice/Library/Application Support/AntiBrowser-Manager/extensions/chromium/abc"
    assert db.canonicalize_extension_path(foreign_mac, "cloakbrowser") == str(ext_root / "chromium" / "abc")

    # 5. Foreign Windows path with backslashes
    foreign_win = r"C:\Users\Bob\AppData\Roaming\AntiBrowser-Manager\extensions\chromium\abc"
    assert db.canonicalize_extension_path(foreign_win, "cloakbrowser") == str(ext_root / "chromium" / "abc")

    # 6. Raw extension ID
    raw_id = "nngceckbapebfimnlniiiahkandclblb"
    assert db.canonicalize_extension_path(raw_id, "cloakbrowser") == str(ext_root / "chromium" / raw_id)


def test_realign_profile_paths_with_relative_and_foreign_extensions(tmp_db: Path):
    ext_root = tmp_db / "extensions"

    # Insert a profile with relativized and foreign extension paths
    pid = "prof-test-realign-unique-123"
    rel_path_1 = "extensions/chromium/ext-chrome-1"
    rel_path_2 = "extensions/chromium/ext-chrome-2"
    foreign_path = "/OldMachine/Home/Library/Application Support/AntiBrowser-Manager/extensions/chromium/ext-foreign"

    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO profiles (id, name, fingerprint_seed, browser_type, user_data_dir, extension_paths, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, "Profile Realign", 1234, "cloakbrowser", str(tmp_db / "profiles" / "cloakbrowser" / pid), json.dumps([rel_path_1, rel_path_2, foreign_path]), "2026-01-01", "2026-01-01"),
        )
        conn.execute(
            """INSERT INTO extensions (id, name, version, path, source, browser_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("ext-chrome-1", "Ext 1", "1.0", "extensions/chromium/ext-chrome-1", "upload", "cloakbrowser", "2026-01-01"),
        )
        conn.commit()

    # Verify that get_profile dynamically hydrates canonical paths
    hydrated = db.get_profile(pid)
    expected_1 = str(ext_root / "chromium" / "ext-chrome-1")
    expected_2 = str(ext_root / "chromium" / "ext-chrome-2")
    expected_foreign = str(ext_root / "chromium" / "ext-foreign")
    assert hydrated["extension_paths"] == [expected_1, expected_2, expected_foreign]

    # Run realign_profile_paths to test database persistence update
    realigned = db.realign_profile_paths()
    assert realigned >= 1

    # Check raw DB row to confirm persistent update
    with db.get_db() as conn:
        p_row = conn.execute("SELECT extension_paths FROM profiles WHERE id = ?", (pid,)).fetchone()
        stored_paths = json.loads(p_row["extension_paths"])
        assert stored_paths == [expected_1, expected_2, expected_foreign]

        e_row = conn.execute("SELECT path FROM extensions WHERE id = 'ext-chrome-1'").fetchone()
        assert e_row["path"] == expected_1


def test_backup_restore_extension_persistence_roundtrip(tmp_path, monkeypatch):
    data_dir_1 = tmp_path / "data_origin"
    data_dir_1.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db, "DATA_DIR", data_dir_1)
    monkeypatch.setattr(db, "DB_PATH", data_dir_1 / "profiles.db")
    db.init_db()

    # Create extension on disk and DB
    ext_dir = data_dir_1 / "extensions" / "chromium" / "ext-alpha"
    ext_dir.mkdir(parents=True, exist_ok=True)
    (ext_dir / "manifest.json").write_text('{"name": "Alpha", "version": "1.0"}', encoding="utf-8")

    db.create_extension(
        ext_id="ext-alpha",
        name="Alpha Extension",
        version="1.0",
        description="Test description",
        icon_url=None,
        path=str(ext_dir),
        source="upload",
        browser_type="cloakbrowser",
    )

    # Create profile with this extension
    prof = db.create_profile(
        name="Source Profile",
        fingerprint_seed=555,
        browser_type="cloakbrowser",
        extension_paths=[str(ext_dir)],
    )

    # Pack backup
    class DummyRuntime:
        def __init__(self, d):
            self.data_dir = d

    monkeypatch.setattr("backend.backup.archiver.resolve_runtime", lambda: DummyRuntime(data_dir_1))
    archive_file = tmp_path / "backup.tar.gz"
    manifest = archiver.pack(archive_file)
    assert manifest["version"] == 1

    # Now simulate restoring to a new data directory (e.g. new machine / location)
    data_dir_2 = tmp_path / "data_destination"
    data_dir_2.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db, "DATA_DIR", data_dir_2)
    monkeypatch.setattr(db, "DB_PATH", data_dir_2 / "profiles.db")

    staging_dir = tmp_path / "staging"
    archiver.unpack(archive_file, staging_dir)

    # Copy files as restore_backup does
    import shutil
    shutil.copy2(staging_dir / "profiles.db", data_dir_2 / "profiles.db")
    shutil.copytree(staging_dir / "extensions", data_dir_2 / "extensions", dirs_exist_ok=True)

    # Re-initialize DB and realign paths
    db.init_db()
    db.realign_profile_paths()

    # Verify profile has extension pointing to data_dir_2!
    restored_prof = db.get_profile(prof["id"])
    expected_new_path = str(data_dir_2 / "extensions" / "chromium" / "ext-alpha")
    assert restored_prof["extension_paths"] == [expected_new_path]

    # Verify extension row in destination
    restored_ext = db.get_extension("ext-alpha")
    assert restored_ext is not None
    assert restored_ext["path"] == expected_new_path
