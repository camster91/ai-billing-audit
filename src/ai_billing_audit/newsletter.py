"""Newsletter signup handler.

The signup form accepts an email + optional name. We
write the row to the hash-chained audit trail (so the
privacy officer can verify what was signed up) and SHA-256
the email so we don't accidentally surface PHI in the
audit log.

The subscriber list is the audit trail itself — we don't
maintain a separate CRM database in v1. A future card
adds a proper subscriber list + double-opt-in + Resend
integration. For v1, the marketing lead reads the audit
trail manually and adds emails to the Resend list.
"""
from __future__ import annotations

import hashlib


def valid_newsletter_email(email: str) -> bool:
    """Same shape check as contact.valid_email."""
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


def append_newsletter_signup(*, email: str, name: str = "") -> dict:
    """Append a 'newsletter_signup' event to the audit trail.

    Returns the row that was appended. The email is SHA-256
    hashed in the row so the privacy officer can dedupe
    without the raw email being in the log.
    """
    from . import audit_actions as _aa
    from .api import _TENANT_ID  # type: ignore[attr-defined]
    email_hash = hashlib.sha256(email.lower().encode("utf-8")).hexdigest()
    extra: dict = {
        "name_excerpt": (name or "")[:80],
    }
    row = _aa.append(
        action="newsletter_signup",
        encounter_id="*",
        user_identifier=email_hash,
        findings=[],
        note=f"newsletter_signup: name={(name or '')[:80]!r}",
        extra=extra,
        tenant_id=_TENANT_ID,
    )
    return row
