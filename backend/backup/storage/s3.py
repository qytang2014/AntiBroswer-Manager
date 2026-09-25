"""Amazon S3 and S3-compatible (MinIO, R2, OpenList) storage backend implementation."""

from __future__ import annotations

import asyncio
import datetime
import logging
import re
from pathlib import Path
from typing import Any, Callable

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError

from . import BackupStorage

logger = logging.getLogger("cloakbrowser.manager.backup.s3")


class S3Storage(BackupStorage):
    """S3 storage backend supporting AWS S3, Cloudflare R2, MinIO, and OpenList S3."""

    def __init__(
        self,
        bucket: str,
        access_key: str = "",
        secret_key: str = "",
        endpoint_url: str | None = None,
        prefix: str = "antibrowser_backups",
        region_name: str = "us-east-1",
    ):
        self.bucket = bucket.strip()
        self.access_key = access_key
        self.secret_key = secret_key
        self.endpoint_url = endpoint_url.strip() if endpoint_url and endpoint_url.strip() else None
        clean_prefix = prefix.strip("/")
        self.prefix = f"{clean_prefix}/" if clean_prefix else ""
        self.region_name = region_name or "us-east-1"

    def _get_client(self):
        config = Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=15,
            read_timeout=60,
        )
        kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": self.region_name,
            "config": config,
        }
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.access_key and self.secret_key:
            kwargs["aws_access_key_id"] = self.access_key
            kwargs["aws_secret_access_key"] = self.secret_key
        return boto3.client(**kwargs)

    def _get_key(self, filename: str) -> str:
        return f"{self.prefix}{filename.lstrip('/')}"

    async def test_connection(self) -> tuple[bool, str | None]:
        def _check():
            s3 = self._get_client()
            try:
                s3.head_bucket(Bucket=self.bucket)
                return True, None
            except ClientError as exc:
                err_code = exc.response.get("Error", {}).get("Code", "")
                if err_code in ("404", "NoSuchBucket"):
                    # Attempt to create the bucket if allowed
                    try:
                        create_kwargs: dict[str, Any] = {"Bucket": self.bucket}
                        if self.region_name and self.region_name != "us-east-1":
                            create_kwargs["CreateBucketConfiguration"] = {
                                "LocationConstraint": self.region_name
                            }
                        s3.create_bucket(**create_kwargs)
                        return True, None
                    except Exception as create_exc:
                        return False, f"Bucket '{self.bucket}' does not exist and could not be created: {create_exc}"
                if err_code in ("403", "AccessDenied", "InvalidAccessKeyId"):
                    return False, f"S3 Access Denied: invalid credentials or insufficient permissions ({err_code})"
                return False, f"S3 Error ({err_code}): {exc}"
            except EndpointConnectionError as exc:
                return False, f"Cannot connect to S3 endpoint: {exc}"
            except Exception as exc:
                return False, f"S3 Connection failed: {exc}"

        return await asyncio.to_thread(_check)

    async def upload_file(
        self,
        local_path: Path,
        remote_filename: str,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> None:
        if not local_path.is_file():
            raise FileNotFoundError(f"Local file not found: {local_path}")

        key = self._get_key(remote_filename)
        file_size = local_path.stat().st_size

        if progress_callback:
            progress_callback(10, f"Uploading {remote_filename} to S3...")

        def _upload():
            s3 = self._get_client()
            s3.upload_file(str(local_path), self.bucket, key)

        await asyncio.to_thread(_upload)

        if progress_callback:
            progress_callback(100, f"Uploaded {remote_filename} ({file_size} bytes) successfully")

    async def download_file(
        self,
        remote_filename: str,
        local_path: Path,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        key = self._get_key(remote_filename)

        if progress_callback:
            progress_callback(10, f"Downloading {remote_filename} from S3...")

        def _download():
            s3 = self._get_client()
            s3.download_file(self.bucket, key, str(local_path))

        await asyncio.to_thread(_download)

        if progress_callback:
            progress_callback(100, f"Downloaded {remote_filename} successfully")

    async def list_backups(self) -> list[dict[str, Any]]:
        def _list():
            s3 = self._get_client()
            paginator = s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket, Prefix=self.prefix)

            all_entries: dict[str, dict[str, Any]] = {}
            sidecars: set[str] = set()

            for page in pages:
                for obj in page.get("Contents", []):
                    full_key = obj.get("Key", "")
                    filename = full_key[len(self.prefix):] if full_key.startswith(self.prefix) else full_key

                    if filename.endswith(".sha256"):
                        sidecars.add(filename[:-7])
                    elif filename.startswith("antibrowser-backup-") and (
                        filename.endswith(".tar.gz") or filename.endswith(".tar.gz.enc")
                    ):
                        is_encrypted = filename.endswith(".enc")
                        mode = "full" if "-full." in filename else "config"
                        last_modified = obj.get("LastModified")
                        created_iso = (
                            last_modified.isoformat()
                            if isinstance(last_modified, datetime.datetime)
                            else datetime.datetime.now(datetime.timezone.utc).isoformat()
                        )

                        # Parse timestamp from filename if available
                        time_match = re.search(r"antibrowser-backup-(\d{8})-(\d{6})", filename)
                        if time_match:
                            try:
                                dt = datetime.datetime.strptime(
                                    f"{time_match.group(1)}{time_match.group(2)}",
                                    "%Y%m%d%H%M%S",
                                ).replace(tzinfo=datetime.timezone.utc)
                                created_iso = dt.isoformat()
                            except Exception:
                                pass

                        all_entries[filename] = {
                            "name": filename,
                            "size_bytes": obj.get("Size", 0),
                            "created_at": created_iso,
                            "mode": mode,
                            "encrypted": is_encrypted,
                            "checksum": None,
                        }

            for base_name, item in all_entries.items():
                if base_name in sidecars:
                    item["checksum"] = "present"

            backups = list(all_entries.values())
            backups.sort(key=lambda x: x["created_at"], reverse=True)
            return backups

        return await asyncio.to_thread(_list)

    async def delete_file(self, remote_filename: str) -> None:
        key = self._get_key(remote_filename)
        sidecar_key = self._get_key(remote_filename + ".sha256")

        def _delete():
            s3 = self._get_client()
            s3.delete_object(Bucket=self.bucket, Key=key)
            try:
                s3.delete_object(Bucket=self.bucket, Key=sidecar_key)
            except Exception:
                pass

        await asyncio.to_thread(_delete)

    async def apply_retention(self, retain_count: int) -> list[str]:
        if retain_count <= 0:
            return []
        backups = await self.list_backups()
        if len(backups) <= retain_count:
            return []

        to_delete = backups[retain_count:]
        deleted = []
        for item in to_delete:
            try:
                await self.delete_file(item["name"])
                deleted.append(item["name"])
            except Exception as exc:
                logger.warning("Failed to delete S3 backup %s: %s", item["name"], exc)
        return deleted
