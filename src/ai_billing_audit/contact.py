"""Contact form handler — receives walkthrough requests and writes
them to the audit trail so the privacy officer can verify.

The form is intentionally simple: name, clinic, email, volume,
message. We don't store any of this in a separate CRM database
(v2); v1 just writes to the existing audit-trail log so we
have a permanent record of who asked what and when.

The form's email field is SHA-256-hashed in the log so we
don't accidentally surface PHI; the contact_email endpoint
returns the original email only when the request is being
reviewed by the demo sales lead (we don't have that role
in v1; the privacy officer reads the log directly).
"""
from __future__ import annotations

import hashlib
from pathlib import Path


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


def _append_contact_event(
    *,
    name: str,
    clinic: str,
    email: str,
    monthly_claims: str,
    message: str,
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
        extra={
            # Store the full message (not PHI; it's a sales request)
            "message_excerpt": message[:500] if message else "",
        },
        tenant_id=_TENANT_ID,
    )
    return row


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