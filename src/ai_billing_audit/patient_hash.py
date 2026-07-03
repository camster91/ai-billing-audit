"""Canonical salted SHA-256 patient identifier hash for the FastAPI audit pipeline.

This is the Python equivalent of ``apps/portal/src/lib/patient-hash.ts`` on
the Next.js side. The two implementations MUST produce identical digests
for the same input + pepper so the audit log written by the FastAPI
service can be cross-referenced with the audit log written by the
portal (and so a single PEPER can rotate hashes across both surfaces
simultaneously).

Why a pepper?
-------------
Unsalted SHA-256 of a 6-12 char member-ID is dictionary-attackable
in seconds: AHCIP PHNs, Ontario health card numbers, and most
commercial payer ID shapes live in a small domain. Anyone with
read access to ``audit_trail`` could correlate encounters back to
specific patients by running a small rainbow-table script. HIA
(Alberta), PHIPA (Ontario), and HIPAA Safe Harbor all treat such
correlation as a breach.

A pepper (a server-side secret mixed into the hash before the
input) raises the cost of any pre-computed attack by requiring the
attacker to also possess the pepper. Rotating the pepper
invalidates every existing hash, which is the right response to a
suspected breach.

Threat model
------------
- **Database snapshot leak:** attacker can read the ``patient_hash``
  column but does NOT have the pepper → cannot run a dictionary
  attack without also compromising the application host or the
  secret manager.
- **Application host compromise:** attacker has the pepper, can
  verify a small candidate set. The mitigation is the same as for
  any application secret — keep the pepper in a secret manager
  (or the ``/root/ai-billing-audit-secrets/`` env file), not in
  ``.env`` committed to the repo.

Environment
-----------
- ``PATIENT_HASH_PEPPER`` — required in production (length ≥ 16);
  optional in dev (the helper falls back to a constant when
  ``APP_ENV`` / ``NODE_ENV`` is not ``"production"``). The
  :func:`assert_production_pepper` helper is called from the
  audit-write path and raises on first request in production if
  the env var is unset or too short. The fail-fast is loud, not
  silent — a misconfigured deployment should be impossible to miss.

Format
------
::

    hash_patient_id(patient_id) = SHA-256(
        "patient-hash:v1:" + pepper + ":" + patient_id
    )

The ``"patient-hash:v1:"`` domain prefix ensures an attacker who
learns the pepper cannot reuse it as a ``patient_id`` (collision
resistance even when secrets share a domain). The ``":v1"`` token
is a version marker — if the hash format ever needs to change
(e.g. switch to Argon2id), the new format uses ``v2`` and the
two are not interoperable. The chain still verifies because each
row carries its own computed signature.

Migration from the prior unsalted path
---------------------------------------
The previous ``audit_actions.append`` did
``sha256(encounter_id).hexdigest()`` with no pepper. Rows already
in the chain (audit_trail.jsonl + Postgres ``audit_trail`` table)
keep their existing ``patient_hash`` values; the chain still
verifies because the cryptographic_signature is computed from
each row's own ``patient_hash`` field, not from the original
input. Forward-only migration: new rows use the salted hash;
old rows are immutable. After the full ledger is rotated (90-day
retention), every row will use the new format.
"""
from __future__ import annotations

import hashlib
import os

__all__ = [
    "hash_patient_id",
    "assert_production_pepper",
    "DOMAIN_PREFIX",
    "DEV_FALLBACK_PEPPER",
    "MIN_PEPPER_LENGTH",
]


# The domain prefix is the single source of truth for the hash
# format. Bumping it (v1 -> v2) is a hard migration: the new
# format cannot be cross-checked against the old. The portal
# side (apps/portal/src/lib/patient-hash.ts) MUST use the same
# prefix so both surfaces produce identical digests.
DOMAIN_PREFIX: str = "patient-hash:v1:"

