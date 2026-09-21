"""Tests for the tenant purge path (review finding 1.7).

The defect these cover: ``DELETE /api/tenants/{tenant_id}`` wrote an audit
row saying the request was recorded and returned success without deleting
anything, while ``docs/PILOT_OFFER.md`` promises a clinic its data is gone
within seven business days.

The tests pin three properties:

1. A tenant-scoped store loses exactly that tenant's rows, and no others.
2. A store with no tenant field is reported as ``unscoped`` and left
   untouched — never truncated, because truncating it would take every
   other tenant's data with it.
3. The rewritten files stay readable, which means staying encrypted. An
   early implementation of this module rewrote survivors as plaintext
   JSON and made every later read raise ``PhiStorageIntegrityError``;
   ``test_rewrite_preserves_encryption_and_readability`` is the regression
   guard for exactly that mistake.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cryptography.fernet import Fernet  # noqa: E402

from ai_billing_audit import audit_actions, tenant_purge  # noqa: E402


@pytest.fixture
def store_root(tmp_path, monkeypatch):
    """Point every store this module knows about at a temp directory."""
    monkeypatch.setenv("ZORVA_LOGS_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(tmp_path / "audit_trail.jsonl"))
    monkeypatch.setenv("UPLOAD_AUDIT_LOG_PATH", str(tmp_path / "upload_jobs.jsonl"))
    monkeypatch.setenv("FEEDBACK_LOG", str(tmp_path / "feedback.jsonl"))
    monkeypatch.setenv("BILLER_CORRECTIONS_LOG", str(tmp_path / "biller_corrections.jsonl"))
    monkeypatch.setenv("FINDING_COMMENTS_LOG", str(tmp_path / "finding_comments.jsonl"))
    monkeypatch.setenv("SNOOZE_LOG", str(tmp_path / "snoozes.jsonl"))
    monkeypatch.setenv("SAVED_FILTERS_LOG", str(tmp_path / "saved_filters.jsonl"))
    monkeypatch.setenv("FINDING_ASSIGNMENT_LOG", str(tmp_path / "finding_assignments.jsonl"))
    monkeypatch.setenv("TENANT_RULES_LOG", str(tmp_path / "tenant_rules.jsonl"))
    monkeypatch.setenv("TENANT_LOCALE_LOG", str(tmp_path / "tenant_locale.jsonl"))
    monkeypatch.setenv("TENANT_AUDIT_DEPTH_LOG", str(tmp_path / "tenant_audit_depth.jsonl"))
    monkeypatch.setenv("IDEMPOTENCY_LOG", str(tmp_path / "idempotency.jsonl"))
    monkeypatch.setenv("USAGE_LOG_PATH", str(tmp_path / "usage_log.jsonl"))
    monkeypatch.setenv("SLACK_INTEGRATIONS_LOG", str(tmp_path / "slack_integrations.jsonl"))
    monkeypatch.setenv("SUBMIT_WEBHOOK_LOG", str(tmp_path / "submit_webhooks.jsonl"))
    monkeypatch.setenv("ONBOARDING_LOG", str(tmp_path / "onboarding.jsonl"))
    monkeypatch.setenv("SPECIALTY_MIX_LOG", str(tmp_path / "specialty_mix.jsonl"))
    monkeypatch.setenv("ZORVA_UPLOADED_NOTES_DIR", str(tmp_path / "uploaded_notes"))
    monkeypatch.setenv("ZORVA_PHI_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(audit_actions, "_LOG_PATH", tmp_path / "audit_trail.jsonl", raising=False)
    audit_actions._reset_last_signature_cache()
    return tmp_path


def _append(tenant: str, encounter: str) -> None:
    audit_actions.append(
        action="accept_all",
        encounter_id=encounter,
        user_identifier="biller@example.ca",
        tenant_id=tenant,
    )


class TestTenantScopedStores:
    def test_removes_only_the_target_tenant(self, store_root):
        _append("clinicA", "enc-A1")
        _append("clinicA", "enc-A2")
        _append("clinicB", "enc-B1")

        report = tenant_purge.purge_tenant("clinicA")

        assert report.purged["audit_trail"] == 2
        remaining = audit_actions.read_all(tenant_id="*")
        assert [r["tenant_id"] for r in remaining] == ["clinicB"]
        assert remaining[0]["data_elements"]["encounter_id"] == "enc-B1"

    def test_reports_target_tenant_fully_gone(self, store_root):
        _append("clinicA", "enc-A1")
        report = tenant_purge.purge_tenant("clinicA")
        assert report.purged["audit_trail"] == 1
        assert audit_actions.read_all(tenant_id="clinicA") == []

    def test_idempotent(self, store_root):
        _append("clinicA", "enc-A1")
        first = tenant_purge.purge_tenant("clinicA")
        second = tenant_purge.purge_tenant("clinicA")
        assert first.purged["audit_trail"] == 1
        assert second.purged["audit_trail"] == 0
        assert second.failed == {}

    def test_absent_store_is_not_an_error(self, store_root):
        report = tenant_purge.purge_tenant("clinicA")
        assert report.failed == {}
        assert all(count == 0 for count in report.purged.values())


class TestUnscopedStores:
    def test_unscoped_store_is_reported_and_untouched(self, store_root):
        """A store with no tenant field must never be truncated."""
        feedback = store_root / "feedback.jsonl"
        feedback.write_text(
            "\n".join(json.dumps({"action": "accept", "biller_id": "b"}) for _ in range(2))
            + "\n"
        )

        report = tenant_purge.purge_tenant("clinicA")

        assert "feedback" in report.unscoped
        assert not report.complete
        # Both rows survive — they may belong to another tenant.
        assert len(feedback.read_text().strip().splitlines()) == 2

    def test_absent_unscoped_store_is_not_reported(self, store_root):
        """Only report what actually exists; don't cry wolf."""
        report = tenant_purge.purge_tenant("clinicA")
        assert "specialty_mix" not in report.unscoped


