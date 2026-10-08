"""SQLite database operations for browser profiles."""

from __future__ import annotations

import datetime
import json
import logging
import random
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .runtime import resolve_runtime

logger = logging.getLogger("cloakbrowser.manager.database")

RUNTIME = resolve_runtime()
DATA_DIR = RUNTIME.data_dir
DB_PATH = DATA_DIR / "profiles.db"

_PROFILE_COLUMNS = (
    "id", "name", "fingerprint_seed", "proxy", "timezone", "locale",
    "screen_width", "screen_height", "gpu_family", "humanize", "human_preset",
    "geoip", "clipboard_sync", "auto_launch", "color_scheme", "launch_args",
    "extension_paths", "allow_3p_cookies", "set_google_default",
    "search_engine_name", "search_engine_keyword", "search_engine_url",
    "capture_preview", "restore_session", "browser_version", "browser_type", "notes", "user_data_dir",
    "created_at", "updated_at", "sort_order", "license_id",
    "cpu_cores", "memory_gb", "webgl_vendor", "webgl_renderer",
    "canvas_noise", "audio_noise", "do_not_track",
    "firefox_user_prefs", "extra_launch_args"
)

_PROFILE_SCHEMA = """
CREATE TABLE profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    fingerprint_seed INTEGER NOT NULL,
    proxy TEXT,
    timezone TEXT,
    locale TEXT,
    screen_width INTEGER DEFAULT 1920,
    screen_height INTEGER DEFAULT 1080,
    gpu_family TEXT NOT NULL DEFAULT 'auto',
    humanize BOOLEAN DEFAULT 0,
    human_preset TEXT DEFAULT 'default',
    geoip BOOLEAN DEFAULT 1,
    clipboard_sync BOOLEAN DEFAULT 1,
    auto_launch BOOLEAN DEFAULT 0,
    color_scheme TEXT,
    launch_args TEXT NOT NULL DEFAULT '[]',
    extension_paths TEXT NOT NULL DEFAULT '[]',
    allow_3p_cookies BOOLEAN DEFAULT 1,
    set_google_default BOOLEAN DEFAULT 1,
    search_engine_name TEXT,
    search_engine_keyword TEXT,
    search_engine_url TEXT,
    capture_preview BOOLEAN DEFAULT 1,
    restore_session BOOLEAN DEFAULT 1,
    browser_version TEXT,
    browser_type TEXT DEFAULT 'cloakbrowser',
    notes TEXT,
    user_data_dir TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    license_id TEXT,
    cpu_cores INTEGER DEFAULT NULL,
    memory_gb INTEGER DEFAULT NULL,
    webgl_vendor TEXT DEFAULT NULL,
    webgl_renderer TEXT DEFAULT NULL,
    canvas_noise BOOLEAN DEFAULT 1,
    audio_noise BOOLEAN DEFAULT 1,
    do_not_track BOOLEAN DEFAULT 0,
    firefox_user_prefs TEXT DEFAULT NULL,
    extra_launch_args TEXT DEFAULT NULL
)
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def _create_tags_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profile_tags (
            profile_id TEXT REFERENCES profiles(id) ON DELETE CASCADE,
            tag TEXT NOT NULL,
            color TEXT,
            PRIMARY KEY (profile_id, tag)
        )
    """)


