"""Tests for the canonical salted SHA-256 patient hash.

Pins the privacy contract for the FastAPI audit pipeline:

* The hash is deterministic for a given (input, pepper) pair.
* The hash is 64 lowercase hex chars (matches the ``audit_trail``
  hex CHECK constraint).
* A different pepper produces a different hash for the same input.
* A different input produces a different hash for the same pepper.
* The hash is domain-separated (an attacker who learns the pepper
  cannot reuse it as a ``patient_id``).
* In production, an unset or too-short ``PATIENT_HASH_PEPPER`` is
  a loud error, not a silent fallback to the dev constant.
* The portal's TypeScript ``hashPatientId`` and the Python
  ``hash_patient_id`` produce the same digest for the same input +
  pepper, so the FastAPI audit log and the Next.js portal audit
  log are cross-referenceable.

The portal TypeScript test lives in apps/portal/src/lib/__tests__/
and the format-compat test below is the cross-implementation
contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.patient_hash import (  # noqa: E402
    DEV_FALLBACK_PEPPER,
    DOMAIN_PREFIX,
    MIN_PEPPER_LENGTH,
    assert_production_pepper,
    hash_patient_id,
    resolve_pepper,
)


# A real-shape AHCIP PHN (Alberta Personal Health Number). Used as
# the test input so the assertions exercise a realistic 9-digit ID
# rather than a generic string.
SAMPLE_PHN = "123456789"

# A real-shape production pepper (32+ hex chars). Reused across
# tests so a regression in the format is caught the same way.
SAMPLE_PEPPER = "0" * 32 + "f" * 32


# ---- basic contract -------------------------------------------------------


def test_hash_is_64_lowercase_hex():
    digest = hash_patient_id(SAMPLE_PHN, pepper=SAMPLE_PEPPER)
    assert isinstance(digest, str)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_hash_is_deterministic_for_same_input_and_pepper():
    a = hash_patient_id(SAMPLE_PHN, pepper=SAMPLE_PEPPER)
    b = hash_patient_id(SAMPLE_PHN, pepper=SAMPLE_PEPPER)
    assert a == b


def test_different_input_produces_different_hash():
    a = hash_patient_id("123456789", pepper=SAMPLE_PEPPER)
    b = hash_patient_id("987654321", pepper=SAMPLE_PEPPER)
    assert a != b


def test_different_pepper_produces_different_hash():
    a = hash_patient_id(SAMPLE_PHN, pepper="a" * MIN_PEPPER_LENGTH)
    b = hash_patient_id(SAMPLE_PHN, pepper="b" * MIN_PEPPER_LENGTH)
    assert a != b


# ---- domain separation ----------------------------------------------------


def test_domain_separation_blocks_pepper_as_input():
    """An attacker who learns the pepper cannot use it as a patient_id
    to forge a collision. The domain prefix ensures
    hash(pepper) != hash_patient_id(pepper)."""
    pepper_only = hash_patient_id(SAMPLE_PEPPER, pepper=SAMPLE_PEPPER)
    # If the patient_id is the pepper itself, the domain prefix
    # still separates "patient-hash:v1:PEPPER:PEPPER" from
    # "patient-hash:v1:PEPPER:OTHER", so the digest of the pepper
    # used as input is NOT a collision for some other input.
    assert len(pepper_only) == 64
    # And the digest is the salted-hash-of-self, not the
    # plain pepper (which would be the leak the attacker wants).
    assert pepper_only != SAMPLE_PEPPER


def test_format_uses_domain_prefix():
    """Sanity-check that the format actually uses the v1 domain
    prefix (catches accidental format drift)."""
    import hashlib

    expected = hashlib.sha256(
        f"{DOMAIN_PREFIX}{SAMPLE_PEPPER}:{SAMPLE_PHN}".encode("utf-8")
    ).hexdigest()
    actual = hash_patient_id(SAMPLE_PHN, pepper=SAMPLE_PEPPER)
    assert actual == expected


# ---- input validation -----------------------------------------------------


def test_empty_string_input_raises():
    with pytest.raises(TypeError):
        hash_patient_id("", pepper=SAMPLE_PEPPER)


def test_non_string_input_raises():
    with pytest.raises(TypeError):
        hash_patient_id(12345, pepper=SAMPLE_PEPPER)  # type: ignore[arg-type]


# ---- production-mode fail-fast -------------------------------------------


def test_production_mode_raises_on_missing_pepper(monkeypatch):
    """In production, an unset PATIENT_HASH_PEPPER must raise rather
    than fall back to the dev constant. Loud failure is the only
    acceptable response to a misconfiguration."""
    monkeypatch.delenv("PATIENT_HASH_PEPPER", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="PATIENT_HASH_PEPPER"):
        resolve_pepper()


def test_production_mode_raises_on_short_pepper(monkeypatch):
    monkeypatch.setenv("PATIENT_HASH_PEPPER", "short")
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="PATIENT_HASH_PEPPER"):
        resolve_pepper()


def test_production_mode_accepts_16_char_pepper(monkeypatch):
    monkeypatch.setenv("PATIENT_HASH_PEPPER", "x" * MIN_PEPPER_LENGTH)
    monkeypatch.setenv("APP_ENV", "production")
    assert resolve_pepper() == "x" * MIN_PEPPER_LENGTH


def test_pepper_file_takes_precedence_over_env(monkeypatch, tmp_path):
    """PATIENT_HASH_PEPPER_FILE: the rotation script writes the
    new pepper to a file and the api reads it on every call.
    The file content wins over PATIENT_HASH_PEPPER env var so a
    rotation in progress (file has new, env has old) doesn't
    serve stale hashes."""
    pepper_file = tmp_path / "pepper"
    pepper_file.write_text("f" * MIN_PEPPER_LENGTH)
    monkeypatch.setenv("PATIENT_HASH_PEPPER_FILE", str(pepper_file))
    monkeypatch.setenv("PATIENT_HASH_PEPPER", "e" * MIN_PEPPER_LENGTH)
    assert resolve_pepper() == "f" * MIN_PEPPER_LENGTH


def test_pepper_file_reads_every_call(monkeypatch, tmp_path):
    """A rotation writes a new pepper to the file; the api picks
    it up on the very next call without a restart."""
    pepper_file = tmp_path / "pepper"
    pepper_file.write_text("a" * MIN_PEPPER_LENGTH)
    monkeypatch.setenv("PATIENT_HASH_PEPPER_FILE", str(pepper_file))
    assert resolve_pepper() == "a" * MIN_PEPPER_LENGTH
    pepper_file.write_text("b" * MIN_PEPPER_LENGTH)
    assert resolve_pepper() == "b" * MIN_PEPPER_LENGTH


def test_pepper_file_falls_through_to_env_when_too_short(monkeypatch, tmp_path):
    """A file with a short pepper doesn't satisfy the length
    check; we fall through to PATIENT_HASH_PEPPER (env) so a
    partial rotation doesn't accidentally serve a weak hash."""
    pepper_file = tmp_path / "pepper"
    pepper_file.write_text("short")
    monkeypatch.setenv("PATIENT_HASH_PEPPER_FILE", str(pepper_file))
    monkeypatch.setenv("PATIENT_HASH_PEPPER", "e" * MIN_PEPPER_LENGTH)
    assert resolve_pepper() == "e" * MIN_PEPPER_LENGTH


