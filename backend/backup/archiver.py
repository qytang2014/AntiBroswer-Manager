"""Archive packing and unpacking operations for AntiBrowser-Manager.

Creates and extracts `.tar.gz` backup bundles, utilizing SQLite online hot backup
to ensure transactional database consistency without interrupting browser operations.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Callable

from ..runtime import resolve_runtime
from ..settings_store import load_settings

logger = logging.getLogger("cloakbrowser.manager.backup.archiver")

MANIFEST_VERSION = 1


def _is_safe_tar_member(member: tarfile.TarInfo, target_dir: Path) -> bool:
    """Protect against zip slip / directory traversal attacks."""
    resolved_target = target_dir.resolve()
    resolved_dest = (target_dir / member.name).resolve()
    try:
        resolved_dest.relative_to(resolved_target)
        return True
    except ValueError:
        return False


def _relativize_staged_database(staged_db_path: Path, host_data_dir: Path) -> None:
    """Strip host-specific absolute data_dir prefixes from the staged database
    before packaging, making the backup archive completely portable across machines.
    """
    host_str = str(host_data_dir)
    conn = sqlite3.connect(str(staged_db_path))
    try:
        conn.row_factory = sqlite3.Row
        # 1. Relativize profiles.user_data_dir and extension_paths
        has_profiles = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='profiles'"
        ).fetchone() is not None
        if has_profiles:
            rows = conn.execute("SELECT id, browser_type, user_data_dir, extension_paths FROM profiles").fetchall()
            for row in rows:
                pid = row["id"]
                btype = row["browser_type"] or "cloakbrowser"
                engine_subdir = "camoufox" if btype == "camoufox" else "cloakbrowser"
                portable_udd = f"profiles/{engine_subdir}/{pid}"

                ext_paths_raw = row["extension_paths"]
                portable_ext_paths = None
                if ext_paths_raw:
                    try:
                        paths = json.loads(ext_paths_raw)
                        if isinstance(paths, list):
                            portable_list = []
                            for ep in paths:
                                if isinstance(ep, str):
                                    if ep.startswith(host_str):
                                        rel = os.path.relpath(ep, host_str)
                                        portable_list.append(rel.replace("\\", "/"))
                                    elif "/extensions/" in ep or "\\extensions\\" in ep:
                                        ep_p = Path(ep)
                                        eng = ep_p.parent.name
                                        eid = ep_p.name
                                        if eng in ("firefox", "chromium"):
                                            portable_list.append(f"extensions/{eng}/{eid}")
                                        else:
                                            portable_list.append(f"extensions/{eid}")
                                    else:
                                        portable_list.append(ep)
                            portable_ext_paths = json.dumps(portable_list)
                    except Exception:
                        pass

                if portable_ext_paths is not None:
                    conn.execute(
                        "UPDATE profiles SET user_data_dir = ?, extension_paths = ? WHERE id = ?",
                        (portable_udd, portable_ext_paths, pid),
                    )
                else:
                    conn.execute(
                        "UPDATE profiles SET user_data_dir = ? WHERE id = ?",
                        (portable_udd, pid),
                    )

        # 2. Relativize extensions table if present
        has_exts = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='extensions'"
        ).fetchone() is not None
        if has_exts:
            try:
                ext_rows = conn.execute("SELECT id, path, browser_type FROM extensions").fetchall()
                for erow in ext_rows:
                    eid = erow["id"]
                    btype = erow["browser_type"] or "cloakbrowser"
                    subdir = "firefox" if btype == "camoufox" else "chromium"
                    portable_ext_path = f"extensions/{subdir}/{eid}"
                    conn.execute(
                        "UPDATE extensions SET path = ? WHERE id = ?",
                        (portable_ext_path, eid),
                    )
            except sqlite3.OperationalError:
                pass

        conn.commit()
    finally:
        conn.close()


def pack(
    dest_tar_path: Path,
    include_browser_state: bool = False,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Package database, settings, extensions, and optionally browser user data into a .tar.gz archive.

    Returns:
        The manifest dict written into the archive.
    """
    runtime = resolve_runtime()
    data_dir = runtime.data_dir
    dest_tar_path.parent.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback(10, "Initializing backup staging area...")

    with tempfile.TemporaryDirectory(dir=str(dest_tar_path.parent), ignore_cleanup_errors=True) as tmp_staging_str:
        staging_dir = Path(tmp_staging_str)

        # 1. Hot backup SQLite database
        db_path = data_dir / "profiles.db"
        staged_db_path = staging_dir / "profiles.db"
        if db_path.exists():
            if progress_callback:
                progress_callback(15, "Performing consistent database hot backup...")
            src_conn = sqlite3.connect(str(db_path))
            dst_conn = sqlite3.connect(str(staged_db_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()

            # Convert hardcoded absolute host paths into portable relative paths
            _relativize_staged_database(staged_db_path, data_dir)

        # 2. Settings JSON
        if progress_callback:
            progress_callback(20, "Collecting system settings...")
        settings_data = load_settings()
        # Clean out any accidental secrets if present
        clean_settings = {k: v for k, v in settings_data.items() if not k.endswith(("_password", "_secret_key"))}
        staged_settings_path = staging_dir / "settings.json"
        staged_settings_path.write_text(json.dumps(clean_settings, indent=2, ensure_ascii=False), encoding="utf-8")

        # 3. Create Manifest
        mode = "full" if include_browser_state else "config"
        manifest = {
            "version": MANIFEST_VERSION,
            "app_name": "AntiBrowser-Manager",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "mode": mode,
            "includes_browser_state": include_browser_state,
            "checksum_algorithm": "sha256",
        }
        staged_manifest_path = staging_dir / "manifest.json"
        staged_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # Prepare Webstore extension exclusions to reduce backup size
        exclude_arcnames: set[str] = set()
        if staged_db_path.exists():
            ext_conn = None
            try:
                ext_conn = sqlite3.connect(str(staged_db_path))
                ext_conn.row_factory = sqlite3.Row
                has_exts = ext_conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='extensions'"
                ).fetchone() is not None
                if has_exts:
                    rows = ext_conn.execute("SELECT path FROM extensions WHERE source = 'webstore_id'").fetchall()
                    for row in rows:
                        p = row["path"]
                        if p and p.startswith("extensions/"):
                            exclude_arcnames.add(p)
            except Exception:
                pass
            finally:
                if ext_conn is not None:
                    ext_conn.close()

        # 4. Assemble .tar.gz
        if progress_callback:
            progress_callback(25, "Compressing archive files...")

        def _ext_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
            # tarinfo.name is e.g. "extensions/chromium/abcdefgh..."
            # Windows might use backslashes in tarinfo.name if python is dumb, but usually forward
            for ex in exclude_arcnames:
                if tarinfo.name == ex or tarinfo.name.startswith(ex + "/"):
                    return None
            return tarinfo

        with tarfile.open(dest_tar_path, "w:gz") as tar:
            # Add manifest
            tar.add(str(staged_manifest_path), arcname="manifest.json")

            # Add database if present
            if staged_db_path.exists():
                tar.add(str(staged_db_path), arcname="profiles.db")

            # Add settings
            tar.add(str(staged_settings_path), arcname="settings.json")

            # Add extensions directory
            extensions_dir = data_dir / "extensions"
            if extensions_dir.exists() and any(extensions_dir.iterdir()):
                if progress_callback:
                    progress_callback(30, "Archiving extensions directory (excluding Webstore extensions)...")
                tar.add(str(extensions_dir), arcname="extensions", filter=_ext_filter)

            # Optionally add browser profiles user data directory
            if include_browser_state:
                profiles_dir = data_dir / "profiles"
                if profiles_dir.exists():
                    if progress_callback:
                        progress_callback(35, "Archiving browser user data directory (cookies, sessions)...")
                    tar.add(str(profiles_dir), arcname="profiles")

        if progress_callback:
            progress_callback(40, "Archive compression complete.")

        return manifest


def unpack(
    src_tar_path: Path,
    extract_dir: Path,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Unpack a .tar.gz backup archive safely into the target extraction directory.

    Returns:
        The manifest dict parsed from the archive.

    Raises:
        ValueError: If archive is corrupted, contains malicious path traversal members, or missing manifest.
    """
    extract_dir.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback(10, "Inspecting backup archive contents...")

    with tarfile.open(src_tar_path, "r:gz") as tar:
        # Validate member paths
        members = tar.getmembers()
        for member in members:
            if not _is_safe_tar_member(member, extract_dir):
                raise ValueError(f"Malicious archive member detected (path traversal): {member.name}")

        if hasattr(tarfile, "data_filter"):
            tar.extractall(path=extract_dir, filter="data")
        else:
            tar.extractall(path=extract_dir)

    manifest_file = extract_dir / "manifest.json"
    if not manifest_file.exists():
        raise ValueError("Invalid backup archive: manifest.json is missing")

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to read backup manifest.json: {exc}") from exc

    if progress_callback:
        progress_callback(50, "Backup archive extracted successfully.")

    return manifest
