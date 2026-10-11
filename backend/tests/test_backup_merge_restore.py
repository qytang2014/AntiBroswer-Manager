"""Tests for Lean State Backup and Incremental Merge Restore."""

import json
import sqlite3
import tarfile
import tempfile
from pathlib import Path

import pytest

from backend import database as db
from backend.backup import archiver
from backend.backup.manager import BackupManager


def test_lean_filter_pruning_and_preservation():
    """Verify _lean_filter excludes transient caches and locks while preserving core sessions."""
    # Test exclusions
    discard_paths = [
        "profiles/cloakbrowser/p1/Default/Cache/data_0",
        "profiles/cloakbrowser/p1/Default/Cache/Cache_Data/index",
        "profiles/cloakbrowser/p1/Default/Code Cache/js/index",
        "profiles/cloakbrowser/p1/Default/GPUCache/data_1",
        "profiles/cloakbrowser/p1/Default/GPUPersistentCache/index",
        "profiles/cloakbrowser/p1/Default/DawnGraphiteCache/data_0",
        "profiles/cloakbrowser/p1/Default/blob_storage/123",
        "profiles/cloakbrowser/p1/Default/Crashpad/attachments",
        "profiles/cloakbrowser/p1/Default/Service Worker/CacheStorage/abc",
        "profiles/cloakbrowser/p1/Default/Service Worker/ScriptCache/def",
        "profiles/cloakbrowser/p1/Default/BrowserMetrics-spare.pma",
        "profiles/cloakbrowser/p1/Default/SingletonLock",
        "profiles/camoufox/p2/cache2/entries/123",
        "profiles/camoufox/p2/startupCache/scriptLoaderCache.bin",
        "profiles/camoufox/p2/thumbnails/page1.png",
        "profiles/cloakbrowser/p1/Default/Favicons",
        "profiles/cloakbrowser/p1/Default/Favicons-journal",
        "profiles/camoufox/p2/favicons.sqlite",
        "profiles/camoufox/p2/favicons.sqlite-wal",
        "profiles/camoufox/p2/storage/default/moz-extension+++uBlock0/idb/12345.files/data",
    ]

    for p in discard_paths:
        ti = tarfile.TarInfo(p)
        assert archiver._lean_filter(ti) is None, f"Expected {p} to be pruned by _lean_filter"

    # Test preservation
    keep_paths = [
        "profiles/cloakbrowser/p1/Default/Cookies",
        "profiles/cloakbrowser/p1/Default/Cookies-wal",
        "profiles/cloakbrowser/p1/Default/Network/Cookies",
        "profiles/cloakbrowser/p1/Default/Local Storage/leveldb/000003.log",
        "profiles/cloakbrowser/p1/Default/Session Storage/000003.log",
        "profiles/cloakbrowser/p1/Default/IndexedDB/https_example.com_0.indexeddb.leveldb/000003.log",
        "profiles/cloakbrowser/p1/Default/Sessions/Session_1337",
        "profiles/cloakbrowser/p1/Default/Sessions/Tabs_1337",
        "profiles/cloakbrowser/p1/Default/History",
        "profiles/cloakbrowser/p1/Default/History-wal",
        "profiles/cloakbrowser/p1/Default/Login Data",
        "profiles/cloakbrowser/p1/Default/Web Data",
        "profiles/cloakbrowser/p1/Default/Preferences",
        "profiles/cloakbrowser/p1/Local State",
        "profiles/cloakbrowser/p1/last_screenshot.jpg",
        "profiles/camoufox/p2/cookies.sqlite",
        "profiles/camoufox/p2/cookies.sqlite-wal",
        "profiles/camoufox/p2/places.sqlite",
        "profiles/camoufox/p2/places.sqlite-wal",
        "profiles/camoufox/p2/webappsstore.sqlite",
        "profiles/camoufox/p2/sessionstore.jsonlz4",
        "profiles/camoufox/p2/sessionstore-backups/recovery.jsonlz4",
        "profiles/camoufox/p2/key4.db",
        "profiles/camoufox/p2/logins.db",
        "profiles/camoufox/p2/cert9.db",
        "profiles/camoufox/p2/prefs.js",
        "profiles/camoufox/p2/storage/default/https+++example.com/idb/000001.sqlite",
        "profiles/camoufox/p2/storage/default/moz-extension+++uBlock0/idb/12345.sqlite",
    ]

    for p in keep_paths:
        ti = tarfile.TarInfo(p)
        assert archiver._lean_filter(ti) is not None, f"Expected {p} to be preserved by _lean_filter"


