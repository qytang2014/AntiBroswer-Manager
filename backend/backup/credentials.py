"""Secure storage for backup credentials and passwords.

Uses the OS keychain via the `keyring` library, with an automated fallback to a
machine-keyed AES-256-GCM local encrypted store if keyring is unavailable (e.g. headless Linux).
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


def _machine_key() -> bytes:
    """Generate a stable machine-bound key for fallback credential encryption."""
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
        aesgcm = AESGCM(_machine_key())
        decrypted = aesgcm.decrypt(nonce, ciphertext, b"antibrowser_secrets")
        return json.loads(decrypted.decode("utf-8"))
    except Exception as exc:
        logger.warning("Failed to read fallback credentials store: %s", exc)
        return {}


def _save_fallback_store(store: dict[str, str]) -> None:
    path = _fallback_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(store).encode("utf-8")
    nonce = os.urandom(12)
    aesgcm = AESGCM(_machine_key())
    ciphertext = aesgcm.encrypt(nonce, raw, b"antibrowser_secrets")
    path.write_bytes(nonce + ciphertext)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass



def get_credential(key: str) -> str | None:
    """Retrieve a secret credential by key.
    
    Checks the machine-keyed local AES-256-GCM encrypted store first to guarantee
    instantaneous, non-blocking resolution without triggering OS GUI prompts.
    """
    store = _load_fallback_store()
    if key in store and store[key] is not None:
        return store[key]

    try:
        import keyring

        val = keyring.get_password(SERVICE_NAME, key)
        if val is not None:
            return val
    except Exception as exc:
        logger.debug("Keyring get_password failed: %s", exc)

    return None


def set_credential(key: str, value: str) -> None:
    """Store a secret credential in the secure machine-keyed AES-256-GCM store."""
    # Always persist to encrypted machine store first
    store = _load_fallback_store()
    store[key] = value
    _save_fallback_store(store)

    # Best-effort sync to system keychain
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, key, value)
    except Exception as exc:
        logger.debug("Keyring set_password skipped: %s", exc)


def delete_credential(key: str) -> None:
    """Delete a secret credential by key."""
    store = _load_fallback_store()
    if key in store:
        del store[key]
        _save_fallback_store(store)

    try:
        import keyring

        keyring.delete_password(SERVICE_NAME, key)
    except Exception:
        pass


def has_credential(key: str) -> bool:
    """Check if a credential exists and is non-empty."""
    val = get_credential(key)
    return bool(val and val.strip())
