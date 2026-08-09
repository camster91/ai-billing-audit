"""Tests for feature_flags module (kanban t_11b04a94)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_billing_audit import feature_flags as ff


@pytest.fixture
def flag_log(tmp_path: Path, monkeypatch):
    log = tmp_path / "flags.jsonl"
    monkeypatch.setenv("FEATURE_FLAG_LOG", str(log))
    return log


def test_known_flags_includes_clinical_impact_set():
    names = ff.list_known_flags()
    for required in (
        "doctor_dashboard",
        "monthly_owner_email",
        "locale_fr_ca",
        "configurable_audit_depth",
        "per_tenant_rules",
        "doctor_positive_feedback",
    ):
        assert required in names


def test_is_enabled_default_false(flag_log):
    assert ff.is_enabled("clinic_a", "doctor_dashboard", log_path=flag_log) is False
    assert (
        ff.is_enabled("clinic_a", "doctor_dashboard", log_path=flag_log, default=True)
        is True
    )


def test_enable_writes_row(flag_log):
    evt = ff.enable("clinic_a", "doctor_dashboard", actor="alice")
    assert evt.enabled is True
    assert evt.flag == "doctor_dashboard"
    assert evt.tenant_id == "clinic_a"
    assert evt.actor == "alice"
    assert evt.cryptographic_signature
    rows = [json.loads(line) for line in flag_log.read_text().splitlines() if line]
    assert len(rows) == 1
    assert rows[0]["enabled"] is True


def test_disable_after_enable(flag_log):
    ff.enable("clinic_a", "doctor_dashboard")
    ff.disable("clinic_a", "doctor_dashboard", actor="bob")
    assert ff.is_enabled("clinic_a", "doctor_dashboard", log_path=flag_log) is False


def test_list_enabled(flag_log):
    ff.enable("clinic_a", "doctor_dashboard")
    ff.enable("clinic_a", "monthly_owner_email")
    ff.enable("clinic_a", "doctor_positive_feedback")
    ff.disable("clinic_a", "monthly_owner_email")
    enabled = ff.list_enabled("clinic_a", log_path=flag_log)
    assert enabled == {"doctor_dashboard", "doctor_positive_feedback"}


def test_tenant_isolation(flag_log):
    ff.enable("clinic_a", "doctor_dashboard")
    assert ff.is_enabled("clinic_b", "doctor_dashboard", log_path=flag_log) is False
    assert ff.list_enabled("clinic_b", log_path=flag_log) == set()


def test_flag_history(flag_log):
    ff.enable("clinic_a", "doctor_dashboard", actor="alice")
    ff.disable("clinic_a", "doctor_dashboard", actor="bob")
    ff.enable("clinic_a", "doctor_dashboard", actor="carol")
    hist = ff.flag_history("clinic_a", "doctor_dashboard", log_path=flag_log)
    assert len(hist) == 3
    assert [h.actor for h in hist] == ["alice", "bob", "carol"]
    assert [h.enabled for h in hist] == [True, False, True]


def test_enable_validates_inputs(flag_log):
    with pytest.raises(ValueError):
        ff.enable("", "doctor_dashboard")
    with pytest.raises(ValueError):
        ff.enable("clinic_a", "")


def test_signature_chain(flag_log):
    ff.enable("clinic_a", "doctor_dashboard")
    ff.enable("clinic_b", "monthly_owner_email")
    rows = [json.loads(line) for line in flag_log.read_text().splitlines() if line]
    assert rows[0]["previous_signature"] == "0" * 64
    assert rows[1]["previous_signature"] == rows[0]["cryptographic_signature"]


def test_register_flag(tmp_path: Path, monkeypatch):
    reg = tmp_path / "registry.json"
    monkeypatch.setenv("FEATURE_FLAG_REGISTRY", str(reg))
    assert ff.register_flag("custom_flag", "test") is True
    assert ff.register_flag("custom_flag", "test") is False  # idempotent
    assert "custom_flag" in json.loads(reg.read_text())


def test_bucket_for_deterministic():
    # Same inputs always produce the same bucket
    b1 = ff.bucket_for("doctor_dashboard", "clinic_a")
    b2 = ff.bucket_for("doctor_dashboard", "clinic_a")
    assert b1 == b2
    assert 0 <= b1 < 100


def test_bucket_for_spread():
    # Across many tenants the buckets should spread reasonably
    buckets = {ff.bucket_for("flag_x", f"clinic_{i}") for i in range(200)}
    assert len(buckets) > 50  # high cardinality — sha256 is well-mixed


def test_rollout_percent_zero_and_hundred():
    m = ff.rollout_percent("flag_x", 0)
    pred = m["_predicate_for_flag_x"]
    for i in range(50):
        assert pred(f"tenant_{i}") is False

    m = ff.rollout_percent("flag_x", 100)
    pred = m["_predicate_for_flag_x"]
    for i in range(50):
        assert pred(f"tenant_{i}") is True


def test_rollout_percent_validates():
    with pytest.raises(ValueError):
        ff.rollout_percent("flag_x", -1)
    with pytest.raises(ValueError):
        ff.rollout_percent("flag_x", 101)


def test_rollout_percent_approximate_count():
    # ~50% rollout should hit ~50% of tenants (within tolerance)
    m = ff.rollout_percent("flag_x", 50)
    pred = m["_predicate_for_flag_x"]
    hits = sum(1 for i in range(1000) if pred(f"tenant_{i}"))
    assert 400 <= hits <= 600, f"expected ~500, got {hits}"
