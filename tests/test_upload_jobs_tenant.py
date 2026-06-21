"""Tests for tenant isolation on upload_jobs.jsonl reads.

The smartness test surfaced a multi-tenant leak in
_latest_real_audit_for: it returned any matching encounter_id
regardless of tenant. A clinic's biller could pull another
clinic's audit findings just by knowing the encounter_id.

These tests pin the fix: tenant_id filter is enforced on the
JSONL read path via the module-level read_latest_real_audit.

What's pinned
-------------
* Two jobs, same encounter_id, different tenants: caller A
  only sees their own row.
* Legacy job without tenant_id is treated as 'default' (the
  existing-tenant scope) so existing audit trails don't
  disappear after the upgrade.
* Empty log → None.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_billing_audit.api import read_latest_real_audit


def _seed_log(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _make_job_row(
    job_id: str,
    encounter_id: str,
    tenant_id: str | None,
    *,
    audit_status: str = "ok",
    findings: list[dict] | None = None,
) -> dict:
    return {
        "job_id": job_id,
        "encounter_id": encounter_id,
        "source": "paste",
        "source_filename": None,
        "tenant_id": tenant_id or "default",
        "status": "done",
        "stage": "done",
        "progress": 100,
        "error": "",
        "result": {
            "audit_status": audit_status,
            "findings_count": len(findings or []),
            "findings": findings or [],
            "summary": f"audit summary for {encounter_id}",
            "zorva_context": None,
        },
        "submitted_at": 1700000000.0,
        "started_at": 1700000001.0,
        "finished_at": 1700000002.0,
    }


@pytest.fixture
def log_path(tmp_path):
    """Yield a tmp upload_jobs.jsonl path."""
    return tmp_path / "upload_jobs.jsonl"


def test_two_tenants_same_encounter_id_returns_only_mine(log_path):
    """Two clinics upload the same encounter_id. Clinic A only sees A's row."""
    _seed_log(log_path, [
        _make_job_row(
            "aaaa11111111",
            "shared-encounter",
            "clinic_a",
            findings=[{"rule_id": "rule_a_001", "quote": "x", "severity": "high"}],
        ),
        _make_job_row(
            "bbbb22222222",
            "shared-encounter",
            "clinic_b",
            findings=[{"rule_id": "rule_b_001", "quote": "y", "severity": "critical"}],
        ),
    ])
    audit = read_latest_real_audit(
        encounter_id="shared-encounter",
        tenant_id="clinic_a",
        log_path=log_path,
    )
    assert audit is not None
    assert audit["tenant_id"] == "clinic_a"
    assert audit["job_id"] == "aaaa11111111"
    assert audit["findings"][0]["rule_id"] == "rule_a_001"


def test_other_tenant_audit_returns_none(log_path):
    """Clinic A asks for an encounter_id owned by Clinic B → None."""
    _seed_log(log_path, [
        _make_job_row(
            "bbbb22222222",
            "clinic-b-only",
            "clinic_b",
        ),
    ])
    audit = read_latest_real_audit(
        encounter_id="clinic-b-only",
        tenant_id="clinic_a",
        log_path=log_path,
    )
    assert audit is None


def test_legacy_row_without_tenant_id_defaults_to_default(log_path):
    """An existing log row without tenant_id is still visible to the default tenant."""
    legacy_row = _make_job_row("cccc33333333", "legacy-enc", None)
    legacy_row.pop("tenant_id", None)
    _seed_log(log_path, [legacy_row])
    audit = read_latest_real_audit(
        encounter_id="legacy-enc",
        tenant_id="default",
        log_path=log_path,
    )
    assert audit is not None
    assert audit["job_id"] == "cccc33333333"


def test_empty_log_returns_none(log_path):
    audit = read_latest_real_audit(
        encounter_id="anything",
        tenant_id="default",
        log_path=log_path,
    )
    assert audit is None


def test_audit_status_failed_excluded(log_path):
    """Failed audits are not surfaced even for the right tenant."""
    _seed_log(log_path, [
        _make_job_row(
            "ffff44444444",
            "enc-failed",
            "clinic_a",
            audit_status="failed",
        ),
    ])
    audit = read_latest_real_audit(
        encounter_id="enc-failed",
        tenant_id="clinic_a",
        log_path=log_path,
    )
    assert audit is None


def test_returns_most_recent_when_multiple_match(log_path):
    """Two OK rows for the same encounter: caller gets the most recent."""
    _seed_log(log_path, [
        _make_job_row("older", "enc-multi", "clinic_a"),
        _make_job_row("newer", "enc-multi", "clinic_a"),
    ])
    audit = read_latest_real_audit(
        encounter_id="enc-multi",
        tenant_id="clinic_a",
        log_path=log_path,
    )
    assert audit["job_id"] == "newer"


def test_cross_tenant_pollution_kept_separate(log_path):
    """The realistic attack: clinic A knows clinic B's encounter_id
    and tries to pull the audit. The filter must block."""
    _seed_log(log_path, [
        _make_job_row(
            "b1",
            "enc-b1",
            "clinic_b",
            findings=[{"rule_id": "leaked_data", "quote": "secret", "severity": "critical"}],
        ),
    ])
    audit = read_latest_real_audit(
        encounter_id="enc-b1",
        tenant_id="clinic_a",
        log_path=log_path,
    )
    # The attacker must not see clinic_b's data
    assert audit is None


def test_status_not_done_excluded(log_path):
    """Rows with status != 'done' are skipped even for matching tenant."""
    row = _make_job_row("running1", "enc-running", "clinic_a")
    row["status"] = "running"
    _seed_log(log_path, [row])
    audit = read_latest_real_audit(
        encounter_id="enc-running",
        tenant_id="clinic_a",
        log_path=log_path,
    )
    assert audit is None


def test_finds_most_recent_across_mixed_tenants(log_path):
    """When logs from multiple tenants exist for an encounter_id,
    the matching tenant gets its own most-recent row, in order."""
    _seed_log(log_path, [
        _make_job_row("a_old", "enc-x", "clinic_a"),
        _make_job_row("b_old", "enc-x", "clinic_b"),
        _make_job_row("a_new", "enc-x", "clinic_a"),
        _make_job_row("b_new", "enc-x", "clinic_b"),
    ])
    a_audit = read_latest_real_audit(
        encounter_id="enc-x", tenant_id="clinic_a", log_path=log_path
    )
    b_audit = read_latest_real_audit(
        encounter_id="enc-x", tenant_id="clinic_b", log_path=log_path
    )
    assert a_audit["job_id"] == "a_new"
    assert b_audit["job_id"] == "b_new"


def test_missing_log_path_returns_none(tmp_path):
    """Non-existent log file → None (no crash)."""
    audit = read_latest_real_audit(
        encounter_id="anything",
        tenant_id="default",
        log_path=tmp_path / "does_not_exist.jsonl",
    )
    assert audit is None
