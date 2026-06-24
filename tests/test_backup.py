"""Tests for the encrypted backup / restore module (kanban ``t_32597423``).

Covers the three acceptance criteria from the task body:

1. ``create_backup`` + ``restore_backup`` round-trip reproduces
   the source files byte-for-byte.
2. Restoring with the wrong key raises :class:`WrongKeyError`
   and does NOT overwrite any existing files.
3. The on-disk ``.tar.gz.enc`` file does NOT contain the
   plaintext payload — the raw bytes of a known plaintext
   file are nowhere to be found inside the encrypted archive.

We use a fresh ``tmp_path`` per test and a tmp env var for
the key so nothing leaks into the production logs/ directory.
"""
from __future__ import annotations

import os
import tarfile
from pathlib import Path

import pytest

from ai_billing_audit import backup
from ai_billing_audit.backup import (
    BackupError,
    WrongKeyError,
    create_backup,
    restore_backup,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def fake_source_dir(tmp_path: Path) -> Path:
    """A minimal fake ``logs/`` + ``data/`` pair with one file each.

    The chosen plaintext is distinctive — ``ZORVA_PLAINTEXT_TOKEN``
    — so the "encrypted file doesn't leak plaintext" test can do
    a substring search against the raw bytes of the encrypted
    archive and find nothing.
    """
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    logs.mkdir()
    data.mkdir()
    (logs / "audit.jsonl").write_text(
        '{"event":"audit_complete","id":"ZORVA_PLAINTEXT_TOKEN"}\n'
    )
    (data / "encounters.json").write_text(
        '{"encounter_id":"E1","note":"ZORVA_PLAINTEXT_TOKEN payload"}\n'
    )
    return tmp_path


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> str:
    """A test-only Fernet key, exported into ``ZORVA_BACKUP_KEY``.

    Generating a fresh key per test keeps the encrypted archive
    different across runs (so the "no plaintext" check can't
    accidentally be satisfied by a previous run's output).
    """
    k = backup.generate_key()
    monkeypatch.setenv("ZORVA_BACKUP_KEY", k)
    return k


# ─── 1. round-trip ───────────────────────────────────────────────────────


def test_create_then_restore_round_trip(
    fake_source_dir: Path, key: str, tmp_path: Path
) -> None:
    """Backup → restore reproduces every source file byte-for-byte."""
    archive = tmp_path / "backup.tar.gz.enc"
    summary = create_backup(
        archive,
        source_dirs=[fake_source_dir / "logs", fake_source_dir / "data"],
    )
    # We got something to back up.
    assert summary["files"] >= 2
    assert archive.is_file()
    # Restore into a fresh destination so we can diff cleanly.
    dest = tmp_path / "restored"
    restore_summary = restore_backup(archive, dest_root=dest)
    assert restore_summary["files"] == summary["files"]
    # Every original file has the same content as the restored copy.
    # The tar builder stores files as
    # ``zorva-backup/<root_basename>/<rel>`` so a source at
    # ``<root>/logs/audit.jsonl`` lands at
    # ``<dest>/zorva-backup/logs/audit.jsonl``. The prefix is
    # there so a restore into the project root never pollutes
    # the cwd; operators can ``mv`` the prefix out, or pass
    # ``--strip-prefix`` (v2 follow-up).
    assert (
        (dest / "zorva-backup" / "logs" / "audit.jsonl").read_bytes()
        == (fake_source_dir / "logs" / "audit.jsonl").read_bytes()
    )
    assert (
        (dest / "zorva-backup" / "data" / "encounters.json").read_bytes()
        == (fake_source_dir / "data" / "encounters.json").read_bytes()
    )


def test_create_backup_summarises_files_and_sizes(
    fake_source_dir: Path, key: str, tmp_path: Path
) -> None:
    """The summary dict is well-formed and consistent with the archive."""
    archive = tmp_path / "backup.tar.gz.enc"
    summary = create_backup(
        archive,
        source_dirs=[fake_source_dir / "logs", fake_source_dir / "data"],
    )
    assert summary["files"] >= 2
    assert summary["bytes_in"] > 0
    assert summary["bytes_out"] > 0
    # Encrypted output must not be smaller than the plaintext
    # tar (Fernet adds at least a 16-byte IV + 32-byte HMAC).
    assert summary["bytes_out"] > summary["bytes_in"]


# ─── 2. wrong key ────────────────────────────────────────────────────────


def test_restore_with_wrong_key_raises_wrong_key_error(
    fake_source_dir: Path, key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A different key cannot decrypt the archive."""
    archive = tmp_path / "backup.tar.gz.enc"
    create_backup(
        archive,
        source_dirs=[fake_source_dir / "logs", fake_source_dir / "data"],
    )
    # Swap the env var to a different key.
    monkeypatch.setenv("ZORVA_BACKUP_KEY", backup.generate_key())
    with pytest.raises(WrongKeyError):
        restore_backup(archive, dest_root=tmp_path / "restored")


def test_restore_with_wrong_key_does_not_overwrite(
    fake_source_dir: Path, key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wrong-key failure leaves the destination directory untouched.

    A restore that "succeeds" by writing nothing (because Fernet
    raised) is fine, but if any prior implementation were to
    catch the exception silently and write a partial extraction,
    existing files would be clobbered. This test pins the
    no-write-on-error contract by placing a sentinel file in
    the destination and asserting it survives.
    """
    archive = tmp_path / "backup.tar.gz.enc"
    create_backup(
        archive,
        source_dirs=[fake_source_dir / "logs", fake_source_dir / "data"],
    )
    dest = tmp_path / "restored"
    dest.mkdir()
    sentinel = dest / "do_not_clobber.txt"
    sentinel.write_text("untouched")
    monkeypatch.setenv("ZORVA_BACKUP_KEY", backup.generate_key())
    with pytest.raises(WrongKeyError):
        restore_backup(archive, dest_root=dest)
    assert sentinel.read_text() == "untouched"


# ─── 3. encrypted file does not leak plaintext ──────────────────────────


def test_encrypted_archive_does_not_contain_plaintext(
    fake_source_dir: Path, key: str, tmp_path: Path
) -> None:
    """Raw bytes of the encrypted file contain no plaintext payload."""
    archive = tmp_path / "backup.tar.gz.enc"
    create_backup(
        archive,
        source_dirs=[fake_source_dir / "logs", fake_source_dir / "data"],
    )
    raw = archive.read_bytes()
    # Both source files contain this token; if any of them appears
    # in the encrypted output, the encryption isn't actually
    # happening (or it's a degenerate no-op cipher).
    assert b"ZORVA_PLAINTEXT_TOKEN" not in raw
    # Filenames in the source tree must not leak either; the
    # arcname lives only inside the tarball (which is encrypted).
    assert b"audit.jsonl" not in raw
    assert b"encounters.json" not in raw


def test_encrypted_archive_is_not_a_plain_gzip(
    fake_source_dir: Path, key: str, tmp_path: Path
) -> None:
    """The encrypted file is not readable as a plain ``tar.gz``.

    A subtle bug — forgetting to encrypt and just writing the
    tarball bytes — would pass the round-trip test if the
    archive ends in ``.enc`` by coincidence. Pin the
    encryption is happening by asserting the file cannot be
    opened as a tar.gz (Fernet's output starts with
    ``gAAA...`` / ``\\x80\\x00...`` in the worst case and is
    never a valid gzip header).
    """
    archive = tmp_path / "backup.tar.gz.enc"
    create_backup(
        archive,
        source_dirs=[fake_source_dir / "logs", fake_source_dir / "data"],
    )
    raw = archive.read_bytes()
    with pytest.raises(tarfile.ReadError):
        # tarfile needs a file-like object; BytesIO works.
        import io as _io

        tarfile.open(fileobj=_io.BytesIO(raw), mode="r:gz")


# ─── Key handling ────────────────────────────────────────────────────────


def test_missing_key_raises_backup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """No key + no env var → :class:`BackupError`."""
    monkeypatch.delenv("ZORVA_BACKUP_KEY", raising=False)
    with pytest.raises(BackupError):
        create_backup("/tmp/should-not-exist.tar.gz.enc", source_dirs=["/tmp"])


def test_passphrase_derives_to_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A passphrase can be used instead of a raw Fernet key.

    Two callers using the same passphrase must be able to
    decrypt each other's archives. This is the operator-friendlier
    flow (you can store ``ZORVA_BACKUP_KEY="hunter2"`` in a vault
    without dealing with the urlsafe-base64 Fernet format).
    """
    monkeypatch.setenv("ZORVA_BACKUP_KEY", "my-shared-passphrase-12345")
    blob = backup._load_key()
    # Same passphrase → same derived key.
    assert backup._load_key() == blob
    # And the derived key decrypts correctly with Fernet.
    from cryptography.fernet import Fernet

    token = Fernet(blob).encrypt(b"hello world")
    assert Fernet(blob).decrypt(token) == b"hello world"


# ─── CLI smoke ───────────────────────────────────────────────────────────


def test_cli_create_and_restore(
    fake_source_dir: Path, key: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``python -m ai_billing_audit.backup create ...`` and ``restore ...`` work."""
    archive = tmp_path / "cli_backup.tar.gz.enc"
    rc = backup.main(
        [
            "create",
            str(archive),
            "--source",
            str(fake_source_dir / "logs"),
            "--source",
            str(fake_source_dir / "data"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "backup created" in out
    dest = tmp_path / "cli_restored"
    rc = backup.main(
        [
            "restore",
            str(archive),
            "--dest",
            str(dest),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "restore complete" in out
    # Sanity: the round-trip extracted at least our two files.
    extracted = sorted(p.name for p in dest.rglob("*") if p.is_file())
    assert "audit.jsonl" in extracted
    assert "encounters.json" in extracted


def test_cli_gen_key_prints_fernet_key(capsys: pytest.CaptureFixture[str]) -> None:
    """``python -m ai_billing_audit.backup gen-key`` prints a fresh key."""
    rc = backup.main(["gen-key"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    # Fernet.generate_key() returns 44-char urlsafe-base64.
    assert len(out) == 44
    # And it's a valid Fernet key (i.e. round-trips through Fernet).
    from cryptography.fernet import Fernet

    Fernet(out.encode("ascii"))  # raises if invalid