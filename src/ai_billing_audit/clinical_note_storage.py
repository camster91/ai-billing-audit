"""Encrypted-at-rest storage for uploaded clinical notes."""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class PhiStorageConfigurationError(RuntimeError):
    """Raised when PHI storage cannot be configured safely."""


class PhiStorageIntegrityError(RuntimeError):
    """Raised when persisted PHI cannot be authenticated or decrypted."""


def _cipher() -> Fernet:
    key = os.environ.get("ZORVA_PHI_ENCRYPTION_KEY", "").strip()
    if not key:
        raise PhiStorageConfigurationError(
            "ZORVA_PHI_ENCRYPTION_KEY is required for clinical-note storage"
        )
    try:
        return Fernet(key.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise PhiStorageConfigurationError(
            "ZORVA_PHI_ENCRYPTION_KEY must be a valid Fernet key"
        ) from exc


def store_clinical_note(path: Path, plaintext: bytes) -> None:
    """Encrypt and persist a clinical note."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encrypt_phi(plaintext))


def load_clinical_note(path: Path) -> bytes:
    """Read and decrypt a stored clinical note."""
    return decrypt_phi(path.read_bytes())


def encrypt_phi(plaintext: bytes) -> bytes:
    """Encrypt a PHI-bearing payload with the configured key."""
    return _cipher().encrypt(plaintext)


def decrypt_phi(ciphertext: bytes) -> bytes:
    """Decrypt a PHI-bearing payload with the configured key."""
    try:
        return _cipher().decrypt(ciphertext)
    except InvalidToken as exc:
        raise PhiStorageIntegrityError(
            "persisted PHI is plaintext, corrupt, or encrypted with another key"
        ) from exc


def phi_encryption_configured() -> bool:
    """Return whether the configured PHI key is present and valid."""
    try:
        _cipher()
    except PhiStorageConfigurationError:
        return False
    return True


def append_encrypted_json_record(path: Path, record: dict[str, Any]) -> None:
    """Append one authenticated JSON object without exposing plaintext at rest."""
    plaintext = json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    token = encrypt_phi(plaintext)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(token + b"\n")


def read_encrypted_json_records(path: Path) -> list[dict[str, Any]]:
    """Authenticate and decode every encrypted JSON object in ``path``."""
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for raw_line in handle:
            token = raw_line.strip()
            if not token:
                continue
            try:
                record = json.loads(decrypt_phi(token))
            except json.JSONDecodeError as exc:
                raise PhiStorageIntegrityError(
                    "encrypted PHI log contains an invalid JSON record"
                ) from exc
            if not isinstance(record, dict):
                raise PhiStorageIntegrityError(
                    "encrypted PHI log record must be a JSON object"
                )
            records.append(record)
    return records


def write_encrypted_json_records(path: Path, records: list[dict[str, Any]]) -> None:
    """Atomically replace ``path`` with authenticated encrypted JSON records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    replacement = path.with_name(path.name + ".encrypted.tmp")
    try:
        with replacement.open("wb") as handle:
            for record in records:
                plaintext = json.dumps(
                    record,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                handle.write(encrypt_phi(plaintext) + b"\n")
        replacement.replace(path)
    finally:
        if replacement.exists():
            replacement.unlink()


def migrate_plaintext_jsonl(path: Path) -> int:
    """Replace a legacy plaintext JSONL file with encrypted records and backup."""
    if not path.is_file():
        return 0
    original = path.read_bytes()
    lines = [line for line in original.splitlines() if line.strip()]
    if not lines:
        return 0
    try:
        decrypt_phi(lines[0])
    except PhiStorageIntegrityError:
        pass
    else:
        read_encrypted_json_records(path)
        return 0

    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PhiStorageIntegrityError(
                "legacy PHI log contains invalid JSON"
            ) from exc
        if not isinstance(record, dict):
            raise PhiStorageIntegrityError(
                "legacy PHI log record must be a JSON object"
            )
        records.append(record)

    backup = path.with_suffix(path.suffix + ".plaintext.bak.enc")
    if backup.exists():
        raise PhiStorageIntegrityError("encrypted plaintext backup already exists")
    backup.write_bytes(encrypt_phi(original))

    write_encrypted_json_records(path, records)
    return len(records)