def test_merge_from_staging_non_conflicting_profile(tmp_path, monkeypatch):
    """Verify merging a new profile from staging adds it without disturbing local profiles."""
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "profiles.db")
    db.init_db()

    # Create local profile
    p1 = db.create_profile("Local Profile 1", fingerprint_seed=11111)

    # Prepare staging area
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    staging_db_path = staging_dir / "profiles.db"

    s_conn = sqlite3.connect(str(staging_db_path))
    s_conn.execute(db._PROFILE_SCHEMA)
    db._create_tags_table(s_conn)
    s_conn.execute(
        """
        INSERT INTO profiles (id, name, fingerprint_seed, user_data_dir, created_at, updated_at, browser_type)
        VALUES ('staging-p2', 'Remote Profile 2', 22222, 'profiles/cloakbrowser/staging-p2', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'cloakbrowser')
        """
    )
    s_conn.commit()
    s_conn.close()

    # Create fake user data in staging
    staged_prof_dir = staging_dir / "profiles" / "cloakbrowser" / "staging-p2" / "Default"
    staged_prof_dir.mkdir(parents=True)
    (staged_prof_dir / "Cookies").write_text("cookie_data", encoding="utf-8")

    mgr = BackupManager()
    events = []
    mgr.merge_from_staging(
        staging_dir=staging_dir,
        data_dir=tmp_path,
        conflict_strategy="latest_wins",
        progress_cb=lambda pct, msg: events.append((pct, msg)),
        manifest={"includes_browser_state": True},
    )

    # Check profiles in local DB
    profiles = db.list_profiles()
    assert len(profiles) == 2
    ids = {p["id"] for p in profiles}
    assert p1["id"] in ids
    assert "staging-p2" in ids

    # Check physical file was copied
    dest_cookie = tmp_path / "profiles" / "cloakbrowser" / "staging-p2" / "Default" / "Cookies"
    assert dest_cookie.is_file()
    assert dest_cookie.read_text(encoding="utf-8") == "cookie_data"


def test_merge_from_staging_uuid_conflict_latest_wins(tmp_path, monkeypatch):
    """Verify conflict resolution: latest_wins overwrites when staging is newer."""
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "profiles.db")
    db.init_db()

    db.create_profile(
        "Local P1 Old",
        fingerprint_seed=11111,
        profile_id="shared-uuid",
    )
    with db.get_db() as conn:
        conn.execute("UPDATE profiles SET updated_at = '2025-01-01T00:00:00Z' WHERE id = 'shared-uuid'")
        conn.commit()

    # Staging has Profile 1 updated at 2026-02-01 (newer)
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    staging_db_path = staging_dir / "profiles.db"
    s_conn = sqlite3.connect(str(staging_db_path))
    s_conn.execute(db._PROFILE_SCHEMA)
    s_conn.execute(
        """
        INSERT INTO profiles (id, name, fingerprint_seed, user_data_dir, created_at, updated_at, browser_type)
        VALUES ('shared-uuid', 'Staged P1 Newer', 99999, 'profiles/cloakbrowser/shared-uuid', '2026-01-01T00:00:00Z', '2026-02-01T00:00:00Z', 'cloakbrowser')
        """
    )
    s_conn.commit()
    s_conn.close()

    mgr = BackupManager()
    mgr.merge_from_staging(
        staging_dir=staging_dir,
        data_dir=tmp_path,
        conflict_strategy="latest_wins",
        progress_cb=lambda pct, msg: None,
        manifest={},
    )

    profiles = db.list_profiles()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "Staged P1 Newer"
    assert profiles[0]["fingerprint_seed"] == 99999


def test_merge_from_staging_uuid_conflict_skip(tmp_path, monkeypatch):
    """Verify conflict resolution: skip retains local profile when UUID collides."""
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "profiles.db")
    db.init_db()

    db.create_profile(
        "Local P1 Keep",
        fingerprint_seed=11111,
        profile_id="shared-uuid",
        updated_at="2026-01-01T00:00:00Z",
    )

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    s_conn = sqlite3.connect(str(staging_dir / "profiles.db"))
    s_conn.execute(db._PROFILE_SCHEMA)
    s_conn.execute(
        """
        INSERT INTO profiles (id, name, fingerprint_seed, user_data_dir, created_at, updated_at, browser_type)
        VALUES ('shared-uuid', 'Staged P1 Skip', 99999, 'profiles/cloakbrowser/shared-uuid', '2026-01-01T00:00:00Z', '2026-05-01T00:00:00Z', 'cloakbrowser')
        """
    )
    s_conn.commit()
    s_conn.close()

    mgr = BackupManager()
    mgr.merge_from_staging(
        staging_dir=staging_dir,
        data_dir=tmp_path,
        conflict_strategy="skip",
        progress_cb=lambda pct, msg: None,
        manifest={},
    )

    profiles = db.list_profiles()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "Local P1 Keep"
    assert profiles[0]["fingerprint_seed"] == 11111


