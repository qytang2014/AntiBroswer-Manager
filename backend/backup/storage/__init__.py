"""Storage backend abstraction for remote backups."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable


class BackupStorage(ABC):
    """Abstract base class for backup remote storage backends."""

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str | None]:
        """Test whether the remote storage is reachable and credentials are valid."""

    @abstractmethod
    async def upload_file(
        self,
        local_path: Path,
        remote_filename: str,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> None:
        """Upload a local file to the remote storage destination."""

    @abstractmethod
    async def download_file(
        self,
        remote_filename: str,
        local_path: Path,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> None:
        """Download a remote file to the specified local path."""

    @abstractmethod
    async def list_backups(self) -> list[dict[str, Any]]:
        """List all available backup files on the remote storage."""

    @abstractmethod
    async def delete_file(self, remote_filename: str) -> None:
        """Delete a remote file (and its .sha256 sidecar if present)."""

    @abstractmethod
    async def apply_retention(self, retain_count: int) -> list[str]:
        """Delete oldest backups if total count exceeds retain_count."""


def get_storage_backend(config: dict[str, Any] | None = None) -> BackupStorage:
    """Instantiate a BackupStorage based on the provided or stored settings."""
    from ...settings_store import load_settings
    from .. import credentials
    from .s3 import S3Storage
    from .webdav import WebDAVStorage

    cfg = dict(config) if config is not None else dict(load_settings().get("backup", {}))
    backend_type = (
        cfg.get("backend")
        or os.environ.get("ANTIBROWSER_BACKUP_BACKEND")
        or os.environ.get("BACKUP_BACKEND")
    )

    if backend_type == "webdav":
        url = (
            cfg.get("webdav_url")
            or os.environ.get("ANTIBROWSER_BACKUP_WEBDAV_URL")
            or os.environ.get("BACKUP_WEBDAV_URL")
        )
        if not url:
            raise ValueError("WebDAV URL is not configured")
        pwd = (
            cfg.get("webdav_password")
            or credentials.get_credential("webdav_password")
            or ""
        )
        return WebDAVStorage(
            url=url,
            username=cfg.get("webdav_username") or os.environ.get("ANTIBROWSER_BACKUP_WEBDAV_USERNAME") or os.environ.get("BACKUP_WEBDAV_USERNAME") or "",
            password=pwd,
            remote_path=cfg.get("webdav_remote_path") or os.environ.get("ANTIBROWSER_BACKUP_WEBDAV_REMOTE_PATH") or os.environ.get("BACKUP_WEBDAV_REMOTE_PATH") or "/antibrowser_backups",
            skip_ssl_verify=bool(cfg.get("webdav_skip_ssl", False)),
        )

    if backend_type == "s3":
        bucket = (
            cfg.get("s3_bucket")
            or os.environ.get("ANTIBROWSER_BACKUP_S3_BUCKET")
            or os.environ.get("BACKUP_S3_BUCKET")
        )
        if not bucket:
            raise ValueError("S3 Bucket name is not configured")
        secret = (
            cfg.get("s3_secret_key")
            or credentials.get_credential("s3_secret_key")
            or ""
        )
        return S3Storage(
            bucket=bucket,
            access_key=cfg.get("s3_access_key") or os.environ.get("ANTIBROWSER_BACKUP_S3_ACCESS_KEY") or os.environ.get("BACKUP_S3_ACCESS_KEY") or "",
            secret_key=secret,
            endpoint_url=cfg.get("s3_endpoint_url") or os.environ.get("ANTIBROWSER_BACKUP_S3_ENDPOINT_URL") or os.environ.get("BACKUP_S3_ENDPOINT_URL"),
            prefix=cfg.get("s3_prefix") or os.environ.get("ANTIBROWSER_BACKUP_S3_PREFIX") or os.environ.get("BACKUP_S3_PREFIX") or "antibrowser_backups",
            region_name=cfg.get("s3_region") or os.environ.get("ANTIBROWSER_BACKUP_S3_REGION") or os.environ.get("BACKUP_S3_REGION") or "us-east-1",
        )

    raise ValueError(f"No valid backup storage backend configured (current: {backend_type!r})")
