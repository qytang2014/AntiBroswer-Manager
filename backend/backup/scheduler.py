"""Automated background backup scheduler using asyncio."""

from __future__ import annotations

import asyncio
import datetime
import logging

from ..settings_store import load_settings
from .manager import BackupManager

logger = logging.getLogger("cloakbrowser.manager.backup.scheduler")


async def run_backup_scheduler(backup_mgr: BackupManager, check_interval_seconds: int = 60) -> None:
    """Continuously monitor and trigger scheduled automated backups."""
    logger.info("Backup scheduler started (check interval: %ds)", check_interval_seconds)
    while True:
        try:
            await asyncio.sleep(check_interval_seconds)
            cfg = load_settings().get("backup", {})
            interval_hours = int(cfg.get("auto_backup_interval_hours", 0))
            backend = cfg.get("backend")

            if interval_hours <= 0 or not backend:
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
                    logger.warning("Could not trigger scheduled backup: %s", exc)

        except asyncio.CancelledError:
            logger.info("Backup scheduler stopped")
            break
        except Exception as exc:
            logger.error("Error in backup scheduler loop: %s", exc, exc_info=True)
            await asyncio.sleep(10)
