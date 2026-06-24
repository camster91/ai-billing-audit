"""Encrypted backup + restore for Zorva logs and data (kanban ``t_32597423``).

Two concerns live in this module:

1. **Backup.** :func:`create_backup` walks the on-disk log + data
   directories, bundles them into a single ``tar.gz`` in memory,
   then encrypts that archive with a symmetric key derived from
   the ``ZORVA_BACKUP_KEY`` environment variable. The output is a
   single ``.tar.gz.enc`` file suitable for off-site storage (S3,
   rsync target, etc.).

2. **Restore.** :func:`restore_backup` decrypts the archive with
   the same key and extracts it under a target root (default:
   the project root, so ``logs/`` and ``data/`` land where the
   rest of the app reads them).

Design choices
--------------
* **Fernet** (AES-128-CBC + HMAC-SHA256) from :mod:`cryptography`
  is used because it bundles authenticated encryption with a
  clean key-rotation story (a bad key raises
  ``InvalidToken`` — see :func:`_load_key`). The raw ``Fernet``
  key (44-char urlsafe-base64) can be passed directly via
  ``ZORVA_BACKUP_KEY``, or you can pass a passphrase which we
  hash with SHA-256 to derive the key (useful when the key is
  shared in a vault that only stores text passphrases).

* **The encrypted file is opaque.** Plaintext bytes — including
  the filenames of the bundled entries — never appear in the
  output, so a leak of the backup file alone is not enough to
  reconstruct the log directory layout.

* **CLI.** Running ``python -m ai_billing_audit.backup`` with
  no args prints help. ``create <out>`` writes the backup;
  ``restore <archive>`` decodes + extracts it.

What ships
----------
* This module (the implementation + CLI).
* :file:`tests/test_backup.py` with a round-trip test, a
  wrong-key rejection test, and a plaintext-leak test.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import logging
import os
import sys
import tarfile
from pathlib import Path
from typing import Iterable

from cryptography.fernet import Fernet, InvalidToken

__all__ = [
    "create_backup",
    "restore_backup",
    "BackupError",
    "WrongKeyError",
]

_log = logging.getLogger(__name__)


# Default source paths inside the container. The deployment
# layout is /app/logs/*.jsonl + /app/data/*.json; tests + the
# CLI override via ``source_dirs=`` or ``ZORVA_BACKUP_SOURCES``
# (colon-separated) so they can use tmp_path.
_DEFAULT_SOURCE_DIRS: tuple[str, ...] = ("/app/logs", "/app/data")


def _resolve_source_dirs(
    source_dirs: Iterable[str | Path] | None,
) -> list[str | Path]:
    """Resolve the source-dir list from explicit args + env var.

    Resolution order (later wins):

    1. The module default (``/app/logs``, ``/app/data``).
    2. The ``ZORVA_BACKUP_SOURCES`` env var (colon-separated
       absolute paths) — convenient for operators who mount
       logs at a non-default path inside their container.
    3. The explicit ``source_dirs`` argument passed to
       :func:`create_backup`.
    """
    out: list[str | Path] = list(_DEFAULT_SOURCE_DIRS)
    env_raw = os.environ.get("ZORVA_BACKUP_SOURCES")
    if env_raw:
        out = [p for p in env_raw.split(":") if p]
    if source_dirs is not None:
        out = list(source_dirs)
    return out


class BackupError(Exception):
    """Base class for backup / restore failures."""


class WrongKeyError(BackupError):
    """Raised when the supplied key cannot decrypt the archive.

    We keep this distinct from the underlying ``InvalidToken``
    so callers (and tests) can match on the cause without
    importing :mod:`cryptography`.
    """


# ─── Key handling ────────────────────────────────────────────────────────


def _load_key(key: str | None = None) -> bytes:
    """Return a 32-byte urlsafe-base64 Fernet key.

    Resolution order:

    1. The explicit ``key`` argument (used by tests + the CLI).
    2. The ``ZORVA_BACKUP_KEY`` environment variable.
    3. Raise :class:`BackupError` if neither is set.

    Accepts either a raw Fernet key (``Fernet.generate_key()``
    output) or a passphrase; passphrases are hashed with
    SHA-256 and the digest is urlsafe-base64-encoded into a
    Fernet-compatible key. The two shapes are
    self-distinguishing: a raw Fernet key is 44 chars ending
    in ``=``; anything else is treated as a passphrase.
    """
    raw = (key or os.environ.get("ZORVA_BACKUP_KEY") or "").strip()
    if not raw:
        raise BackupError(
            "ZORVA_BACKUP_KEY is not set; export it or pass key= explicitly"
        )
    # Raw Fernet keys are 44-char urlsafe-base64 strings
    # (32 bytes => 43 chars + 1 padding char). We try to
    # decode it; if decoding succeeds AND the decoded length
    # is 32, we treat it as a raw key. Otherwise we hash it.
    try:
        decoded = base64.urlsafe_b64decode(raw)
        if len(decoded) == 32:
            return raw.encode("ascii")
    except (ValueError, TypeError, base64.binascii.Error):  # type: ignore[attr-defined]
        pass
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def generate_key() -> str:
    """Return a fresh, random Fernet key as a string.

    Helper for operators who need to rotate the key — the
    output can be dropped straight into the ``ZORVA_BACKUP_KEY``
    environment variable. The string is url-safe so it can
    be copy-pasted without quoting.
    """
    return Fernet.generate_key().decode("ascii")


# ─── Source / archive helpers ────────────────────────────────────────────


def _iter_source_files(source_dirs: Iterable[str | Path]) -> list[tuple[Path, Path]]:
    """Collect every regular file under ``source_dirs``.

    Returns a list of ``(root, file_path)`` tuples so the tar
    builder can preserve the relative layout (a file at
    ``<root>/sub/foo.json`` is stored as ``<root>/sub/foo.json``).

    Missing directories are skipped silently — a fresh deploy
    may not have any ``/app/data/*.json`` yet, and we don't
    want backup to fail in that case. Symlinks are followed
    once (we're a backup, not a filesystem walker).
    """
    pairs: list[tuple[Path, Path]] = []
    for raw in source_dirs:
        root = Path(raw)
        if not root.exists():
            _log.warning("backup: source dir %s does not exist; skipping", root)
            continue
        if root.is_file():
            pairs.append((root.parent, root))
            continue
        for p in root.rglob("*"):
            if p.is_file() and not p.name.startswith("."):
                pairs.append((root, p))
    # Stable order: backup reproducibility + deterministic tests.
    pairs.sort(key=lambda rp: str(rp[1]))
    return pairs


def _tar_bytes(
    pairs: Iterable[tuple[Path, Path]], *, arcname_root: str = "zorva-backup"
) -> bytes:
    """Bundle ``(root, file_path)`` pairs into an in-memory ``tar.gz``.

    Each entry is stored under
    ``<arcname_root>/<root_basename>/<relative-to-root>`` so the
    extracted tree mirrors the source layout but is clearly
    tagged as a Zorva backup. On restore, callers can then
    extract under the project root and the files land under
    ``logs/`` and ``data/`` exactly where the running app
    reads them.

    Both ``root`` and ``file_path`` are resolved to handle
    macOS's ``/tmp`` -> ``/private/tmp`` symlink (without
    resolution, ``relative_to`` raises because the resolved
    file is outside the unresolved root).
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for root, path in pairs:
            resolved_root = root.resolve()
            resolved_path = path.resolve()
            try:
                rel = resolved_path.relative_to(resolved_root)
            except ValueError:
                # File outside its declared root (shouldn't
                # happen with rglob, but a paranoid fallback
                # is cheap). Use the basename; the worst case
                # is a flat file at the archive root.
                rel = Path(resolved_path.name)
            arcname = f"{arcname_root}/{resolved_root.name}/{rel}"
            tar.add(str(resolved_path), arcname=arcname, recursive=False)
    return buf.getvalue()


def _untar_bytes(blob: bytes, *, dest_root: str | Path) -> int:
    """Extract ``blob`` (a ``tar.gz``) under ``dest_root``.

    Returns the number of regular files written. Path-traversal
    entries (members whose arcname contains ``..`` or an
    absolute path) are rejected to keep a malicious archive
    from writing outside ``dest_root``.
    """
    dest_root = Path(dest_root).resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            # Reject anything that escapes dest_root. tarfile
            # normalises paths on extract but we belt-and-brace
            # because the cost of skipping is tiny and the cost
            # of a traversal is filesystem-level damage.
            target = (dest_root / member.name).resolve()
            try:
                target.relative_to(dest_root)
            except ValueError:
                _log.warning(
                    "restore: skipping path-traversal entry %r", member.name
                )
                continue
            if member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                target.write_bytes(extracted.read())
                count += 1
            elif member.isdir():
                target.mkdir(parents=True, exist_ok=True)
    return count


# ─── Public API ──────────────────────────────────────────────────────────


def create_backup(
    output_path: str | Path,
    *,
    source_dirs: Iterable[str | Path] | None = None,
    key: str | None = None,
) -> dict[str, int]:
    """Encrypt-and-write a backup of ``source_dirs`` to ``output_path``.

    Parameters
    ----------
    output_path:
        Path the encrypted ``.tar.gz.enc`` archive is written to.
        The parent directory is created if needed.
    source_dirs:
        Iterable of root paths to bundle. ``None`` (the default)
        uses the production layout (``/app/logs``, ``/app/data``).
    key:
        Optional Fernet key or passphrase. ``None`` (the default)
        reads ``ZORVA_BACKUP_KEY``.

    Returns
    -------
    A summary dict ``{"files": N, "bytes_in": M, "bytes_out": K}``
    suitable for logging. ``files`` is the number of source
    files bundled; ``bytes_in`` is the plaintext tarball size
    (pre-encryption); ``bytes_out`` is the on-disk size.
    """
    sources = _resolve_source_dirs(source_dirs)
    pairs = _iter_source_files(sources)
    if not pairs:
        raise BackupError(
            "no source files found under: " + ", ".join(str(s) for s in sources)
        )
    plaintext = _tar_bytes(pairs)
    fernet = Fernet(_load_key(key))
    encrypted = fernet.encrypt(plaintext)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encrypted)
    _log.info(
        "backup: wrote %d files (%d bytes plaintext) to %s (%d bytes encrypted)",
        len(pairs),
        len(plaintext),
        out,
        len(encrypted),
    )
    return {"files": len(pairs), "bytes_in": len(plaintext), "bytes_out": len(encrypted)}


def restore_backup(
    archive_path: str | Path,
    *,
    dest_root: str | Path,
    key: str | None = None,
) -> dict[str, int]:
    """Decrypt ``archive_path`` and extract it under ``dest_root``.

    Parameters
    ----------
    archive_path:
        Path to an encrypted ``.tar.gz.enc`` produced by
        :func:`create_backup`.
    dest_root:
        Directory the archive is extracted under. Existing
        files with the same name are overwritten — restore is
        intended to recover from a fresh deploy where the
        ``logs/`` directory may or may not exist.
    key:
        Optional Fernet key or passphrase. ``None`` (the default)
        reads ``ZORVA_BACKUP_KEY``.

    Raises
    ------
    :class:`WrongKeyError`
        If the supplied key cannot decrypt the archive (most
        commonly: a different ``ZORVA_BACKUP_KEY`` was used
        at backup time).
    :class:`BackupError`
        If the archive is corrupt, the tar is malformed, or
        the source file isn't readable.

    Returns
    -------
    A summary dict ``{"files": N}`` with the number of regular
    files extracted.
    """
    archive = Path(archive_path)
    if not archive.is_file():
        raise BackupError(f"archive not found: {archive}")
    ciphertext = archive.read_bytes()
    try:
        plaintext = Fernet(_load_key(key)).decrypt(ciphertext)
    except InvalidToken as exc:
        raise WrongKeyError(
            "backup key does not match the archive (wrong ZORVA_BACKUP_KEY?)"
        ) from exc
    count = _untar_bytes(plaintext, dest_root=dest_root)
    _log.info(
        "restore: extracted %d files from %s to %s",
        count,
        archive,
        dest_root,
    )
    return {"files": count}


# ─── CLI ─────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ai_billing_audit.backup",
        description=(
            "Encrypted backup + restore for the Zorva log + data "
            "directories. The ZORVA_BACKUP_KEY env var (or a raw "
            "Fernet key from `python -m ai_billing_audit.backup "
            "gen-key`) is required."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create", help="write an encrypted backup")
    p_create.add_argument(
        "output",
        help="path to the .tar.gz.enc file to write",
    )
    p_create.add_argument(
        "--source",
        action="append",
        default=None,
        help=(
            "directory to bundle (repeatable). Defaults to "
            "ZORVA_BACKUP_SOURCES, or /app/logs + /app/data"
        ),
    )

    p_restore = sub.add_parser(
        "restore",
        help="decrypt + extract an encrypted backup",
    )
    p_restore.add_argument(
        "archive",
        help="path to a .tar.gz.enc file produced by `create`",
    )
    p_restore.add_argument(
        "--dest",
        default=".",
        help="destination directory (default: current directory)",
    )

    sub.add_parser(
        "gen-key",
        help="print a fresh Fernet key (set this as ZORVA_BACKUP_KEY)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — invoked by ``python -m ai_billing_audit.backup``."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "create":
        summary = create_backup(args.output, source_dirs=args.source)
        print(
            f"backup created: files={summary['files']} "
            f"bytes_in={summary['bytes_in']} bytes_out={summary['bytes_out']}"
        )
        return 0
    if args.command == "restore":
        summary = restore_backup(args.archive, dest_root=args.dest)
        print(f"restore complete: files={summary['files']}")
        return 0
    if args.command == "gen-key":
        print(generate_key())
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI smoke
    sys.exit(main())