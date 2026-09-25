"""Cryptographic utilities for backup encryption, decryption, and integrity verification.

Implements AES-256-GCM encryption with PBKDF2-HMAC-SHA256 key derivation and SHA-256
sidecar checksum calculations.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

MAGIC = b"ABKE"  # AntiBrowser Encrypted
VERSION = 0x01
SALT_LENGTH = 32
NONCE_LENGTH = 12
TAG_LENGTH = 16
HEADER_LENGTH = len(MAGIC) + 1 + SALT_LENGTH + NONCE_LENGTH + TAG_LENGTH  # 4 + 1 + 32 + 12 + 16 = 65 bytes
KDF_ITERATIONS = 600_000


class CryptoError(Exception):
    """Base exception for backup cryptographic operations."""


class DecryptionError(CryptoError):
    """Raised when backup decryption fails (e.g. invalid password or corrupted data)."""


class IntegrityError(CryptoError):
    """Raised when backup integrity verification fails (e.g. SHA-256 mismatch)."""


def derive_key(password: str, salt: bytes, iterations: int = KDF_ITERATIONS) -> bytes:
    """Derive a 256-bit AES key from a password string and salt using PBKDF2-HMAC-SHA256."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(password.encode("utf-8"))


def compute_sha256(file_path: Path) -> str:
    """Compute the SHA-256 hex digest of a file in streaming chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_sha256(file_path: Path, expected_sha256: str) -> bool:
    """Verify that a file matches the expected SHA-256 hex digest."""
    clean_expected = expected_sha256.strip().split()[0].lower()
    actual = compute_sha256(file_path).lower()
    return actual == clean_expected


def encrypt_file(
    src_path: Path,
    dest_path: Path,
    password: str,
    iterations: int = KDF_ITERATIONS,
) -> None:
    """Encrypt a file using AES-256-GCM and write the output file with ABKE header."""
    if not password:
        raise ValueError("Encryption password cannot be empty")

    salt = os.urandom(SALT_LENGTH)
    nonce = os.urandom(NONCE_LENGTH)
    key = derive_key(password, salt, iterations=iterations)
    aesgcm = AESGCM(key)

    aad = MAGIC + bytes([VERSION]) + salt + nonce

    with open(src_path, "rb") as f_in:
        plaintext = f_in.read()

    ciphertext_and_tag = aesgcm.encrypt(nonce, plaintext, aad)
    tag = ciphertext_and_tag[-TAG_LENGTH:]
    ciphertext = ciphertext_and_tag[:-TAG_LENGTH]

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f_out:
        f_out.write(MAGIC)
        f_out.write(bytes([VERSION]))
        f_out.write(salt)
        f_out.write(nonce)
        f_out.write(tag)
        f_out.write(ciphertext)


def decrypt_file(
    src_path: Path,
    dest_path: Path,
    password: str,
    iterations: int = KDF_ITERATIONS,
) -> None:
    """Decrypt an ABKE encrypted file using AES-256-GCM.

    Raises:
        DecryptionError: if magic is invalid, version is unsupported, or password/tag verification fails.
    """
    if not password:
        raise DecryptionError("Decryption password cannot be empty")

    file_size = src_path.stat().st_size
    if file_size < HEADER_LENGTH:
        raise DecryptionError(f"File is too small to be a valid encrypted backup ({file_size} bytes)")

    with open(src_path, "rb") as f_in:
        magic = f_in.read(len(MAGIC))
        if magic != MAGIC:
            raise DecryptionError("Invalid file header: not an AntiBrowser encrypted backup file")

        version_byte = f_in.read(1)
        if len(version_byte) != 1 or version_byte[0] != VERSION:
            raise DecryptionError(f"Unsupported backup encryption version: {version_byte!r}")

        salt = f_in.read(SALT_LENGTH)
        nonce = f_in.read(NONCE_LENGTH)
        tag = f_in.read(TAG_LENGTH)
        ciphertext = f_in.read()

    aad = MAGIC + bytes([VERSION]) + salt + nonce
    ciphertext_and_tag = ciphertext + tag

    key = derive_key(password, salt, iterations=iterations)
    aesgcm = AESGCM(key)

    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext_and_tag, aad)
    except InvalidTag as exc:
        raise DecryptionError("Decryption failed: incorrect password or corrupted backup package") from exc
    except Exception as exc:
        raise DecryptionError(f"Decryption error: {exc}") from exc

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f_out:
        f_out.write(plaintext)
