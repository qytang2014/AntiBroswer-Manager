"""Automated background backup scheduler using asyncio."""

from __future__ import annotations

import asyncio
import datetime
import logging

from ..settings_store import load_settings
from . import credentials
from .manager import BackupManager

logger = logging.getLogger("cloakbrowser.manager.backup.scheduler")

_last_warned_missing_config: str | None = None


async def run_backup_scheduler(backup_mgr: BackupManager, check_interval_seconds: int = 60) -> None:
    """Continuously monitor and trigger scheduled automated backups."""
    global _last_warned_missing_config
    logger.info("Backup scheduler started (check interval: %ds)", check_interval_seconds)
    while True:
        try:
            await asyncio.sleep(check_interval_seconds)
            cfg = load_settings().get("backup", {})
            interval_hours = int(cfg.get("auto_backup_interval_hours", 0))
            backend = cfg.get("backend")

            if interval_hours <= 0 or not backend:
                continue

            # Pre-validation: ensure required configurations are set before attempting backup
            if backend == "webdav" and not cfg.get("webdav_url"):
                if _last_warned_missing_config != "webdav_url":
                    logger.warning("Scheduled backup skipped: WebDAV storage selected but webdav_url is missing")
                    _last_warned_missing_config = "webdav_url"
                continue
            if backend == "s3" and not cfg.get("s3_bucket"):
                if _last_warned_missing_config != "s3_bucket":
                    logger.warning("Scheduled backup skipped: S3 storage selected but s3_bucket is missing")
                    _last_warned_missing_config = "s3_bucket"
                continue

            if bool(cfg.get("encrypt_enabled", False)) and not credentials.has_credential("encrypt_password"):
                if _last_warned_missing_config != "encrypt_password":
                    logger.warning(
                        "Scheduled backup skipped: backup encryption is enabled but encrypt_password is not set"
                    )
                    _last_warned_missing_config = "encrypt_password"
                continue

            _last_warned_missing_config = None

            # Retry backoff: do not spam if previous backup attempt recently failed
            if backup_mgr.last_backup_error_time:
                failed_elapsed = (
                    datetime.datetime.now(datetime.timezone.utc) - backup_mgr.last_backup_error_time
                ).total_seconds()
                if failed_elapsed < 900:  # 15 minutes backoff
                    continue

            last_backup_str = cfg.get("last_backup_at")
            should_run = False

            if not last_backup_str:
                should_run = True
            else:
                try:
                    last_backup_dt = datetime.datetime.fromisoformat(last_backup_str)
                    if last_backup_dt.tzinfo is None:
                        last_backup_dt = last_backup_dt.replace(tzinfo=datetime.timezone.utc)
                    elapsed_seconds = (
                        datetime.datetime.now(datetime.timezone.utc) - last_backup_dt
                    ).total_seconds()
                    if elapsed_seconds >= interval_hours * 3600:
                        should_run = True
                except Exception as exc:
                    logger.warning("Invalid last_backup_at date string %r: %s", last_backup_str, exc)
                    should_run = True

            if should_run:
                logger.info("Triggering scheduled automated backup (interval: %dh)", interval_hours)
                try:
                    task_id = await backup_mgr.create_backup()
                    logger.info("Scheduled backup triggered with task ID %s", task_id)
                except Exception as exc:
                    backup_mgr.last_backup_error = str(exc)
                    backup_mgr.last_backup_error_time = datetime.datetime.now(datetime.timezone.utc)
                    logger.warning("Could not trigger scheduled backup: %s", exc)

        except asyncio.CancelledError:
            logger.info("Backup scheduler stopped")
            break
        except Exception as exc:
            logger.error("Error in backup scheduler loop: %s", exc, exc_info=True)
            await asyncio.sleep(10)