def _rebuild_profiles(conn: sqlite3.Connection, old_columns: set[str]) -> None:
    """Rebuild the table in one transaction, retaining supported data and tags.

    SQLite cannot drop columns on older supported versions.  Copying tags through a
    temporary table avoids a foreign-key reference to the old parent table while it
    is replaced.
    """
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        has_tags = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_tags'"
        ).fetchone() is not None
        if has_tags:
            conn.execute("CREATE TEMP TABLE _profile_tags_backup AS SELECT * FROM profile_tags")
        conn.execute("DROP TABLE IF EXISTS profile_tags")
        conn.execute(_PROFILE_SCHEMA.replace("CREATE TABLE profiles", "CREATE TABLE profiles_new"))
        copied = [column for column in _PROFILE_COLUMNS if column in old_columns]
        if copied:
            cols = ", ".join(copied)
            conn.execute(f"INSERT INTO profiles_new ({cols}) SELECT {cols} FROM profiles")

        # Preserve the user's old broad GPU preference while discarding the
        # brittle free-text vendor/renderer fields. Explicit gpu_family values
        # from newer schemas always win.
        if "gpu_family" not in old_columns:
            legacy_gpu_parts = [
                column for column in ("gpu_vendor", "gpu_renderer")
                if column in old_columns
            ]
            if legacy_gpu_parts:
                expression = " || ' ' || ".join(
                    f"lower(coalesce({column}, ''))" for column in legacy_gpu_parts
                )
                conn.execute(
                    f"""
                    UPDATE profiles_new
                    SET gpu_family = CASE
                        WHEN id IN (SELECT id FROM profiles WHERE {expression} LIKE '%nvidia%') THEN 'nvidia'
                        WHEN id IN (SELECT id FROM profiles WHERE {expression} LIKE '%intel%') THEN 'intel'
                        ELSE 'auto'
                    END
                    """
                )
        if "license_id" not in old_columns:
            conn.execute("UPDATE profiles_new SET license_id = 'default-id'")

        conn.execute("DROP TABLE profiles")
        conn.execute("ALTER TABLE profiles_new RENAME TO profiles")
        _create_tags_table(conn)
        if has_tags:
            conn.execute("""
                INSERT OR IGNORE INTO profile_tags (profile_id, tag, color)
                SELECT profile_id, tag, color FROM _profile_tags_backup
            """)
        conn.execute("DROP TABLE IF EXISTS _profile_tags_backup")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _create_extensions_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS extensions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            description TEXT,
            icon_url TEXT,
            path TEXT NOT NULL,
            source TEXT NOT NULL,
            webstore_id TEXT,
            browser_type TEXT DEFAULT 'cloakbrowser',
            created_at TEXT NOT NULL
        )
    """)
    # Ensure browser_type exists for existing databases
    try:
        conn.execute("ALTER TABLE extensions ADD COLUMN browser_type TEXT DEFAULT 'cloakbrowser'")
    except sqlite3.OperationalError:
        pass


def _create_proxy_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            update_interval_hours INTEGER NOT NULL DEFAULT 0,
            last_updated_at TEXT,
            node_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proxy_nodes (
            id TEXT PRIMARY KEY,
            subscription_id TEXT REFERENCES subscriptions(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            protocol TEXT NOT NULL,
            raw_uri TEXT NOT NULL,
            parsed_config TEXT,
            last_latency_ms INTEGER,
            last_tested_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_proxy_nodes_sub_id ON proxy_nodes (subscription_id)")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profiles'").fetchone()
        if not exists:
            conn.execute(_PROFILE_SCHEMA)
            _create_tags_table(conn)
            _create_extensions_table(conn)
            _create_proxy_tables(conn)
            conn.commit()
            return
        old_columns = {row[1] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()}
        if old_columns != set(_PROFILE_COLUMNS):
            _rebuild_profiles(conn, old_columns)
        else:
            _create_tags_table(conn)
        _create_extensions_table(conn)
        _create_proxy_tables(conn)
        conn.commit()
    migrate_profiles_to_engine_subdirs()
    realign_profile_paths()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(value or "[]") if isinstance(value, str) else value or []
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except (TypeError, json.JSONDecodeError):
            return None
    return None


def new_profile_id() -> str:
    return str(uuid.uuid4())


def user_data_dir_for(profile_id: str, browser_type: str = "cloakbrowser") -> str:
    """Where a profile keeps its browser user data.

    Layout:
        profiles/cloakbrowser/{profile_id}  – CloakBrowser (Chromium)
        profiles/camoufox/{profile_id}      – Camoufox (Firefox)
    """
    engine_subdir = "camoufox" if browser_type == "camoufox" else "cloakbrowser"
    return str(DATA_DIR / "profiles" / engine_subdir / profile_id)


def create_profile(
    name: str, fingerprint_seed: int | None = None, *, profile_id: str | None = None, **fields: Any
) -> dict[str, Any]:
    """Insert a new profile. ``profile_id`` lets a caller mint the id (and so the
    user_data_dir) ahead of the row — used to fill a clone's directory BEFORE it
    becomes visible, so a half-built profile is never listed."""
    profile_id = profile_id or new_profile_id()
    seed = fingerprint_seed if fingerprint_seed is not None else random.randint(10000, 99999)
    browser_type = fields.get("browser_type", "cloakbrowser")
    user_data_dir = fields.get("user_data_dir") or user_data_dir_for(profile_id, browser_type)
    now = _now()
    tags = fields.pop("tags", None) or []
    values = {
        "id": profile_id, "name": name, "fingerprint_seed": seed,
        "proxy": fields.get("proxy"), "timezone": fields.get("timezone"), "locale": fields.get("locale"),
        "screen_width": fields.get("screen_width", 1920), "screen_height": fields.get("screen_height", 1080),
        "gpu_family": fields.get("gpu_family", "auto"), "humanize": fields.get("humanize", False),
        "human_preset": fields.get("human_preset", "default"), "geoip": fields.get("geoip", True),
        "clipboard_sync": fields.get("clipboard_sync", True), "auto_launch": fields.get("auto_launch", False),
        "color_scheme": fields.get("color_scheme"), "launch_args": json.dumps(fields.get("launch_args") or []),
        "extension_paths": json.dumps(fields.get("extension_paths") or []),
        "allow_3p_cookies": fields.get("allow_3p_cookies", True),
        "set_google_default": fields.get("set_google_default", True),
        "search_engine_name": fields.get("search_engine_name"),
        "search_engine_keyword": fields.get("search_engine_keyword"),
        "search_engine_url": fields.get("search_engine_url"),
        "capture_preview": fields.get("capture_preview", True),
        "restore_session": fields.get("restore_session", True),
        "browser_version": fields.get("browser_version"),
        "browser_type": fields.get("browser_type", "cloakbrowser"),
        "notes": fields.get("notes"),
        "license_id": fields.get("license_id"),
        "cpu_cores": fields.get("cpu_cores"),
        "memory_gb": fields.get("memory_gb"),
        "webgl_vendor": fields.get("webgl_vendor"),
        "webgl_renderer": fields.get("webgl_renderer"),
        "canvas_noise": 1 if fields.get("canvas_noise", False) else 0,
        "audio_noise": 1 if fields.get("audio_noise", True) else 0,
        "do_not_track": 1 if fields.get("do_not_track", False) else 0,
        "firefox_user_prefs": json.dumps(fields.get("firefox_user_prefs")) if fields.get("firefox_user_prefs") is not None else None,
        "extra_launch_args": json.dumps(fields.get("extra_launch_args")) if fields.get("extra_launch_args") is not None else None,
        "user_data_dir": user_data_dir, "created_at": now, "updated_at": now,
    }
    with get_db() as conn:
        # New profiles land on top of the manual order (smallest sort_order).
        min_order = conn.execute("SELECT MIN(sort_order) FROM profiles").fetchone()[0]
        values["sort_order"] = (min_order - 1) if min_order is not None else 0
        cols = ", ".join(_PROFILE_COLUMNS)
        placeholders = ", ".join("?" for _ in _PROFILE_COLUMNS)
        conn.execute(
            f"INSERT INTO profiles ({cols}) VALUES ({placeholders})",
            [values[column] for column in _PROFILE_COLUMNS],
        )
        for tag in tags:
            conn.execute(
                "INSERT INTO profile_tags (profile_id, tag, color) VALUES (?, ?, ?)",
                (profile_id, tag["tag"], tag.get("color")),
            )
        conn.commit()

    profile = get_profile(profile_id)
    if profile is None:
        raise RuntimeError(f"Created profile {profile_id} could not be reloaded")
    return profile


def canonicalize_extension_path(ep: str, browser_type: str | None = None) -> str:
    """Resolve an extension path, relative path, or legacy foreign path to the canonical absolute path."""
    if not ep or not isinstance(ep, str):
        return ep
    extensions_root = DATA_DIR / "extensions"
    default_engine = "firefox" if (browser_type or "").lower() == "camoufox" else "chromium"

    norm_ep = ep.replace("\\", "/")

    # 1. Relative path from backup archive (e.g. "extensions/chromium/{ext_id}" or "extensions/firefox/{ext_id}")
    if norm_ep.startswith("extensions/"):
        sub = norm_ep[len("extensions/"):].strip("/")
        parts = [p for p in sub.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("chromium", "firefox"):
            return str(extensions_root / parts[0] / parts[1])
        elif len(parts) >= 1 and parts[0]:
            return str(extensions_root / default_engine / parts[0])

    # 2. Path already starting with current DATA_DIR
    data_dir_str = str(DATA_DIR).replace("\\", "/")
    if norm_ep.startswith(data_dir_str):
        # Check if legacy layout extensions/{ext_id} without engine
        rel_to_data = norm_ep[len(data_dir_str):].strip("/")
        if rel_to_data.startswith("extensions/"):
            sub = rel_to_data[len("extensions/"):].strip("/")
            parts = [p for p in sub.split("/") if p]
            if len(parts) == 1 and parts[0]:
                cand = extensions_root / default_engine / parts[0]
                if cand.exists():
                    return str(cand)
        return str(Path(ep))

    # 3. Foreign absolute path from another machine (contains /extensions/chromium/ or /extensions/firefox/)
    if "/extensions/chromium/" in norm_ep:
        ext_id = norm_ep.split("/extensions/chromium/", 1)[1].strip("/").split("/")[0]
        return str(extensions_root / "chromium" / ext_id)
    if "/extensions/firefox/" in norm_ep:
        ext_id = norm_ep.split("/extensions/firefox/", 1)[1].strip("/").split("/")[0]
        return str(extensions_root / "firefox" / ext_id)

    # 4. Raw extension ID (no slashes and length >= 8)
    if "/" not in norm_ep and "\\" not in norm_ep and "." not in norm_ep and len(norm_ep) >= 8:
        return str(extensions_root / default_engine / norm_ep)

    return ep


def _hydrate_profile(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    profile = dict(row)
    btype = profile.get("browser_type") or "cloakbrowser"
    canonical_udd = user_data_dir_for(profile["id"], btype)
    stored_udd = profile.get("user_data_dir")
    if not stored_udd:
        profile["user_data_dir"] = canonical_udd
    else:
        try:
            if not str(stored_udd).startswith(str(DATA_DIR)) and not Path(stored_udd).is_dir():
                profile["user_data_dir"] = canonical_udd
        except Exception:
            profile["user_data_dir"] = canonical_udd

    profile["launch_args"] = _json_list(profile.get("launch_args"))
    raw_exts = _json_list(profile.get("extension_paths"))
    profile["extension_paths"] = [
        canonicalize_extension_path(ep, btype) for ep in raw_exts if isinstance(ep, str)
    ]

    profile["firefox_user_prefs"] = _json_dict(profile.get("firefox_user_prefs"))
    profile["extra_launch_args"] = _json_dict(profile.get("extra_launch_args"))
    profile["canvas_noise"] = bool(profile.get("canvas_noise", 0)) if profile.get("canvas_noise") is not None else False
    profile["audio_noise"] = bool(profile.get("audio_noise", 1)) if profile.get("audio_noise") is not None else True
    profile["do_not_track"] = bool(profile.get("do_not_track", 0)) if profile.get("do_not_track") is not None else False
    tags = conn.execute(
        "SELECT tag, color FROM profile_tags WHERE profile_id = ?",
        (profile["id"],),
    ).fetchall()
    profile["tags"] = [dict(tag) for tag in tags]
    return profile


def get_profile(profile_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        return _hydrate_profile(conn, row) if row else None


def list_profiles() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM profiles ORDER BY sort_order ASC, created_at DESC"
        ).fetchall()
        return [_hydrate_profile(conn, row) for row in rows]


def reorder_profiles(ordered_ids: list[str]) -> None:
    """Persist a manual profile order: sort_order = position in ordered_ids."""
    with get_db() as conn:
        conn.executemany(
            "UPDATE profiles SET sort_order = ? WHERE id = ?",
            [(index, profile_id) for index, profile_id in enumerate(ordered_ids)],
        )
        conn.commit()


def update_profile(profile_id: str, **fields: Any) -> dict[str, Any] | None:
    current = get_profile(profile_id)
    if not current:
        return None
    tags = fields.pop("tags", None)
    for key in ("launch_args", "extension_paths"):
        if key in fields:
            fields[key] = json.dumps(fields[key] or [])
    for key in ("firefox_user_prefs", "extra_launch_args"):
        if key in fields:
            fields[key] = json.dumps(fields[key]) if fields[key] is not None else None
    for key in ("canvas_noise", "audio_noise", "do_not_track"):
        if key in fields and fields[key] is not None:
            fields[key] = 1 if fields[key] else 0

    # If browser_type is changed, move on-disk directory to the new engine subdir
    new_browser_type = fields.get("browser_type")
    if new_browser_type and new_browser_type != current.get("browser_type"):
        old_udd = Path(current["user_data_dir"])
        new_udd = Path(user_data_dir_for(profile_id, new_browser_type))
        if old_udd != new_udd and old_udd.exists():
            new_udd.parent.mkdir(parents=True, exist_ok=True)
            if not new_udd.exists():
                try:
                    shutil.move(str(old_udd), str(new_udd))
                    fields["user_data_dir"] = str(new_udd)
                except Exception as exc:
                    logger.warning("Failed to move user_data_dir on browser_type update: %s", exc)

    update_cols = []
    update_vals = []
    for col in _PROFILE_COLUMNS:
        if col not in {"id", "created_at", "updated_at"} and col in fields:
            # Prevent arbitrary user_data_dir changes unless explicitly moved above
            if col == "user_data_dir" and "user_data_dir" not in fields:
                continue
            update_cols.append(f"{col} = ?")
            update_vals.append(fields[col])
    with get_db() as conn:
        if update_cols:
            conn.execute(
                f"UPDATE profiles SET {', '.join(update_cols)}, updated_at = ? WHERE id = ?",
                [*update_vals, _now(), profile_id],
            )
        if tags is not None:
            conn.execute("DELETE FROM profile_tags WHERE profile_id = ?", (profile_id,))
            for tag in tags:
                conn.execute(
                    "INSERT INTO profile_tags (profile_id, tag, color) VALUES (?, ?, ?)",
                    (profile_id, tag["tag"], tag.get("color")),
                )
        conn.commit()
    return get_profile(profile_id)


def migrate_profiles_to_engine_subdirs() -> None:
    """One-time migration: move profiles from flat 'profiles/' to engine-specific subdirs.

    Old layout:  profiles/{profile_id}/
    New layout:  profiles/cloakbrowser/{profile_id}/   (CloakBrowser)
                 profiles/camoufox/{profile_id}/        (Camoufox)

    The database ``user_data_dir`` column is updated in-place for every moved profile.
    Profiles whose on-disk path is already inside a sub-directory are skipped.
    """
    profiles = list_profiles()
    moved = 0
    profiles_root = DATA_DIR / "profiles"
    for profile in profiles:
        raw_udd = profile.get("user_data_dir")
        if not raw_udd:
            continue
        old_path = Path(raw_udd)
        if not old_path.is_dir():
            continue

        # If already migrated (parent is 'cloakbrowser' or 'camoufox'), skip
        if old_path.parent.name in ("cloakbrowser", "camoufox"):
            continue

        browser_type = profile.get("browser_type") or "cloakbrowser"
        engine_subdir = "camoufox" if browser_type == "camoufox" else "cloakbrowser"
        new_parent = profiles_root / engine_subdir
        new_parent.mkdir(parents=True, exist_ok=True)
        new_path = new_parent / old_path.name

        if new_path == old_path:
            continue

        try:
            if not new_path.exists():
                shutil.move(str(old_path), str(new_path))
            else:
                # Target already occupied, do not overwrite
                pass

            with get_db() as conn:
                conn.execute(
                    "UPDATE profiles SET user_data_dir = ? WHERE id = ?",
                    (str(new_path), profile["id"]),
                )
                conn.commit()
            moved += 1
            logger.info("Migrated profile %s: %s → %s", profile["id"], old_path, new_path)
        except Exception as exc:
            logger.warning("Failed to migrate profile %s (%s → %s): %s", profile["id"], old_path, new_path, exc)

    if moved:
        logger.info("Profile directory migration complete: %d profile(s) moved.", moved)


def realign_profile_paths() -> int:
    """Rebase profile user_data_dir, extension_paths, and extensions table paths
    to the current host environment's DATA_DIR.

    This ensures that database backups restored across different hosts, operating
    systems, usernames, or Docker containers seamlessly match the current host.
    """
    extensions_root = DATA_DIR / "extensions"
    realigned_count = 0

    with get_db() as conn:
        rows = conn.execute("SELECT id, browser_type, user_data_dir, extension_paths FROM profiles").fetchall()
        for row in rows:
            pid = row["id"]
            btype = row["browser_type"] or "cloakbrowser"
            canonical_udd = user_data_dir_for(pid, btype)
            current_udd = row["user_data_dir"]

            if current_udd != canonical_udd:
                if current_udd:
                    try:
                        old_p = Path(current_udd)
                        if old_p.is_dir() and not Path(canonical_udd).exists():
                            Path(canonical_udd).parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(old_p), canonical_udd)
                    except Exception as exc:
                        logger.debug("Failed moving profile dir %s -> %s: %s", current_udd, canonical_udd, exc)

                conn.execute(
                    "UPDATE profiles SET user_data_dir = ? WHERE id = ?",
                    (canonical_udd, pid),
                )
                realigned_count += 1

            ext_paths_raw = row["extension_paths"]
            if ext_paths_raw:
                try:
                    paths = json.loads(ext_paths_raw)
                    if isinstance(paths, list):
                        updated_paths = [
                            canonicalize_extension_path(ep, btype) for ep in paths if isinstance(ep, str)
                        ]
                        if updated_paths != paths:
                            conn.execute(
                                "UPDATE profiles SET extension_paths = ? WHERE id = ?",
                                (json.dumps(updated_paths), pid),
                            )
                            realigned_count += 1
                except Exception as exc:
                    logger.debug("Failed to rebase extension_paths for profile %s: %s", pid, exc)

        try:
            ext_rows = conn.execute("SELECT id, path, browser_type FROM extensions").fetchall()
            for erow in ext_rows:
                eid = erow["id"]
                btype = erow["browser_type"] or "cloakbrowser"
                subdir = "firefox" if btype == "camoufox" else "chromium"
                canonical_ext_path = str(extensions_root / subdir / eid)
                if erow["path"] != canonical_ext_path:
                    conn.execute(
                        "UPDATE extensions SET path = ? WHERE id = ?",
                        (canonical_ext_path, eid),
                    )
        except sqlite3.OperationalError:
            pass

        conn.commit()

    if realigned_count:
        logger.info("Realigned %d profile path(s) to current data directory %s", realigned_count, DATA_DIR)
    return realigned_count


def delete_profile(profile_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        conn.commit()
        return cursor.rowcount > 0


def reset_profile(profile_id: str) -> dict[str, Any] | None:
    """Re-roll fingerprint_seed and bump updated_at. Returns the updated profile or None.

    A fresh seed is the point of a reset: the profile keeps its config (name,
    proxy, locale, tags) but takes on a new identity. Seed range mirrors
    create_profile.
    """
    if not get_profile(profile_id):
        return None
    with get_db() as conn:
        conn.execute(
            "UPDATE profiles SET fingerprint_seed = ?, updated_at = ? WHERE id = ?",
            (random.randint(10000, 99999), _now(), profile_id),
        )
        conn.commit()
    return get_profile(profile_id)


def duplicate_profile(profile_id: str, *, new_id: str | None = None) -> dict[str, Any] | None:
    """Clone a profile's config into a brand-new profile. Returns it or None.

    Config-only clone: every setting, the tags, notes, and the SAME
    fingerprint_seed are carried over, but no on-disk browser state is copied.
    create_profile mints a fresh uuid, user_data_dir and sort_order (or takes
    ``new_id``), so the clone launches with an empty profile dir built fresh on
    first use — unless the caller filled that dir beforehand.
    """
    src = get_profile(profile_id)
    if src is None:
        return None
    fields = {
        key: value
        for key, value in src.items()
        if key not in {"id", "name", "fingerprint_seed", "tags",
                       "user_data_dir", "created_at", "updated_at", "sort_order"}
    }
    return create_profile(
        name=f"{src['name']} (copy)",
        fingerprint_seed=src["fingerprint_seed"],
        profile_id=new_id,
        tags=src.get("tags"),
        **fields,
    )


def list_extensions(browser_type: str | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        if browser_type:
            rows = conn.execute("SELECT * FROM extensions WHERE browser_type = ? ORDER BY created_at DESC", (browser_type,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM extensions ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


def get_extension(ext_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM extensions WHERE id = ?", (ext_id,)).fetchone()
        return dict(row) if row else None


def create_extension(
    ext_id: str,
    name: str,
    version: str,
    description: str | None,
    icon_url: str | None,
    path: str,
    source: str,
    webstore_id: str | None = None,
    browser_type: str = "cloakbrowser",
) -> dict[str, Any]:
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO extensions
            (id, name, version, description, icon_url, path, source, webstore_id, browser_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ext_id, name, version, description, icon_url, path, source, webstore_id, browser_type, _now()),
        )
        conn.commit()
    return get_extension(ext_id)  # type: ignore


def delete_extension(ext_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM extensions WHERE id = ?", (ext_id,))
        conn.commit()
        return cursor.rowcount > 0


def update_extension_path(ext_id: str, new_path: str) -> bool:
    """Update on-disk storage path of an extension."""
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE extensions SET path = ? WHERE id = ?",
            (new_path, ext_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def replace_profile_extension_path(old_path: str, new_path: str) -> int:
    """Replace an extension path in all profiles that reference old_path."""
    updated_count = 0
    with get_db() as conn:
        rows = conn.execute("SELECT id, extension_paths FROM profiles").fetchall()
        for row in rows:
            profile_id = row["id"]
            raw_paths = row["extension_paths"]
            try:
                paths = json.loads(raw_paths) if raw_paths else []
            except Exception:
                paths = []
            if old_path in paths:
                new_paths = [new_path if p == old_path else p for p in paths]
                conn.execute(
                    "UPDATE profiles SET extension_paths = ? WHERE id = ?",
                    (json.dumps(new_paths), profile_id),
                )
                updated_count += 1
        conn.commit()
    return updated_count


# ---------------------------------------------------------------------------
# Subscriptions and Proxy Nodes CRUD
# ---------------------------------------------------------------------------

def list_subscriptions() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM subscriptions ORDER BY created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_subscription(sub_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE id = ?", (sub_id,)
        ).fetchone()
        return dict(row) if row else None


def create_subscription(
    name: str,
    url: str,
    update_interval_hours: int = 0,
    sub_id: str | None = None,
) -> dict[str, Any]:
    sid = sub_id or uuid.uuid4().hex[:12]
    now = _now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO subscriptions
            (id, name, url, update_interval_hours, last_updated_at, node_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (sid, name, url, update_interval_hours, None, now, now),
        )
        conn.commit()
    return get_subscription(sid)  # type: ignore


def update_subscription(
    sub_id: str,
    *,
    name: str | None = None,
    url: str | None = None,
    update_interval_hours: int | None = None,
    last_updated_at: str | None = None,
    node_count: int | None = None,
) -> dict[str, Any] | None:
    current = get_subscription(sub_id)
    if not current:
        return None

    fields: list[str] = []
    values: list[Any] = []

    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if url is not None:
        fields.append("url = ?")
        values.append(url)
    if update_interval_hours is not None:
        fields.append("update_interval_hours = ?")
        values.append(update_interval_hours)
    if last_updated_at is not None:
        fields.append("last_updated_at = ?")
        values.append(last_updated_at)
    if node_count is not None:
        fields.append("node_count = ?")
        values.append(node_count)

    fields.append("updated_at = ?")
    values.append(_now())
    values.append(sub_id)

    with get_db() as conn:
        conn.execute(
            f"UPDATE subscriptions SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        conn.commit()
    return get_subscription(sub_id)


def delete_subscription(sub_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
        conn.commit()
        return cursor.rowcount > 0


def list_proxy_nodes(
    subscription_id: str | None = None,
    manual_only: bool = False,
) -> list[dict[str, Any]]:
    with get_db() as conn:
        if manual_only:
            rows = conn.execute(
                "SELECT * FROM proxy_nodes WHERE subscription_id IS NULL ORDER BY created_at DESC"
            ).fetchall()
        elif subscription_id is not None:
            rows = conn.execute(
                "SELECT * FROM proxy_nodes WHERE subscription_id = ? ORDER BY created_at ASC",
                (subscription_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM proxy_nodes ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]


def get_proxy_node(node_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM proxy_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return dict(row) if row else None


def create_proxy_node(
    name: str,
    protocol: str,
    raw_uri: str,
    subscription_id: str | None = None,
    parsed_config: str | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    nid = node_id or uuid.uuid4().hex[:12]
    now = _now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO proxy_nodes
            (id, subscription_id, name, protocol, raw_uri, parsed_config, last_latency_ms, last_tested_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (nid, subscription_id, name, protocol, raw_uri, parsed_config, now, now),
        )
        if subscription_id:
            conn.execute(
                "UPDATE subscriptions SET node_count = (SELECT count(*) FROM proxy_nodes WHERE subscription_id = ?), updated_at = ? WHERE id = ?",
                (subscription_id, now, subscription_id),
            )
        conn.commit()
    return get_proxy_node(nid)  # type: ignore


def batch_create_proxy_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert multiple proxy nodes in a single transaction."""
    if not nodes:
        return []
    now = _now()
    sub_ids: set[str] = set()
    result_ids: list[str] = []

    with get_db() as conn:
        for node in nodes:
            nid = node.get("id") or uuid.uuid4().hex[:12]
            result_ids.append(nid)
            sub_id = node.get("subscription_id")
            if sub_id:
                sub_ids.add(sub_id)
            conn.execute(
                """
                INSERT INTO proxy_nodes
                (id, subscription_id, name, protocol, raw_uri, parsed_config, last_latency_ms, last_tested_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    nid,
                    sub_id,
                    node["name"],
                    node["protocol"],
                    node["raw_uri"],
                    node.get("parsed_config"),
                    now,
                    now,
                ),
            )
        for sub_id in sub_ids:
            conn.execute(
                "UPDATE subscriptions SET node_count = (SELECT count(*) FROM proxy_nodes WHERE subscription_id = ?), updated_at = ? WHERE id = ?",
                (sub_id, now, sub_id),
            )
        conn.commit()

    with get_db() as conn:
        placeholders = ",".join("?" for _ in result_ids)
        rows = conn.execute(
            f"SELECT * FROM proxy_nodes WHERE id IN ({placeholders})", result_ids
        ).fetchall()
        return [dict(row) for row in rows]


def update_proxy_node(
    node_id: str,
    name: str | None = None,
    protocol: str | None = None,
    raw_uri: str | None = None,
    parsed_config: str | None = None,
) -> dict[str, Any] | None:
    updates: list[str] = []
    params: list[Any] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if protocol is not None:
        updates.append("protocol = ?")
        params.append(protocol)
    if raw_uri is not None:
        updates.append("raw_uri = ?")
        params.append(raw_uri)
    if parsed_config is not None:
        updates.append("parsed_config = ?")
        params.append(parsed_config)

    if not updates:
        return get_proxy_node(node_id)

    updates.append("updated_at = ?")
    params.append(_now())
    params.append(node_id)

    with get_db() as conn:
        cursor = conn.execute(
            f"UPDATE proxy_nodes SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
    return get_proxy_node(node_id)


def update_proxy_node_latency(node_id: str, latency_ms: int | None) -> bool:
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE proxy_nodes SET last_latency_ms = ?, last_tested_at = ?, updated_at = ? WHERE id = ?",
            (latency_ms, _now(), _now(), node_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_proxy_node(node_id: str) -> bool:
    with get_db() as conn:
        node = conn.execute("SELECT subscription_id FROM proxy_nodes WHERE id = ?", (node_id,)).fetchone()
        if not node:
            return False
        sub_id = node["subscription_id"]
        cursor = conn.execute("DELETE FROM proxy_nodes WHERE id = ?", (node_id,))
        if sub_id:
            conn.execute(
                "UPDATE subscriptions SET node_count = (SELECT count(*) FROM proxy_nodes WHERE subscription_id = ?), updated_at = ? WHERE id = ?",
                (sub_id, _now(), sub_id),
            )
        conn.commit()
        return cursor.rowcount > 0


def delete_nodes_by_subscription(sub_id: str) -> int:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM proxy_nodes WHERE subscription_id = ?", (sub_id,))
        conn.execute(
            "UPDATE subscriptions SET node_count = 0, updated_at = ? WHERE id = ?",
            (_now(), sub_id),
        )
        conn.commit()
        return cursor.rowcount