def test_merge_from_staging_uuid_conflict_keep_both(tmp_path, monkeypatch):
    """Verify conflict resolution: keep_both mints a new UUID and renames the imported copy."""
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "profiles.db")
    db.init_db()

    db.create_profile("Profile Original", fingerprint_seed=11111, profile_id="shared-uuid")

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    s_conn = sqlite3.connect(str(staging_dir / "profiles.db"))
    s_conn.execute(db._PROFILE_SCHEMA)
    s_conn.execute(
        """
        INSERT INTO profiles (id, name, fingerprint_seed, user_data_dir, created_at, updated_at, browser_type)
        VALUES ('shared-uuid', 'Profile Original', 22222, 'profiles/cloakbrowser/shared-uuid', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'cloakbrowser')
        """
    )
    s_conn.commit()
    s_conn.close()

    mgr = BackupManager()
    mgr.merge_from_staging(
        staging_dir=staging_dir,
        data_dir=tmp_path,
        conflict_strategy="keep_both",
        progress_cb=lambda pct, msg: None,
        manifest={},
    )

    profiles = db.list_profiles()
    assert len(profiles) == 2
    names = {p["name"] for p in profiles}
    assert "Profile Original" in names
    assert "Profile Original (来自备份)" in names


def test_merge_from_staging_name_collision_different_uuid(tmp_path, monkeypatch):
    """Verify when different UUIDs share the exact same name, imported one is renamed with suffix."""
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "profiles.db")
    db.init_db()

    db.create_profile("Google Account", fingerprint_seed=11111, profile_id="uuid-local")

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    s_conn = sqlite3.connect(str(staging_dir / "profiles.db"))
    s_conn.execute(db._PROFILE_SCHEMA)
    s_conn.execute(
        """
        INSERT INTO profiles (id, name, fingerprint_seed, user_data_dir, created_at, updated_at, browser_type)
        VALUES ('uuid-remote', 'Google Account', 33333, 'profiles/cloakbrowser/uuid-remote', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'cloakbrowser')
        """
    )
    s_conn.commit()
    s_conn.close()

    mgr = BackupManager()
    mgr.merge_from_staging(
        staging_dir=staging_dir,
        data_dir=tmp_path,
        conflict_strategy="latest_wins",
        progress_cb=lambda pct, msg: None,
        manifest={},
    )

    profiles = db.list_profiles()
    assert len(profiles) == 2
    by_id = {p["id"]: p["name"] for p in profiles}
    assert by_id["uuid-local"] == "Google Account"
    assert by_id["uuid-remote"] == "Google Account (来自备份)"


