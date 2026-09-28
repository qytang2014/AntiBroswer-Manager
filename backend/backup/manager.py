"""Backup & Restore Manager coordinating archiver, crypto, storage, and progress events."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from .. import database as db
from ..runtime import resolve_runtime
from ..settings_store import load_settings, save_settings
from . import archiver, credentials, crypto
from .storage import BackupStorage, get_storage_backend

logger = logging.getLogger("cloakbrowser.manager.backup")


class BackupManager:
    """Coordinates backup creation, restoration, scheduling, and live SSE progress."""

    def __init__(self, browser_mgr=None):
        self.browser_mgr = browser_mgr
        self.__lock: asyncio.Lock | None = None
        self._tasks: dict[str, dict[str, Any]] = {}
        self._task_listeners: dict[str, list[asyncio.Queue]] = {}
        self.last_backup_time: datetime.datetime | None = None
        self.last_backup_error: str | None = None
        self.last_backup_error_time: datetime.datetime | None = None
        self.cleanup_stale_temp_dirs()

    @property
    def _lock(self) -> asyncio.Lock:
        if self.__lock is None:
            self.__lock = asyncio.Lock()
        return self.__lock

    def cleanup_stale_temp_dirs(self) -> None:
        """Scan and remove any leftover temporary backup or restore staging directories in data_dir."""
        try:
            runtime = resolve_runtime()
            data_dir = runtime.data_dir
            if data_dir.exists():
                for pattern in ("_tmp_backup_*", "_tmp_restore_*", ".tmp_backup_*", ".tmp_restore_*"):
                    for stale in data_dir.glob(pattern):
                        if stale.is_dir():
                            logger.info("Cleaning up stale temporary backup directory: %s", stale)
                            shutil.rmtree(stale, ignore_errors=True)
                        elif stale.is_file():
                            try:
                                stale.unlink()
                            except OSError:
                                pass
        except Exception as exc:
            logger.debug("Failed sweeping stale backup temp dirs: %s", exc)

    def get_config(self) -> dict[str, Any]:
        """Return the current backup configuration with masked/stripped credentials."""
        stored = load_settings().get("backup", {})
        backend = stored.get("backend")

        def _check_cred(key: str) -> bool:
            try:
                return credentials.has_credential(key)
            except Exception:
                return False

        return {
            "backend": backend,
            "webdav_url": stored.get("webdav_url"),
            "webdav_username": stored.get("webdav_username"),
            "webdav_password_set": _check_cred("webdav_password"),
            "webdav_remote_path": stored.get("webdav_remote_path", "/antibrowser_backups"),
            "webdav_skip_ssl": bool(stored.get("webdav_skip_ssl", False)),
            "s3_endpoint_url": stored.get("s3_endpoint_url"),
            "s3_access_key": stored.get("s3_access_key"),
            "s3_secret_key_set": _check_cred("s3_secret_key"),
            "s3_bucket": stored.get("s3_bucket"),
            "s3_prefix": stored.get("s3_prefix", "antibrowser_backups"),
            "s3_region": stored.get("s3_region", "us-east-1"),
            "encrypt_enabled": bool(stored.get("encrypt_enabled", False)),
            "encrypt_password_set": _check_cred("encrypt_password"),
            "auto_backup_interval_hours": int(stored.get("auto_backup_interval_hours", 0)),
            "retain_count": int(stored.get("retain_count", 10)),
            "include_browser_state": bool(stored.get("include_browser_state", False)),
            "last_backup_at": stored.get("last_backup_at"),
        }

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Update and persist backup settings, saving sensitive credentials to secure storage."""
        stored = load_settings()
        backup_cfg = stored.setdefault("backup", {})

        # Non-sensitive fields
        for field in (
            "backend",
            "webdav_url",
            "webdav_username",
            "webdav_remote_path",
            "webdav_skip_ssl",
            "s3_endpoint_url",
            "s3_access_key",
            "s3_bucket",
            "s3_prefix",
            "s3_region",
            "encrypt_enabled",
            "auto_backup_interval_hours",
            "retain_count",
            "include_browser_state",
        ):
            if field in payload and payload[field] is not None:
                backup_cfg[field] = payload[field]

        # Sensitive credentials stored via Keychain/fallback
        if "webdav_password" in payload and payload["webdav_password"] is not None:
            if payload["webdav_password"]:
                credentials.set_credential("webdav_password", payload["webdav_password"])
            else:
                credentials.delete_credential("webdav_password")

        if "s3_secret_key" in payload and payload["s3_secret_key"] is not None:
            if payload["s3_secret_key"]:
                credentials.set_credential("s3_secret_key", payload["s3_secret_key"])
            else:
                credentials.delete_credential("s3_secret_key")

        if "encrypt_password" in payload and payload["encrypt_password"] is not None:
            if payload["encrypt_password"]:
                credentials.set_credential("encrypt_password", payload["encrypt_password"])
            else:
                credentials.delete_credential("encrypt_password")

        save_settings(stored)
        return self.get_config()

    async def test_connection(self, config_override: dict[str, Any] | None = None) -> tuple[bool, str | None]:
        """Test connection to the configured storage backend."""
        cfg = config_override or load_settings().get("backup", {})
        try:
            storage = get_storage_backend(cfg)
            return await storage.test_connection()
        except Exception as exc:
            return False, str(exc)

    def _publish_event(self, task_id: str, data: dict[str, Any]) -> None:
        self._tasks[task_id] = data
        for q in self._task_listeners.get(task_id, []):
            q.put_nowait(data)

    async def subscribe_progress(self, task_id: str) -> AsyncGenerator[str, None]:
        """Yield Server-Sent Events (SSE) formatted progress updates for a task."""
        queue: asyncio.Queue = asyncio.Queue()
        self._task_listeners.setdefault(task_id, []).append(queue)

        # Send initial state if already known
        if task_id in self._tasks:
            yield f"data: {json.dumps(self._tasks[task_id])}\n\n"

        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=3.0)
                    yield f"data: {json.dumps(data)}\n\n"
                    if data.get("status") in ("completed", "error"):
                        break
                except asyncio.TimeoutError:
                    # Send periodic SSE comment ping so browser and proxies keep socket open
                    yield ": ping\n\n"
        finally:
            if task_id in self._task_listeners:
                try:
                    self._task_listeners[task_id].remove(queue)
                except ValueError:
                    pass

    async def create_backup(self, include_browser_state: bool | None = None) -> str:
        """Trigger an asynchronous backup task."""
        if self._lock.locked():
            raise RuntimeError("Another backup or restore operation is already in progress.")

        cfg = load_settings().get("backup", {})
        if not cfg.get("backend"):
            raise ValueError("Backup backend is not configured. Please configure WebDAV or S3 in settings.")

        task_id = uuid.uuid4().hex[:12]
        self._tasks[task_id] = {
            "task_id": task_id,
            "type": "backup",
            "stage": "starting",
            "percent": 0,
            "message": "Initializing backup task...",
            "status": "running",
            "error": None,
        }

        asyncio.create_task(self._run_backup(task_id, include_browser_state))
        return task_id

    async def _run_backup(self, task_id: str, include_browser_state: bool | None) -> None:
        async with self._lock:
            self.cleanup_stale_temp_dirs()
            # Create isolated temporary directory in system temp to avoid polluting data_dir
            with tempfile.TemporaryDirectory(prefix=f"antibrowser_backup_{task_id}_") as tmp_dir_str:
                work_dir = Path(tmp_dir_str)

                def progress_cb(pct: int, msg: str) -> None:
                    self._publish_event(
                        task_id,
                        {
                            "task_id": task_id,
                            "type": "backup",
                            "stage": "archiving",
                            "percent": pct,
                            "message": msg,
                            "status": "running",
                            "error": None,
                        },
                    )

                try:
                    cfg = load_settings().get("backup", {})
                    if include_browser_state is None:
                        include_browser_state = bool(cfg.get("include_browser_state", False))

                    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
                    mode_tag = "full" if include_browser_state else "config"
                    tar_name = f"antibrowser-backup-{timestamp}-{mode_tag}.tar.gz"
                    tar_path = work_dir / tar_name

                    # Step 1: Pack tar.gz
                    archiver.pack(tar_path, include_browser_state, progress_cb)

                    # Step 2: SHA-256 calculation of raw tar
                    progress_cb(45, "Calculating SHA-256 package checksum...")
                    tar_sha256 = crypto.compute_sha256(tar_path)
                    sha256_path = work_dir / f"{tar_name}.sha256"
                    sha256_path.write_text(f"{tar_sha256}  {tar_name}\n", encoding="utf-8")

                    # Step 3: Optional Encryption
                    encrypt_enabled = bool(cfg.get("encrypt_enabled", False))
                    if encrypt_enabled:
                        password = credentials.get_credential("encrypt_password")
                        if not password:
                            raise ValueError(
                                "Backup encryption is enabled, but no encryption password is set. "
                                "Please configure an encryption password in settings."
                            )
                        progress_cb(55, "Encrypting backup archive with AES-256-GCM...")
                        enc_name = f"{tar_name}.enc"
                        enc_path = work_dir / enc_name
                        crypto.encrypt_file(tar_path, enc_path, password)

                        enc_sha256 = crypto.compute_sha256(enc_path)
                        enc_sha256_path = work_dir / f"{enc_name}.sha256"
                        enc_sha256_path.write_text(f"{enc_sha256}  {enc_name}\n", encoding="utf-8")

                        final_file = enc_path
                        final_name = enc_name
                        final_sidecar = enc_sha256_path
                        final_sidecar_name = f"{enc_name}.sha256"
                    else:
                        final_file = tar_path
                        final_name = tar_name
                        final_sidecar = sha256_path
                        final_sidecar_name = f"{tar_name}.sha256"

                    # Step 4: Storage Upload
                    storage = get_storage_backend(cfg)
                    progress_cb(65, f"Uploading {final_name} to remote storage...")
                    await storage.upload_file(final_file, final_name)

                    progress_cb(85, "Uploading integrity checksum sidecar (.sha256)...")
                    await storage.upload_file(final_sidecar, final_sidecar_name)

                    # Step 5: Retention policy
                    retain_count = int(cfg.get("retain_count", 10))
                    progress_cb(90, f"Applying retention policy (keeping latest {retain_count} backups)...")
                    await storage.apply_retention(retain_count)

                    # Step 6: Record last_backup_at
                    stored = load_settings()
                    stored.setdefault("backup", {})["last_backup_at"] = datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat()
                    save_settings(stored)

                    self.last_backup_time = datetime.datetime.now(datetime.timezone.utc)
                    self.last_backup_error = None
                    self.last_backup_error_time = None

                    self._publish_event(
                        task_id,
                        {
                            "task_id": task_id,
                            "type": "backup",
                            "stage": "complete",
                            "percent": 100,
                            "message": "Backup completed successfully!",
                            "status": "completed",
                            "filename": final_name,
                            "error": None,
                        },
                    )
                except Exception as exc:
                    self.last_backup_error = str(exc)
                    self.last_backup_error_time = datetime.datetime.now(datetime.timezone.utc)
                    logger.error("Backup failed for task %s: %s", task_id, exc, exc_info=True)
                    self._publish_event(
                        task_id,
                        {
                            "task_id": task_id,
                            "type": "backup",
                            "stage": "error",
                            "percent": 100,
                            "message": f"Backup failed: {exc}",
                            "status": "error",
                            "error": str(exc),
                        },
                    )
                finally:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    self.cleanup_stale_temp_dirs()

    async def restore_backup(self, filename: str, decrypt_password: str | None = None) -> str:
        """Trigger an asynchronous restore task."""
        if self._lock.locked():
            raise RuntimeError("Another backup or restore operation is already in progress.")

        # Guard: Ensure no profiles are running
        if self.browser_mgr and (len(self.browser_mgr.running) > 0 or len(self.browser_mgr._launching) > 0):
            raise RuntimeError(
                f"Cannot restore backup while {len(self.browser_mgr.running)} browser profile(s) are running. "
                "Please close all running profiles before restoring."
            )

        task_id = uuid.uuid4().hex[:12]
        self._tasks[task_id] = {
            "task_id": task_id,
            "type": "restore",
            "stage": "starting",
            "percent": 0,
            "message": "Initializing restore task...",
            "status": "running",
            "error": None,
        }

        asyncio.create_task(self._run_restore(task_id, filename, decrypt_password))
        return task_id

    async def _run_restore(self, task_id: str, filename: str, decrypt_password: str | None) -> None:
        async with self._lock:
            self.cleanup_stale_temp_dirs()
            with tempfile.TemporaryDirectory(prefix=f"antibrowser_restore_{task_id}_") as tmp_dir_str:
                work_dir = Path(tmp_dir_str)

                def progress_cb(pct: int, msg: str) -> None:
                    self._publish_event(
                        task_id,
                        {
                            "task_id": task_id,
                            "type": "restore",
                            "stage": "restoring",
                            "percent": pct,
                            "message": msg,
                            "status": "running",
                            "error": None,
                        },
                    )

                try:
                    cfg = load_settings().get("backup", {})
                    storage = get_storage_backend(cfg)

                    # Step 1: Download backup and sidecar checksum
                    progress_cb(10, f"正在连接远端存储下载备份包 {filename}...")
                    local_file = work_dir / filename

                    def dl_cb(pct: int, msg: str) -> None:
                        # Allocate 10% -> 60% of the overall progress bar to download
                        mapped_pct = 10 + int((pct / 100) * 50)
                        progress_cb(mapped_pct, msg)

                    await storage.download_file(filename, local_file, progress_callback=dl_cb)

                    sidecar_name = f"{filename}.sha256"
                    local_sidecar = work_dir / sidecar_name
                    has_sidecar = False
                    try:
                        await storage.download_file(sidecar_name, local_sidecar)
                        has_sidecar = True
                    except Exception:
                        logger.debug("No sidecar checksum found for %s", filename)

                    # Step 2: Verify checksum if sidecar is available
                    if has_sidecar and local_sidecar.is_file():
                        progress_cb(65, "正在校验 SHA-256 数据包完整性...")
                        expected_hash = local_sidecar.read_text(encoding="utf-8").strip().split()[0]
                        if not crypto.verify_sha256(local_file, expected_hash):
                            raise crypto.IntegrityError(
                                "SHA-256 package checksum verification failed! "
                                "The remote backup file may be corrupted or tampered with."
                            )

                    # Step 3: Decrypt if .enc
                    if filename.endswith(".enc"):
                        progress_cb(72, "正在使用 AES-256-GCM 解密备份数据包...")
                        password = decrypt_password or credentials.get_credential("encrypt_password")
                        if not password:
                            raise crypto.DecryptionError(
                                "This backup package is encrypted. Please provide the decryption password."
                            )
                        tar_name = filename[:-4]  # remove .enc
                        local_tar = work_dir / tar_name
                        crypto.decrypt_file(local_file, local_tar, password)
                    else:
                        local_tar = local_file

                    # Step 4: Extract and inspect
                    progress_cb(80, "正在解压备份数据包内容...")
                    staging_dir = work_dir / "extracted"
                    manifest = archiver.unpack(local_tar, staging_dir)
                    logger.info("Restoring from manifest: %s", manifest)

                    # Step 5: Create a safety snapshot of current data before overwriting
                    progress_cb(88, "正在创建当前系统状态的安全快照...")
                    data_dir = runtime.data_dir
                    snapshot_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
                    snapshot_dir = data_dir / "snapshots" / f"pre_restore_{snapshot_time}"
                    snapshot_dir.mkdir(parents=True, exist_ok=True)

                    if (data_dir / "profiles.db").exists():
                        shutil.copy2(data_dir / "profiles.db", snapshot_dir / "profiles.db")
                    if (data_dir / "settings.json").exists():
                        shutil.copy2(data_dir / "settings.json", snapshot_dir / "settings.json")

                    # Step 6: Atomic swap of databases and configuration
                    progress_cb(92, "正在恢复数据库与系统配置...")
                    if (staging_dir / "profiles.db").exists():
                        shutil.copy2(staging_dir / "profiles.db", data_dir / "profiles.db")

                    if (staging_dir / "settings.json").exists():
                        # Preserve currently active backup configuration so remote connectivity remains intact
                        restored_settings = json.loads((staging_dir / "settings.json").read_text(encoding="utf-8"))
                        restored_settings["backup"] = cfg
                        save_settings(restored_settings)

                    if (staging_dir / "extensions").is_dir():
                        progress_cb(95, "正在恢复浏览器扩展插件...")
                        dest_ext = data_dir / "extensions"
                        dest_ext.mkdir(parents=True, exist_ok=True)
                        shutil.copytree(staging_dir / "extensions", dest_ext, dirs_exist_ok=True)

                    if manifest.get("includes_browser_state") and (staging_dir / "profiles").is_dir():
                        progress_cb(98, "正在恢复浏览器环境 Cookies 与会话状态...")
                        dest_prof = data_dir / "profiles"
                        dest_prof.mkdir(parents=True, exist_ok=True)
                        shutil.copytree(staging_dir / "profiles", dest_prof, dirs_exist_ok=True)

                    # Step 7: Re-initialize database connections
                    db.init_db()

                    self._publish_event(
                        task_id,
                        {
                            "task_id": task_id,
                            "type": "restore",
                            "stage": "complete",
                            "percent": 100,
                            "message": "数据恢复成功！请刷新页面加载最新环境与配置。",
                            "status": "completed",
                            "error": None,
                        },
                    )
                except Exception as exc:
                    logger.error("Restore failed for task %s: %s", task_id, exc, exc_info=True)
                    self._publish_event(
                        task_id,
                        {
                            "task_id": task_id,
                            "type": "restore",
                            "stage": "error",
                            "percent": 100,
                            "message": f"Restoration failed: {exc}",
                            "status": "error",
                            "error": str(exc),
                        },
                    )
                finally:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    self.cleanup_stale_temp_dirs()

    async def list_backups(self) -> list[dict[str, Any]]:
        """List available backups on the remote storage backend."""
        cfg = load_settings().get("backup", {})
        if not cfg.get("backend"):
            return []
        storage = get_storage_backend(cfg)
        return await storage.list_backups()

    async def delete_backup(self, filename: str) -> None:
        """Delete a remote backup package."""
        cfg = load_settings().get("backup", {})
        storage = get_storage_backend(cfg)
        await storage.delete_file(filename)
