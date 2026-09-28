"""Secure storage for backup credentials and passwords.

Uses a local machine-isolated AES-256-GCM encrypted store with a 256-bit
secure master key (file permissions 0600) located in the manager data directory.
This ensures instantaneous, non-blocking resolution without triggering OS GUI prompts
(such as macOS Keychain authorization modals).
"""

from __future__ import annotations

import json
import logging
import os
import platform
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ..runtime import resolve_runtime

logger = logging.getLogger("cloakbrowser.manager.backup.credentials")

SERVICE_NAME = "antibrowser.backup"


def _fallback_file_path() -> Path:
    return resolve_runtime().data_dir / ".backup_secrets.enc"


def _master_key_file_path() -> Path:
    return resolve_runtime().data_dir / ".secret_key"


def _get_or_create_master_key() -> bytes:
    """Retrieve or generate a 32-byte AES-256 master key."""
    path = _master_key_file_path()
    if path.is_file():
        try:
            key = path.read_bytes()
            if len(key) == 32:
                return key
        except Exception as exc:
            logger.warning("Failed to read master key from %s: %s", path, exc)

    # Generate cryptographically secure 256-bit random key
    key = os.urandom(32)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception as exc:
        logger.error("Failed to write master key to %s: %s", path, exc)

    return key


def _machine_key() -> bytes:
    """Generate the legacy machine-bound key for fallback credential migration."""
    node_id = str(uuid.getnode())
    system_info = f"{platform.node()}-{platform.system()}-{platform.machine()}"
    raw = f"{node_id}:{system_info}:antibrowser_backup_salt_2026".encode("utf-8")
    salt = b"antibrowser_machine_salt_v1"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=50_000,
    )
    return kdf.derive(raw)


def _load_fallback_store() -> dict[str, str]:
    path = _fallback_file_path()
    if not path.is_file():
        return {}
    try:
        data = path.read_bytes()
        if len(data) < 28:
            return {}
        nonce = data[:12]
        ciphertext = data[12:]

        # 1. Try decrypting with master key
        try:
            aesgcm = AESGCM(_get_or_create_master_key())
            decrypted = aesgcm.decrypt(nonce, ciphertext, b"antibrowser_secrets")
            return json.loads(decrypted.decode("utf-8"))
        except Exception:
            pass

        # 2. Try legacy machine key for backward-compatible migration
        try:
            aesgcm = AESGCM(_machine_key())
            decrypted = aesgcm.decrypt(nonce, ciphertext, b"antibrowser_secrets")
            store = json.loads(decrypted.decode("utf-8"))
            # Upgrade in-place to master key
            _save_fallback_store(store)
            return store
        except Exception:
            pass

        logger.debug("Could not decrypt existing backup secrets store; returning empty.")
        return {}
    except Exception as exc:
        logger.warning("Failed to read fallback credentials store: %s", exc)
        return {}


def _save_fallback_store(store: dict[str, str]) -> None:
    path = _fallback_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(store).encode("utf-8")
    nonce = os.urandom(12)
    aesgcm = AESGCM(_get_or_create_master_key())
    ciphertext = aesgcm.encrypt(nonce, raw, b"antibrowser_secrets")
    path.write_bytes(nonce + ciphertext)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def get_credential(key: str) -> str | None:
    """Retrieve a secret credential by key from local encrypted store."""
    store = _load_fallback_store()
    return store.get(key)


def set_credential(key: str, value: str) -> None:
    """Store a secret credential in the secure machine-keyed AES-256-GCM store."""
    store = _load_fallback_store()
    store[key] = value
    _save_fallback_store(store)


def delete_credential(key: str) -> None:
    """Delete a secret credential by key."""
    store = _load_fallback_store()
    if key in store:
        del store[key]
        _save_fallback_store(store)


def has_credential(key: str) -> bool:
    """Check if a credential exists and is non-empty."""
    val = get_credential(key)
    return bool(val and val.strip())