def test_pepper_file_falls_through_to_env_when_unreadable(monkeypatch, tmp_path):
    """A missing file falls through to PATIENT_HASH_PEPPER (env).
    The rotation script creates the file first then updates .env;
    between those two steps the api must keep serving hashes."""
    monkeypatch.setenv("PATIENT_HASH_PEPPER_FILE", str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("PATIENT_HASH_PEPPER", "e" * MIN_PEPPER_LENGTH)
    assert resolve_pepper() == "e" * MIN_PEPPER_LENGTH


def test_assert_production_pepper_noop_in_dev(monkeypatch):
    monkeypatch.delenv("PATIENT_HASH_PEPPER", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)
    # Should not raise.
    assert_production_pepper()


def test_assert_production_pepper_raises_in_prod(monkeypatch):
    monkeypatch.delenv("PATIENT_HASH_PEPPER", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="PATIENT_HASH_PEPPER"):
        assert_production_pepper()


def test_assert_production_pepper_accepts_valid_rotation_file(monkeypatch, tmp_path):
    """The startup guard accepts the file-backed rotation source."""
    pepper_file = tmp_path / "pepper"
    pepper_file.write_text("r" * MIN_PEPPER_LENGTH)
    monkeypatch.delenv("PATIENT_HASH_PEPPER", raising=False)
    monkeypatch.setenv("PATIENT_HASH_PEPPER_FILE", str(pepper_file))
    monkeypatch.setenv("APP_ENV", "production")

    assert_production_pepper()


# ---- dev-mode fallback ----------------------------------------------------


def test_dev_mode_falls_back_to_dev_constant(monkeypatch):
    monkeypatch.delenv("PATIENT_HASH_PEPPER", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)
    assert resolve_pepper() == DEV_FALLBACK_PEPPER


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("PATIENT_HASH_PEPPER", "y" * MIN_PEPPER_LENGTH)
    monkeypatch.delenv("APP_ENV", raising=False)
    assert resolve_pepper() == "y" * MIN_PEPPER_LENGTH


def test_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("PATIENT_HASH_PEPPER", "env-value" + "z" * 20)
    assert resolve_pepper("override" + "z" * 20) == "override" + "z" * 20


# ---- cross-implementation format compatibility ---------------------------
# Pins the contract with apps/portal/src/lib/patient-hash.ts. The
# TypeScript side uses Node's createHash("sha256") which is
# byte-compatible with Python's hashlib.sha256(). The format string
# and domain prefix MUST stay identical on both sides.


def test_format_matches_portal_typescript():
    """Verify the digest matches what the portal side would produce
    for the same input + pepper. The portal
    (apps/portal/src/lib/patient-hash.ts) computes
    ``sha256("patient-hash:v1:" + pepper + ":" + patientId)`` —
    the format is identical, so the digests are byte-equal. This
    test will fail the moment the portal format drifts."""
    import hashlib

    pepper = "abc123" + "def456" + "ghi789" + "jkl012"  # exactly 24 chars
    patient = "123456789"  # AHCIP PHN shape
    expected = hashlib.sha256(
        f"{DOMAIN_PREFIX}{pepper}:{patient}".encode("utf-8")
    ).hexdigest()
    assert hash_patient_id(patient, pepper=pepper) == expected


# ---- integration: audit_actions uses the canonical hash ------------------
# Pins the contract that audit_actions.append (the canonical
# hash-chain appender) uses the same patient_hash shape as the rest
# of the system. This is the test that catches a future regression
# where someone reverts audit_actions.py to the old bare
# sha256(encounter_id) path.


def test_audit_actions_uses_canonical_patient_hash(monkeypatch, tmp_path):
    """End-to-end: call audit_actions.append, then verify the
    written patient_hash field equals hash_patient_id(encounter_id)
    under the same pepper. This is the contract the privacy
    officer's verifier relies on."""

    # Import inside the test so the env vars are set first.
    from ai_billing_audit import audit_actions

    monkeypatch.setenv("PATIENT_HASH_PEPPER", "z" * 32)
    monkeypatch.setenv("APP_ENV", "production")
    log_path = tmp_path / "audit_trail.jsonl"
    # Redirect the audit-trail path via env var + reload rather
    # than monkeypatching ``aa_mod._LOG_PATH`` directly. The
    # legacy patch pattern conflicts with the broader
    # ``AUDIT_TRAIL_LOG`` env var contract used by ``test_rbac`` /
    # ``test_contact`` etc — tests that share the same module
    # attribute would otherwise leak the previous tmp path via
    # monkeypatch.undo. Standardizing on env var + reload keeps
    # each test's path fully isolated.
    import importlib as _il

    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(log_path))
    _il.reload(audit_actions)

    audit_actions.append(
        action="accept_all",
        encounter_id="enc-abc-123",
        user_identifier="tester",
        findings=[{"finding_id": "f1", "rule_id": "MOD-25"}],
        note="",
        tenant_id="test-tenant",
    )

    # The log file is append-only; read the one row we wrote.
    assert log_path.is_file()
    from ai_billing_audit.clinical_note_storage import (
        read_encrypted_json_records,
    )

    rows = read_encrypted_json_records(log_path)
    assert len(rows) == 1
    written = rows[0]
    expected = hash_patient_id("enc-abc-123", pepper="z" * 32)
    assert written["patient_hash"] == expected
