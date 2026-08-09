"""Contact form handler — receives audit requests and writes
them to the audit trail so the privacy officer can verify.

The form is intentionally simple: name, clinic, email, volume,
message, claims file. We don't store any of this in a separate
CRM database (v2); v1 just writes to the existing audit-trail
log so we have a permanent record of who asked what and when.

The form's email field is SHA-256-hashed in the log so we
don't accidentally surface PHI; the contact_email endpoint
returns the original email only when the request is being
reviewed by the demo sales lead (we don't have that role
in v1; the privacy officer reads the log directly).
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Any

from ai_billing_audit.clinical_note_storage import (
    decrypt_phi,
    encrypt_phi,
    PhiStorageIntegrityError,
    store_clinical_note,
)

# Maximum upload size for /contact claims — matches the rest of
# the upload portal (api.py: _MAX_UPLOAD_BYTES). 25 MB is enough
# for ~5,000 encounter rows in 837P/CSV.
_MAX_CONTACT_UPLOAD_BYTES = int(
    os.environ.get("CONTACT_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))
)

# Where to stage the uploaded file. The audit team pulls from
# this directory via the shadow_audit pipeline.
_DEFAULT_STAGE_DIR = "/app/logs/contact_uploads"

# Allowlist of file extensions the contact-form uploader accepts.
# Same set as the main upload portal: 837P (the .edi/.txt variants
# are legacy filenames for the same format), CSV, JSON, FHIR JSON
# or XML, and ZIP archives of any of those.
_ALLOWED_EXTENSIONS = frozenset(
    {
        ".837",
        ".edi",
        ".txt",
        ".csv",
        ".json",
        ".xml",
        ".fhir",
        ".zip",
    }
)


def valid_email(email: str) -> bool:
    """Lightweight email-shape validation.

    Not RFC-compliant; the goal is to catch obvious typos
    (missing @, missing domain, embedded whitespace). The
    sales lead validates the actual deliverability on receipt.
    """
    if not email or len(email) > 320:
        return False
    if "@" not in email:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return False
    if " " in email or "\t" in email or "\n" in email:
        return False
    return True


def valid_volume(monthly_claims: str) -> bool:
    """Accept a positive integer string up to 1,000,000."""
    try:
        n = int(monthly_claims)
    except (TypeError, ValueError):
        return False
    return 1 <= n <= 1_000_000


def _stage_dir() -> Path:
    """Resolve the upload staging directory from env or default."""
    return Path(os.environ.get("CONTACT_UPLOAD_DIR", _DEFAULT_STAGE_DIR))


def migrate_contact_uploads() -> int:
    """Encrypt legacy plaintext uploads without changing manifest paths."""
    directory = _stage_dir()
    if not directory.is_dir():
        return 0
    migrated = 0
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name.endswith(
            (".plaintext.bak.enc", ".encrypted.tmp")
        ):
            continue
        original = path.read_bytes()
        try:
            decrypt_phi(original)
        except PhiStorageIntegrityError:
            pass
        else:
            continue
        backup = path.with_name(path.name + ".plaintext.bak.enc")
        if backup.exists():
            raise PhiStorageIntegrityError("encrypted plaintext backup already exists")
        backup.write_bytes(encrypt_phi(original))
        replacement = path.with_name(path.name + ".encrypted.tmp")
        try:
            store_clinical_note(replacement, original)
            replacement.replace(path)
        finally:
            if replacement.exists():
                replacement.unlink()
        migrated += 1
    return migrated


async def _stage_contact_upload(file) -> dict[str, Any] | None:
    """Stage a /contact claims file to disk for the audit team.

    swarm-audit B-Conv-1: previously the contact form didn't accept
    file uploads — the "send 100 claims" promise was a lie. Now
    the file is staged to ``/app/logs/contact_uploads/`` (configurable
    via ``CONTACT_UPLOAD_DIR``) with a SHA-256 hash + size + extension
    manifest. The audit team pulls from this directory via the
    shadow_audit pipeline.

    Returns ``None`` when no file was selected (FastAPI sends an
    empty UploadFile in that case — the form treats it as "no
    upload, follow up by email").

    Raises ``ValueError`` on size or extension violations so the
    contact handler can surface the error message to the user.
    """
    # No file selected: filename is empty.
    filename = (file.filename or "").strip()
    if not filename:
        return None

    # Extension gate.
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type {suffix!r}. Accepted: "
            f"{', '.join(sorted(_ALLOWED_EXTENSIONS))}."
        )

    raw = await file.read()
    if len(raw) > _MAX_CONTACT_UPLOAD_BYTES:
        raise ValueError(
            f"File is {len(raw):,} bytes; max is {_MAX_CONTACT_UPLOAD_BYTES:,}."
        )
    if not raw:
        raise ValueError("File is empty.")

    digest = hashlib.sha256(raw).hexdigest()
    staged_at = _stage_dir()
    staged_at.mkdir(parents=True, exist_ok=True)

    # Stable on-disk name: <sha-prefix>-<uuid>-<original-name>.
    # The SHA prefix is for human-grep; the uuid prevents collisions
    # when two prospects upload the same filename. The original
    # filename is preserved so the audit team knows which file it
    # is without consulting a separate manifest.
    safe_name = filename.replace("/", "_").replace("\\", "_").strip() or "upload"
    staged_name = f"{digest[:12]}-{uuid.uuid4().hex[:8]}-{safe_name}"
    staged_path = staged_at / staged_name
    store_clinical_note(staged_path, raw)

    manifest = {
        "filename": filename,
        "staged_path": str(staged_path),
        "staged_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "size_bytes": len(raw),
        "sha256": digest,
        "extension": suffix,
        "encrypted_at_rest": True,
    }
    return manifest


def _append_contact_event(
    *,
    name: str,
    clinic: str,
    email: str,
    monthly_claims: str,
    message: str,
    upload: dict[str, Any] | None = None,
) -> dict:
    """Append a 'contact_request' event to the audit trail.

    Goes through the standard `audit_actions.append()` so the
    event is part of the SHA-256 chain — tamper-evident by
    construction, not just append-only.

    Returns the row that was appended, including the email
    SHA-256 hash so the privacy officer can dedupe later.
    """
    from . import audit_actions as _aa

    email_hash = hashlib.sha256(email.lower().encode("utf-8")).hexdigest()
    # tenant_id is captured at app-init from TENANT_ID env var;
    # audit_actions._LOG_PATH is captured at module-import
    # time, so the test fixture must reload audit_actions.
    from .api import _TENANT_ID  # type: ignore[attr-defined]

    extra: dict[str, Any] = {
        # Store the full message (not PHI; it's a sales request)
        "message_excerpt": message[:500] if message else "",
    }
    if upload is not None:
        # The upload manifest includes the SHA-256 of the file
        # and the staged path. The original filename + size are
        # retained so the audit team knows what was uploaded.
        # We deliberately do NOT include the file contents or any
        # patient identifiers — privacy posture matches the rest
        # of the upload portal.
        extra["upload"] = upload
    row = _aa.append(
        action="contact_request",
        encounter_id="*",  # not a single encounter
        user_identifier=email_hash,
        findings=[],
        note=(
            f"contact_request: name={name[:80]!r} "
            f"clinic={clinic[:80]!r} "
            f"monthly_claims={monthly_claims!r}"
        ),
        extra=extra,
        tenant_id=_TENANT_ID,
    )
    return row