# Constant used when ``PATIENT_HASH_PEPPER`` is unset and we are
# not in production. NEVER use this in production — the audit
# log would be trivially dictionary-attackable by anyone with
# the source code. The ``assert_production_pepper`` helper
# prevents this via a loud error at first request.
DEV_FALLBACK_PEPPER: str = (
    "dev-only-patients-hash-pepper-do-not-use-in-production"
)

# Minimum length of an acceptable pepper. The portal side uses
# the same threshold; keep them in sync.
MIN_PEPPER_LENGTH: int = 32


def _is_production() -> bool:
    """True iff the current process is running in production.

    Matches the portal's ``NODE_ENV === "production"`` check via
    ``APP_ENV`` first (the FastAPI service uses ``APP_ENV`` per
    the deploy scripts) and falls back to ``ENVIRONMENT`` for
    the dev container. Test runs (``pytest``) leave both unset
    and get the dev fallback.
    """
    return (
        os.environ.get("APP_ENV", "").lower() == "production"
        or os.environ.get("ENVIRONMENT", "").lower() == "production"
        or os.environ.get("NODE_ENV", "").lower() == "production"
    )


def resolve_pepper(override: str | None = None) -> str:
    """Return the active pepper, raising in production if it is missing.

    Resolution order:
    1. ``override`` (caller-supplied; used by tests). If supplied
       explicitly, we trust the caller — length validation only
       applies to env-sourced peppers, NOT to in-code overrides.
       This lets tests assert hash-format pinning with a short
       pepper without tripping the production minimum-length check.
    2. ``PATIENT_HASH_PEPPER`` environment variable (must be
       :data:`MIN_PEPPER_LENGTH`+ chars)
    3. Dev fallback constant (only when not in production)

    In production, an unset or too-short env-sourced pepper raises
    :class:`RuntimeError` so the misconfiguration is loud, not
    silent. A 32+ char pepper is the minimum the threat model
    accepts (longer is fine).
    """
    # Caller-supplied overrides are trusted (this is the contract for
    # unit tests asserting exact digests with a known short pepper).
    if override is not None:
        return override
    env_value = os.environ.get("PATIENT_HASH_PEPPER", "")
    if env_value and len(env_value) >= MIN_PEPPER_LENGTH:
        return env_value

    if _is_production():
        raise RuntimeError(
            f"PATIENT_HASH_PEPPER must be set to a {MIN_PEPPER_LENGTH}+ "
            "char secret in production. Refusing to compute a "
            "patient_hash with a weak / missing pepper."
        )

    return DEV_FALLBACK_PEPPER


def hash_patient_id(patient_id: str, *, pepper: str | None = None) -> str:
    """Return the salted SHA-256 hex digest of ``patient_id``.

    The output is 64 lowercase hex chars, matching the
    ``patient_hash`` column shape expected by ``audit_trail.sql``
    (hex CHECK constraint). The same input + pepper always
    produces the same output — deterministic, idempotent, safe
    to use as a dedupe key.

    Raises :class:`TypeError` if ``patient_id`` is empty or not
    a string. Raises :class:`RuntimeError`` (via
    :func:`resolve_pepper`) if a production deployment has not
    configured ``PATIENT_HASH_PEPPER``.
    """
    if not isinstance(patient_id, str) or not patient_id:
        raise TypeError("patient_id must be a non-empty string")
    active_pepper = resolve_pepper(pepper)
    payload = f"{DOMAIN_PREFIX}{active_pepper}:{patient_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assert_production_pepper() -> None:
    """Loud-fail helper for the audit-write path.

    Call this from the FastAPI app startup (or the worker init)
    so a missing ``PATIENT_HASH_PEPPER`` is caught at process
    start, not at first request. Idempotent: calling it more
    than once is fine; in non-production it is a no-op.
    """
    if not _is_production():
        return
    pepper = os.environ.get("PATIENT_HASH_PEPPER", "")
    if len(pepper) < MIN_PEPPER_LENGTH:
        raise RuntimeError(
            f"PATIENT_HASH_PEPPER must be set to a {MIN_PEPPER_LENGTH}+ "
            "char secret in production. Refusing to start."
        )
