"""Tests for tenant scoping in the audit trail.

When Zorva serves multiple clinics, the activity feed on
/activity must only show reviewer actions from the current
tenant. This pins the read_all() tenant filter and the
append() tenant_id recording.

What's pinned
-------------
* append() records the tenant_id field on every event
* read_all(tenant_id=None) returns only the default tenant's rows
* read_all(tenant_id='acme') returns only acme's rows
* read_all(tenant_id='*') returns all rows across tenants
* Legacy rows (no tenant_id key) default to 'default' so
  existing audit trails don't disappear after the upgrade
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ai_billing_audit import audit_actions as aa_mod


@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    """Point the audit_actions module at a tmp log file."""
    log = tmp_path / "audit_trail.jsonl"
    monkeypatch.setattr(aa_mod, "_LOG_PATH", log)
    return log


def _append(log, action, encounter_id, tenant_id=None, **kwargs):
    """Wrap append to also accept a tenant_id."""
    row = aa_mod.append(
        action=action,
        encounter_id=encounter_id,
        tenant_id=tenant_id,
        **kwargs,
    )
    return row


def test_append_records_tenant_id(tmp_log):
    row = _append(tmp_log, "accept_all", "E-1", tenant_id="acme")
    assert row.get("tenant_id") == "acme"


def test_append_default_tenant_when_omitted(tmp_log):
    row = _append(tmp_log, "accept_all", "E-1")
    assert row.get("tenant_id") == "default"


def test_read_all_filters_by_default_tenant(tmp_log):
    _append(tmp_log, "accept_all", "E-1", tenant_id="acme")
    _append(tmp_log, "accept_all", "E-2", tenant_id="north_york")
    _append(tmp_log, "accept_all", "E-3")  # defaults to 'default'
    rows = aa_mod.read_all(tenant_id=None)  # None == 'default'
    encs = [r["data_elements"]["encounter_id"] for r in rows]
    assert "E-3" in encs
    assert "E-1" not in encs
    assert "E-2" not in encs


def test_read_all_filters_by_specific_tenant(tmp_log):
    _append(tmp_log, "accept_all", "E-1", tenant_id="acme")
    _append(tmp_log, "accept_all", "E-2", tenant_id="north_york")
    rows = aa_mod.read_all(tenant_id="acme")
    encs = [r["data_elements"]["encounter_id"] for r in rows]
    assert encs == ["E-1"]


def test_read_all_star_returns_across_tenants(tmp_log):
    _append(tmp_log, "accept_all", "E-1", tenant_id="acme")
    _append(tmp_log, "accept_all", "E-2", tenant_id="north_york")
    _append(tmp_log, "accept_all", "E-3", tenant_id="default")
    rows = aa_mod.read_all(tenant_id="*")
    assert len(rows) == 3


def test_read_all_none_tenant_matches_legacy_rows(tmp_log):
    """Legacy rows have no tenant_id key; they should default to 'default'
    so the activity page doesn't lose them after the upgrade."""
    # Write a row directly without tenant_id
    legacy_row = {
        "action": "accept_all",
        "user_identifier": "demo",
        "patient_hash": "abc",
        "data_elements": {"encounter_id": "LEGACY-1"},
        "model_run_id": "",
        "cryptographic_signature": "0000000000000000000000000000000000000000000000000000000000000000",
    }
    tmp_log.write_text(json.dumps(legacy_row) + "\n")
    _append(tmp_log, "accept_all", "E-NEW", tenant_id="default")
    rows = aa_mod.read_all(tenant_id=None)
    encs = [r["data_elements"]["encounter_id"] for r in rows]
    # Both the legacy row and the new default-tenant row appear
    assert "LEGACY-1" in encs
    assert "E-NEW" in encs


def test_read_all_does_not_bleed_across_tenants(tmp_log):
    _append(tmp_log, "accept_all", "E-1", tenant_id="acme")
    _append(tmp_log, "accept_all", "E-2", tenant_id="north_york")
    _append(tmp_log, "flag", "E-3", tenant_id="acme")
    rows = aa_mod.read_all(tenant_id="north_york")
    assert len(rows) == 1
    assert rows[0]["data_elements"]["encounter_id"] == "E-2"


def test_read_all_limit_respected_after_tenant_filter(tmp_log):
    """The limit applies AFTER the tenant filter, not before."""
    for i in range(10):
        _append(tmp_log, "accept_all", f"E-{i}", tenant_id="acme")
    for i in range(10, 15):
        _append(tmp_log, "accept_all", f"E-{i}", tenant_id="north_york")
    rows = aa_mod.read_all(tenant_id="acme", limit=3)
    assert len(rows) == 3
    # The last 3 acme rows (E-7, E-8, E-9)
    encs = [r["data_elements"]["encounter_id"] for r in rows]
    assert encs == ["E-7", "E-8", "E-9"]


def test_read_all_chain_signature_still_intact(tmp_log):
    """Tenant scoping doesn't break the SHA-256 chain verification."""
    _append(tmp_log, "accept_all", "E-1", tenant_id="acme")
    _append(tmp_log, "dismiss", "E-2", tenant_id="acme")
    rows = aa_mod.read_all(tenant_id="acme")
    # Each row has a cryptographic_signature; the chain is intact if
    # every row's stored signature matches compute_signature() on its
    # (previous_signature, row) pair. (verify() was removed in
    # t_649272eb — replicate its core check inline.)
    assert all("cryptographic_signature" in r for r in rows)
    expected_prev = aa_mod._GENESIS_SIG
    for r in rows:
        assert r.get("previous_signature") == expected_prev
        computed = aa_mod.compute_signature(
            r.get("previous_signature", aa_mod._GENESIS_SIG), r
        )
        assert computed == r.get("cryptographic_signature")
        expected_prev = r.get("cryptographic_signature", aa_mod._GENESIS_SIG)


def test_read_all_empty_when_no_matches(tmp_log):
    _append(tmp_log, "accept_all", "E-1", tenant_id="acme")
    rows = aa_mod.read_all(tenant_id="north_york")
    assert rows == []


def test_append_returns_full_row_with_tenant(tmp_log):
    """The returned row includes the tenant_id and chain signature."""
    row = _append(tmp_log, "accept_all", "E-1", tenant_id="acme",
                  extra={"findings_count": 3})
    assert "cryptographic_signature" in row
    assert row["tenant_id"] == "acme"
    assert row["data_elements"]["findings_count"] == 3