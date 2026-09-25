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

    cfg = config or load_settings().get("backup", {})
    backend_type = cfg.get("backend")

    if backend_type == "webdav":
        url = cfg.get("webdav_url")
        if not url:
            raise ValueError("WebDAV URL is not configured")
        pwd = cfg.get("webdav_password") or credentials.get_credential("webdav_password") or ""
        return WebDAVStorage(
            url=url,
            username=cfg.get("webdav_username", ""),
            password=pwd,
            remote_path=cfg.get("webdav_remote_path", "/antibrowser_backups"),
            skip_ssl_verify=bool(cfg.get("webdav_skip_ssl", False)),
        )

    if backend_type == "s3":
        bucket = cfg.get("s3_bucket")
        if not bucket:
            raise ValueError("S3 Bucket name is not configured")
        secret = cfg.get("s3_secret_key") or credentials.get_credential("s3_secret_key") or ""
        return S3Storage(
            bucket=bucket,
            access_key=cfg.get("s3_access_key", ""),
            secret_key=secret,
            endpoint_url=cfg.get("s3_endpoint_url"),
            prefix=cfg.get("s3_prefix", "antibrowser_backups"),
            region_name=cfg.get("s3_region", "us-east-1"),
        )

    raise ValueError(f"No valid backup storage backend configured (current: {backend_type!r})")
