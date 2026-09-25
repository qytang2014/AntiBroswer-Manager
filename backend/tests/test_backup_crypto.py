"""Tests for backup cryptographic operations and SHA-256 integrity checks."""

import tempfile
from pathlib import Path
import pytest

from backend.backup import crypto


def test_sha256_computation_and_verification(tmp_path: Path):
    test_file = tmp_path / "sample.txt"
    test_file.write_text("AntiBrowser Manager Backup Test Content", encoding="utf-8")

    digest = crypto.compute_sha256(test_file)
    assert len(digest) == 64
    assert crypto.verify_sha256(test_file, digest)
    assert crypto.verify_sha256(test_file, f"{digest}  sample.txt\n")

    # Tampered content should fail verification
    assert not crypto.verify_sha256(test_file, "a" * 64)


def test_aes_gcm_encryption_and_decryption_roundtrip(tmp_path: Path):
    src_file = tmp_path / "data.tar.gz"
    src_file.write_bytes(b"Compressed archive binary contents" * 100)

    enc_file = tmp_path / "data.tar.gz.enc"
    dec_file = tmp_path / "data_restored.tar.gz"

    password = "SuperSecurePassword2026!"

    # Use smaller iterations for fast unit test
    crypto.encrypt_file(src_file, enc_file, password, iterations=1000)
    assert enc_file.exists()
    assert enc_file.stat().st_size > src_file.stat().st_size

    # Verify header magic
    with open(enc_file, "rb") as f:
        magic = f.read(4)
        assert magic == crypto.MAGIC

    # Decrypt with correct password
    crypto.decrypt_file(enc_file, dec_file, password, iterations=1000)
    assert dec_file.read_bytes() == src_file.read_bytes()


def test_decrypt_with_wrong_password_fails(tmp_path: Path):
    src_file = tmp_path / "data.tar.gz"
    src_file.write_bytes(b"Secret browser profiles data")

    enc_file = tmp_path / "data.tar.gz.enc"
    dec_file = tmp_path / "restored.tar.gz"

    crypto.encrypt_file(src_file, enc_file, "correct_pass", iterations=1000)

    with pytest.raises(crypto.DecryptionError, match="incorrect password or corrupted"):
        crypto.decrypt_file(enc_file, dec_file, "wrong_pass", iterations=1000)


def test_decrypt_corrupted_file_fails(tmp_path: Path):
    src_file = tmp_path / "data.tar.gz"
    src_file.write_bytes(b"Secret browser profiles data")

    enc_file = tmp_path / "data.tar.gz.enc"
    dec_file = tmp_path / "restored.tar.gz"

    crypto.encrypt_file(src_file, enc_file, "correct_pass", iterations=1000)

    # Tamper with the ciphertext
    data = bytearray(enc_file.read_bytes())
    data[-5] ^= 0xFF
    enc_file.write_bytes(data)

    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_file(enc_file, dec_file, "correct_pass", iterations=1000)


def test_decrypt_invalid_header_fails(tmp_path: Path):
    invalid_file = tmp_path / "invalid.enc"
    invalid_file.write_bytes(b"NOT_A_VALID_HEADER" + b"\x00" * 100)

    with pytest.raises(crypto.DecryptionError, match="Invalid file header"):
        crypto.decrypt_file(invalid_file, tmp_path / "out", "pass")