def test_merge_from_staging_license_union_and_id_remap(tmp_path, monkeypatch):
    """Verify license pool deduplication by key and remapping of profiles.license_id."""
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "profiles.db")
    db.init_db()

    # Settings mock
    settings_file = tmp_path / "settings.json"
    local_settings = {
        "licenses": [
            {
                "id": "loc-lic-1",
                "name": "旧别名",
                "key": "KEY-AAA-111",
                "is_default": True,
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ]
    }
    settings_file.write_text(json.dumps(local_settings), encoding="utf-8")

    from backend import settings_store
    monkeypatch.setattr(settings_store, "_settings_path", lambda: settings_file)

    # Staging settings has same key KEY-AAA-111 with different id and newer name, plus a new key KEY-BBB-222
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    staging_settings = {
        "licenses": [
            {
                "id": "staged-lic-1",
                "name": "最新重命名别名",
                "key": "KEY-AAA-111",
                "updated_at": "2026-02-01T00:00:00Z",
            },
            {
                "id": "staged-lic-2",
                "name": "全新机器B License",
                "key": "KEY-BBB-222",
                "updated_at": "2026-02-01T00:00:00Z",
            },
        ]
    }
    (staging_dir / "settings.json").write_text(json.dumps(staging_settings), encoding="utf-8")

    # Staging profiles referencing staged-lic-1 and staged-lic-2
    s_conn = sqlite3.connect(str(staging_dir / "profiles.db"))
    s_conn.execute(db._PROFILE_SCHEMA)
    s_conn.execute(
        """
        INSERT INTO profiles (id, name, fingerprint_seed, user_data_dir, created_at, updated_at, license_id, browser_type)
        VALUES 
        ('p-lic-1', 'Profile with Lic A', 100, 'profiles/cloakbrowser/p-lic-1', '2026-01-01', '2026-01-01', 'staged-lic-1', 'cloakbrowser'),
        ('p-lic-2', 'Profile with Lic B', 200, 'profiles/cloakbrowser/p-lic-2', '2026-01-01', '2026-01-01', 'staged-lic-2', 'cloakbrowser')
        """
    )
    s_conn.commit()
    s_conn.close()

    mgr = BackupManager()
    mgr.merge_from_staging(
        staging_dir=staging_dir,
        data_dir=tmp_path,
        conflict_strategy="latest_wins",
        progress_cb=lambda pct, msg: None,
        manifest={},
    )

    # Verify licenses merged in settings
    updated_settings = json.loads(settings_file.read_text(encoding="utf-8"))
    licenses = updated_settings["licenses"]
    assert len(licenses) == 2
    lic_a = next(lic for lic in licenses if lic["key"] == "KEY-AAA-111")
    lic_b = next(lic for lic in licenses if lic["key"] == "KEY-BBB-222")

    # KEY-AAA-111 kept its local id 'loc-lic-1' but adopted the newer name
    assert lic_a["id"] == "loc-lic-1"
    assert lic_a["name"] == "最新重命名别名"

    # Profiles in DB should have remapped license_id!
    profiles = {p["id"]: p for p in db.list_profiles()}
    assert profiles["p-lic-1"]["license_id"] == "loc-lic-1"  # Remapped to local ID!
    assert profiles["p-lic-2"]["license_id"] == lic_b["id"]


def test_pack_and_unpack_lean_state_end_to_end(tmp_path, monkeypatch):
    """Verify that pack with include_browser_state=True creates a session backup without cache files."""
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "profiles.db")
    db.init_db()

    p = db.create_profile("End2End Profile", fingerprint_seed=54321)
    pid = p["id"]

    # Populate dummy files in profile user_data_dir
    prof_dir = tmp_path / "profiles" / "cloakbrowser" / pid / "Default"
    cache_dir = prof_dir / "Cache"
    gpu_dir = prof_dir / "GPUCache"
    sw_cache = prof_dir / "Service Worker" / "CacheStorage"

    prof_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)
    gpu_dir.mkdir(parents=True)
    sw_cache.mkdir(parents=True)

    # Core session files (must be kept)
    (prof_dir / "Cookies").write_text("my_cookies", encoding="utf-8")
    (prof_dir / "History").write_text("my_history", encoding="utf-8")
    # Junk cache files (must be dropped)
    (cache_dir / "data_0").write_text("junk_cache", encoding="utf-8")
    (gpu_dir / "data_0").write_text("junk_gpu", encoding="utf-8")
    (sw_cache / "index").write_text("junk_sw", encoding="utf-8")
    (prof_dir / "SingletonLock").write_text("lock", encoding="utf-8")

    from backend import runtime
    class FakeRuntime:
        data_dir = tmp_path
    monkeypatch.setattr(runtime, "resolve_runtime", lambda: FakeRuntime())
    monkeypatch.setattr(archiver, "resolve_runtime", lambda: FakeRuntime())

    dest_tar = tmp_path / "backup.tar.gz"
    manifest = archiver.pack(dest_tar, include_browser_state=True)

    assert manifest["mode"] == "session"
    assert manifest["includes_browser_state"] is True

    # Unpack into target
    extracted_dir = tmp_path / "extracted"
    extracted_manifest = archiver.unpack(dest_tar, extracted_dir)
    assert extracted_manifest["mode"] == "session"

    extracted_prof = extracted_dir / "profiles" / "cloakbrowser" / pid / "Default"
    assert (extracted_prof / "Cookies").is_file()
    assert (extracted_prof / "Cookies").read_text(encoding="utf-8") == "my_cookies"
    assert (extracted_prof / "History").is_file()

    # Verify junk caches were completely excluded
    assert not (extracted_prof / "Cache").exists()
    assert not (extracted_prof / "GPUCache").exists()
    assert not (extracted_prof / "Service Worker" / "CacheStorage").exists()
    assert not (extracted_prof / "SingletonLock").exists()