class TestRewriteIntegrity:
    def test_rewrite_preserves_encryption_and_readability(self, store_root):
        """Regression guard: survivors must stay encrypted, not plaintext.

        The first implementation of this module wrote survivors as plain
        JSON lines. Every later read then raised
        ``PhiStorageIntegrityError`` because the file was no longer
        Fernet-framed, and PHI sat on disk in the clear.
        """
        _append("clinicA", "enc-A1")
        _append("clinicB", "enc-B1")

        tenant_purge.purge_tenant("clinicA")

        raw = (store_root / "audit_trail.jsonl").read_bytes()
        assert b"enc-B1" not in raw, "surviving row must not be plaintext on disk"
        # And it must still be readable through the normal reader.
        rows = audit_actions.read_all(tenant_id="*")
        assert len(rows) == 1
        assert rows[0]["data_elements"]["encounter_id"] == "enc-B1"

    def test_chain_rows_still_verify_after_batch_rewrite(self, store_root):
        """Rows that were already written keep their signatures."""
        _append("clinicB", "enc-B1")
        _append("clinicB", "enc-B2")
        before = audit_actions.read_all(tenant_id="*")
        sigs_before = [r["cryptographic_signature"] for r in before]

        # Purge a different tenant; clinicB's rows are untouched.
        tenant_purge.purge_tenant("clinicA")

        after = audit_actions.read_all(tenant_id="*")
        assert [r["cryptographic_signature"] for r in after] == sigs_before


class TestBoundaryMarker:
    def test_marker_records_what_could_not_be_deleted(self, store_root):
        feedback = store_root / "feedback.jsonl"
        feedback.write_text(json.dumps({"action": "accept"}) + "\n")

        report = tenant_purge.purge_tenant("clinicA")
        marker = tenant_purge.purge_boundary_marker(report, at="2026-09-21T00:00:00Z")

        assert marker["kind"] == "tenant_purge_boundary"
        assert marker["tenant_id"] == "clinicA"
        assert "feedback" in marker["stores_unscoped"]
        assert marker["complete"] is False
        assert "audit_trail" in marker["stores_purged"]

    def test_marker_is_json_serializable(self, store_root):
        """It goes into the audit trail, so it must survive json.dumps."""
        report = tenant_purge.purge_tenant("clinicA")
        marker = tenant_purge.purge_boundary_marker(report, at="2026-09-21T00:00:00Z")
        assert json.loads(json.dumps(marker))["kind"] == "tenant_purge_boundary"
