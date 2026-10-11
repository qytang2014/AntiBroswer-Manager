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
        self._last_completed_task: dict[str, Any] | None = None
        self._last_completed_at: float | None = None
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
        """Return the current backup configuration with masked/stripped credentials and env fallbacks."""
        stored = load_settings().get("backup", {})
        backend = (
            stored.get("backend")
            or os.environ.get("ANTIBROWSER_BACKUP_BACKEND")
            or os.environ.get("BACKUP_BACKEND")
        )

        def _check_cred(key: str) -> bool:
            try:
                return credentials.has_credential(key)
            except Exception:
                return False

        def _resolve(field: str, *env_keys: str, default: Any = None) -> Any:
            val = stored.get(field)
            if val is not None and val != "":
                return val
            for ek in env_keys:
                eval_ = os.environ.get(ek)
                if eval_ is not None and eval_ != "":
                    return eval_
            return default

        return {
            "backend": backend,
            "webdav_url": _resolve("webdav_url", "ANTIBROWSER_BACKUP_WEBDAV_URL", "BACKUP_WEBDAV_URL"),
            "webdav_username": _resolve("webdav_username", "ANTIBROWSER_BACKUP_WEBDAV_USERNAME", "BACKUP_WEBDAV_USERNAME"),
            "webdav_password_set": _check_cred("webdav_password"),
            "webdav_remote_path": _resolve("webdav_remote_path", "ANTIBROWSER_BACKUP_WEBDAV_REMOTE_PATH", "BACKUP_WEBDAV_REMOTE_PATH", default="/antibrowser_backups"),
            "webdav_skip_ssl": bool(_resolve("webdav_skip_ssl", "ANTIBROWSER_BACKUP_WEBDAV_SKIP_SSL", "BACKUP_WEBDAV_SKIP_SSL", default=False)),
            "s3_endpoint_url": _resolve("s3_endpoint_url", "ANTIBROWSER_BACKUP_S3_ENDPOINT_URL", "BACKUP_S3_ENDPOINT_URL"),
            "s3_access_key": _resolve("s3_access_key", "ANTIBROWSER_BACKUP_S3_ACCESS_KEY", "BACKUP_S3_ACCESS_KEY"),
            "s3_secret_key_set": _check_cred("s3_secret_key"),
            "s3_bucket": _resolve("s3_bucket", "ANTIBROWSER_BACKUP_S3_BUCKET", "BACKUP_S3_BUCKET"),
            "s3_prefix": _resolve("s3_prefix", "ANTIBROWSER_BACKUP_S3_PREFIX", "BACKUP_S3_PREFIX", default="antibrowser_backups"),
            "s3_region": _resolve("s3_region", "ANTIBROWSER_BACKUP_S3_REGION", "BACKUP_S3_REGION", default="us-east-1"),
            "encrypt_enabled": bool(_resolve("encrypt_enabled", "ANTIBROWSER_BACKUP_ENCRYPT_ENABLED", "BACKUP_ENCRYPT_ENABLED", default=False)),
            "encrypt_password_set": _check_cred("encrypt_password"),
            "auto_backup_interval_hours": int(_resolve("auto_backup_interval_hours", "ANTIBROWSER_BACKUP_AUTO_INTERVAL_HOURS", "BACKUP_AUTO_INTERVAL_HOURS", default=0)),
            "retain_count": int(_resolve("retain_count", "ANTIBROWSER_BACKUP_RETAIN_COUNT", "BACKUP_RETAIN_COUNT", default=10)),
            "include_browser_state": bool(_resolve("include_browser_state", "ANTIBROWSER_BACKUP_INCLUDE_BROWSER_STATE", "BACKUP_INCLUDE_BROWSER_STATE", default=False)),
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
        import time
        self._tasks[task_id] = data
        if data.get("status") in ("completed", "error"):
            self._last_completed_task = data
            self._last_completed_at = time.time()
        for q in self._task_listeners.get(task_id, []):
            q.put_nowait(data)

    def get_status(self) -> dict[str, Any]:
        """Return the current active backup/restore task or recently completed/failed task."""
        import time
        # 1. Look for active running task
        for task in reversed(list(self._tasks.values())):
            if task.get("status") == "running":
                return {"active": True, "task": task}

        # 2. Check if a task completed or errored within the last 8 seconds
        if self._last_completed_task and self._last_completed_at:
            if time.time() - self._last_completed_at <= 8.0:
                return {"active": False, "task": self._last_completed_task}

        return {"active": False, "task": None}

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

    async def create_backup(
        self, include_browser_state: bool | None = None, mode: str | None = None
    ) -> str:
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

        asyncio.create_task(self._run_backup(task_id, include_browser_state, mode))
        return task_id

    async def _run_backup(
        self, task_id: str, include_browser_state: bool | None, mode: str | None = None
    ) -> None:
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
                    if mode is not None:
                        include_browser_state = (mode == "session")
                    elif include_browser_state is None:
                        include_browser_state = bool(cfg.get("include_browser_state", False))

                    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
                    mode_tag = "session" if include_browser_state else "config"
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
                    exc_str = str(exc) or repr(exc)
                    self.last_backup_error = exc_str
                    self.last_backup_error_time = datetime.datetime.now(datetime.timezone.utc)
                    logger.error("Backup failed for task %s: %s", task_id, exc_str, exc_info=True)
                    self._publish_event(
                        task_id,
                        {
                            "task_id": task_id,
                            "type": "backup",
                            "stage": "error",
                            "percent": 100,
                            "message": f"Backup failed: {exc_str}",
                            "status": "error",
                            "error": exc_str,
                        },
                    )
                finally:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    self.cleanup_stale_temp_dirs()

    async def restore_backup(
        self,
        filename: str,
        decrypt_password: str | None = None,
        mode: str = "replace",
        conflict_strategy: str = "latest_wins",
    ) -> str:
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
            "mode": mode,
            "conflict_strategy": conflict_strategy,
        }

        asyncio.create_task(
            self._run_restore(task_id, filename, decrypt_password, mode, conflict_strategy)
        )
        return task_id

    async def _run_restore(
        self,
        task_id: str,
        filename: str,
        decrypt_password: str | None,
        mode: str = "replace",
        conflict_strategy: str = "latest_wins",
    ) -> None:
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
                    logger.info("Restoring from manifest: %s (mode=%s)", manifest, mode)

                    # Step 5: Create safety snapshot
                    progress_cb(88, "正在创建当前系统状态的安全快照...")
                    runtime = resolve_runtime()
                    data_dir = runtime.data_dir
                    snapshot_prefix = "pre_merge" if mode == "merge" else "pre_restore"
                    snapshot_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
                    snapshot_dir = data_dir / "snapshots" / f"{snapshot_prefix}_{snapshot_time}"
                    snapshot_dir.mkdir(parents=True, exist_ok=True)

                    if (data_dir / "profiles.db").exists():
                        shutil.copy2(data_dir / "profiles.db", snapshot_dir / "profiles.db")
                    if (data_dir / "settings.json").exists():
                        shutil.copy2(data_dir / "settings.json", snapshot_dir / "settings.json")

                    if mode == "merge":
                        self.merge_from_staging(staging_dir, data_dir, conflict_strategy, progress_cb, manifest)
                    else:
                        # Step 6: Atomic swap of databases and configuration (Replace mode)
                        progress_cb(92, "正在全量替换数据库与系统配置...")
                        if (staging_dir / "profiles.db").exists():
                            shutil.copy2(staging_dir / "profiles.db", data_dir / "profiles.db")

                        if (staging_dir / "settings.json").exists():
                            # Preserve currently active backup configuration so remote connectivity remains intact
                            restored_settings = json.loads((staging_dir / "settings.json").read_text(encoding="utf-8"))
                            restored_backup = restored_settings.get("backup", {})
                            if cfg and cfg.get("backend"):
                                merged_backup = {**restored_backup, **cfg}
                            else:
                                merged_backup = restored_backup
                            restored_settings["backup"] = merged_backup
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

                    # Step 7: Re-initialize database connections and realign paths
                    db.init_db()
                    db.realign_profile_paths()

                    if self.browser_mgr:
                        self.browser_mgr.resolve_binary_status()

                    # Step 8: Rebuild missing webstore extensions
                    progress_cb(99, "正在检查并后台重建缺失的商店插件...")
                    try:
                        from backend.extension_manager import rebuild_missing_extensions
                        asyncio.create_task(rebuild_missing_extensions())
                    except Exception as e:
                        logger.error("Failed to start extension rebuild task: %s", e)

                    success_msg = (
                        "数据增量合并完成！已成功并入新环境并同步授权凭据。"
                        if mode == "merge"
                        else "数据恢复成功！请刷新页面加载最新环境与配置。"
                    )
                    self._publish_event(
                        task_id,
                        {
                            "task_id": task_id,
                            "type": "restore",
                            "stage": "complete",
                            "percent": 100,
                            "message": success_msg,
                            "status": "completed",
                            "error": None,
                        },
                    )
                except Exception as exc:
                    exc_str = str(exc) or repr(exc)
                    logger.error("Restore failed for task %s: %s", task_id, exc_str, exc_info=True)
                    self._publish_event(
                        task_id,
                        {
                            "task_id": task_id,
                            "type": "restore",
                            "stage": "error",
                            "percent": 100,
                            "message": f"Restoration failed: {exc_str}",
                            "status": "error",
                            "error": exc_str,
                        },
                    )
                finally:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    self.cleanup_stale_temp_dirs()

    def merge_from_staging(
        self,
        staging_dir: Path,
        data_dir: Path,
        conflict_strategy: str,
        progress_cb: Callable[[int, str], None],
        manifest: dict[str, Any],
    ) -> None:
        """Incrementally merge profiles, licenses, extensions, and proxy nodes from staging into the active database."""
        import sqlite3

        progress_cb(90, "正在合并系统设置与授权池 (License Pool)...")
        # 1. License Pool Union & Build Staging-to-Local ID Map
        staging_id_to_local_id: dict[str, str] = {}
        staging_settings_file = staging_dir / "settings.json"
        current_settings = load_settings()

        if staging_settings_file.is_file():
            try:
                staging_settings = json.loads(staging_settings_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to parse staging settings.json during merge: %s", e)
                staging_settings = {}

            # Prepare local licenses list
            local_licenses: list[dict[str, Any]] = list(current_settings.get("licenses") or [])
            if not local_licenses and current_settings.get("license_key"):
                local_licenses = [{
                    "id": "default-id",
                    "name": "默认 License",
                    "key": current_settings["license_key"],
                    "is_default": True,
                }]

            # Prepare staging licenses list
            staging_licenses: list[dict[str, Any]] = list(staging_settings.get("licenses") or [])
            if not staging_licenses and staging_settings.get("license_key"):
                staging_licenses = [{
                    "id": "default-id",
                    "name": "默认 License",
                    "key": staging_settings["license_key"],
                    "is_default": True,
                }]

            local_by_key = {
                (lic.get("key") or "").strip(): lic
                for lic in local_licenses
                if (lic.get("key") or "").strip()
            }

            for s_lic in staging_licenses:
                s_key = (s_lic.get("key") or "").strip()
                s_id = s_lic.get("id") or str(uuid.uuid4())
                if not s_key:
                    continue

                if s_key in local_by_key:
                    # License key already exists on target machine
                    target_lic = local_by_key[s_key]
                    target_id = target_lic.get("id") or "default-id"
                    if s_id:
                        staging_id_to_local_id[s_id] = target_id
                    # If staging has newer updated_at and a non-empty name, update local name
                    s_updated = s_lic.get("updated_at") or ""
                    l_updated = target_lic.get("updated_at") or ""
                    if s_updated > l_updated and s_lic.get("name"):
                        target_lic["name"] = s_lic["name"]
                else:
                    # New license from backup
                    existing_ids = {lic.get("id") for lic in local_licenses}
                    final_id = s_id
                    if final_id in existing_ids:
                        final_id = str(uuid.uuid4())
                    new_entry = dict(s_lic)
                    new_entry["id"] = final_id
                    if any(lic.get("is_default") for lic in local_licenses):
                        new_entry["is_default"] = False
                    local_licenses.append(new_entry)
                    local_by_key[s_key] = new_entry
                    if s_id:
                        staging_id_to_local_id[s_id] = final_id

            current_settings["licenses"] = local_licenses
            save_settings(current_settings)
            if self.browser_mgr:
                self.browser_mgr.licenses = local_licenses

        # 2. Database Merge
        staging_db_path = staging_dir / "profiles.db"
        local_db_path = data_dir / "profiles.db"
        if not staging_db_path.is_file():
            logger.info("No profiles.db in staging area, skipping database merge.")
            return

        progress_cb(92, "正在比对并增量合并浏览器环境 (Profiles)...")
        s_conn = sqlite3.connect(str(staging_db_path))
        s_conn.row_factory = sqlite3.Row
        l_conn = sqlite3.connect(str(local_db_path))
        l_conn.row_factory = sqlite3.Row

        try:
            s_tables = {
                r[0] for r in s_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            l_tables = {
                r[0] for r in l_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }

            # 2.1 Merge Profiles
            if "profiles" in s_tables and "profiles" in l_tables:
                local_cols_info = l_conn.execute("PRAGMA table_info(profiles)").fetchall()
                local_cols = {r["name"] for r in local_cols_info}

                local_rows = l_conn.execute("SELECT * FROM profiles").fetchall()
                local_by_id = {r["id"]: dict(r) for r in local_rows}
                local_names = {r["name"] for r in local_rows}

                staged_rows = s_conn.execute("SELECT * FROM profiles").fetchall()
                for s_row in staged_rows:
                    pid = s_row["id"]
                    p_name = s_row["name"]
                    btype = s_row["browser_type"] or "cloakbrowser"
                    engine_subdir = "camoufox" if btype == "camoufox" else "cloakbrowser"
                    staged_prof_dir = staging_dir / "profiles" / engine_subdir / pid
                    dest_prof_dir = data_dir / "profiles" / engine_subdir / pid

                    # Remap license_id
                    raw_lic_id = s_row["license_id"] if "license_id" in s_row.keys() else None
                    remapped_lic_id = staging_id_to_local_id.get(raw_lic_id, raw_lic_id)

                    # Build base dictionary for insert/update with supported local columns
                    row_data = {}
                    for col in local_cols:
                        if col in s_row.keys():
                            row_data[col] = s_row[col]
                    if "license_id" in local_cols:
                        row_data["license_id"] = remapped_lic_id

                    if pid in local_by_id:
                        # UUID collision - resolve conflict
                        local_item = local_by_id[pid]
                        should_overwrite = False
                        if conflict_strategy == "skip":
                            logger.info("Conflict strategy 'skip': skipping profile %s (%s)", pid, p_name)
                            continue
                        elif conflict_strategy == "overwrite":
                            should_overwrite = True
                        elif conflict_strategy == "latest_wins":
                            s_time = s_row["updated_at"] or ""
                            l_time = local_item.get("updated_at") or ""
                            if s_time > l_time:
                                should_overwrite = True
                            else:
                                logger.info(
                                    "Conflict strategy 'latest_wins': local (%s) >= staging (%s) for %s, skipping",
                                    l_time, s_time, pid
                                )
                                continue
                        elif conflict_strategy == "keep_both":
                            # Mint a new UUID and rename
                            new_pid = str(uuid.uuid4())
                            new_name = f"{p_name} (来自备份)"
                            counter = 2
                            while new_name in local_names:
                                new_name = f"{p_name} (来自备份 {counter})"
                                counter += 1
                            local_names.add(new_name)

                            row_data["id"] = new_pid
                            row_data["name"] = new_name
                            new_dest_prof_dir = data_dir / "profiles" / engine_subdir / new_pid
                            row_data["user_data_dir"] = f"profiles/{engine_subdir}/{new_pid}"

                            cols = list(row_data.keys())
                            placeholders = ", ".join("?" for _ in cols)
                            l_conn.execute(
                                f"INSERT INTO profiles ({', '.join(cols)}) VALUES ({placeholders})",
                                [row_data[c] for c in cols]
                            )

                            if staged_prof_dir.is_dir():
                                new_dest_prof_dir.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copytree(staged_prof_dir, new_dest_prof_dir, dirs_exist_ok=True)

                            if "profile_tags" in s_tables and "profile_tags" in l_tables:
                                tags = s_conn.execute("SELECT tag, color FROM profile_tags WHERE profile_id = ?", (pid,)).fetchall()
                                for t in tags:
                                    l_conn.execute(
                                        "INSERT OR IGNORE INTO profile_tags (profile_id, tag, color) VALUES (?, ?, ?)",
                                        (new_pid, t["tag"], t["color"])
                                    )
                            continue

                        if should_overwrite:
                            set_clauses = [f"{c} = ?" for c in row_data.keys() if c != "id"]
                            vals = [row_data[c] for c in row_data.keys() if c != "id"]
                            vals.append(pid)
                            l_conn.execute(
                                f"UPDATE profiles SET {', '.join(set_clauses)} WHERE id = ?",
                                vals
                            )
                            if staged_prof_dir.is_dir():
                                dest_prof_dir.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copytree(staged_prof_dir, dest_prof_dir, dirs_exist_ok=True)

                            if "profile_tags" in l_tables:
                                l_conn.execute("DELETE FROM profile_tags WHERE profile_id = ?", (pid,))
                                if "profile_tags" in s_tables:
                                    tags = s_conn.execute("SELECT tag, color FROM profile_tags WHERE profile_id = ?", (pid,)).fetchall()
                                    for t in tags:
                                        l_conn.execute(
                                            "INSERT OR IGNORE INTO profile_tags (profile_id, tag, color) VALUES (?, ?, ?)",
                                            (pid, t["tag"], t["color"])
                                        )
                    else:
                        # Non-conflicting profile (new profile from backup)
                        final_name = p_name
                        if final_name in local_names:
                            final_name = f"{p_name} (来自备份)"
                            counter = 2
                            while final_name in local_names:
                                final_name = f"{p_name} (来自备份 {counter})"
                                counter += 1
                        local_names.add(final_name)
                        row_data["name"] = final_name

                        cols = list(row_data.keys())
                        placeholders = ", ".join("?" for _ in cols)
                        l_conn.execute(
                            f"INSERT INTO profiles ({', '.join(cols)}) VALUES ({placeholders})",
                            [row_data[c] for c in cols]
                        )
                        local_by_id[pid] = row_data

                        if staged_prof_dir.is_dir():
                            dest_prof_dir.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copytree(staged_prof_dir, dest_prof_dir, dirs_exist_ok=True)

                        if "profile_tags" in s_tables and "profile_tags" in l_tables:
                            tags = s_conn.execute("SELECT tag, color FROM profile_tags WHERE profile_id = ?", (pid,)).fetchall()
                            for t in tags:
                                l_conn.execute(
                                    "INSERT OR IGNORE INTO profile_tags (profile_id, tag, color) VALUES (?, ?, ?)",
                                    (pid, t["tag"], t["color"])
                                )

            # 2.2 Merge Extensions
            if "extensions" in s_tables and "extensions" in l_tables:
                progress_cb(95, "正在合并扩展插件库...")
                ext_cols = {r["name"] for r in l_conn.execute("PRAGMA table_info(extensions)").fetchall()}
                s_exts = s_conn.execute("SELECT * FROM extensions").fetchall()
                for ext in s_exts:
                    ext_data = {c: ext[c] for c in ext_cols if c in ext.keys()}
                    cols = list(ext_data.keys())
                    placeholders = ", ".join("?" for _ in cols)
                    l_conn.execute(
                        f"INSERT OR IGNORE INTO extensions ({', '.join(cols)}) VALUES ({placeholders})",
                        [ext_data[c] for c in cols]
                    )

            # 2.3 Merge Subscriptions & Proxy Nodes
            if "subscriptions" in s_tables and "subscriptions" in l_tables:
                progress_cb(96, "正在合并代理节点与订阅...")
                sub_cols = {r["name"] for r in l_conn.execute("PRAGMA table_info(subscriptions)").fetchall()}
                s_subs = s_conn.execute("SELECT * FROM subscriptions").fetchall()
                l_subs = l_conn.execute("SELECT * FROM subscriptions").fetchall()
                local_sub_urls = {r["url"]: r["id"] for r in l_subs}
                sub_id_map: dict[str, str] = {}

                for s_sub in s_subs:
                    s_url = s_sub["url"]
                    old_sid = s_sub["id"]
                    if s_url in local_sub_urls:
                        sub_id_map[old_sid] = local_sub_urls[s_url]
                    else:
                        sub_data = {c: s_sub[c] for c in sub_cols if c in s_sub.keys()}
                        cols = list(sub_data.keys())
                        placeholders = ", ".join("?" for _ in cols)
                        l_conn.execute(
                            f"INSERT OR IGNORE INTO subscriptions ({', '.join(cols)}) VALUES ({placeholders})",
                            [sub_data[c] for c in cols]
                        )
                        sub_id_map[old_sid] = old_sid

                if "proxy_nodes" in s_tables and "proxy_nodes" in l_tables:
                    node_cols = {r["name"] for r in l_conn.execute("PRAGMA table_info(proxy_nodes)").fetchall()}
                    l_nodes = l_conn.execute("SELECT raw_uri FROM proxy_nodes").fetchall()
                    existing_raw_uris = {r["raw_uri"] for r in l_nodes}
                    s_nodes = s_conn.execute("SELECT * FROM proxy_nodes").fetchall()

                    for node in s_nodes:
                        if node["raw_uri"] in existing_raw_uris:
                            continue
                        node_data = {c: node[c] for c in node_cols if c in node.keys()}
                        if "subscription_id" in node_data and node_data["subscription_id"]:
                            node_data["subscription_id"] = sub_id_map.get(
                                node_data["subscription_id"], node_data["subscription_id"]
                            )
                        cols = list(node_data.keys())
                        placeholders = ", ".join("?" for _ in cols)
                        l_conn.execute(
                            f"INSERT OR IGNORE INTO proxy_nodes ({', '.join(cols)}) VALUES ({placeholders})",
                            [node_data[c] for c in cols]
                        )
                        existing_raw_uris.add(node["raw_uri"])

            l_conn.commit()
        finally:
            s_conn.close()
            l_conn.close()

        # 3. Copy Physical Extension Files
        if (staging_dir / "extensions").is_dir():
            dest_ext = data_dir / "extensions"
            dest_ext.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staging_dir / "extensions", dest_ext, dirs_exist_ok=True)

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
