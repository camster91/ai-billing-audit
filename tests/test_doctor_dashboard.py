"""Tests for doctor_dashboard module (kanban t_af26abdb, t_df188436, t_f5ea3bf2, t_585dcaed, t_267a1ad6)."""
from __future__ import annotations

import time

import pytest

from ai_billing_audit import doctor_dashboard as dd


# Test fixtures --------------------------------------------------------------


def _enc(
    eid: str,
    provider: str,
    dos: str,
    findings: list[dict] | None = None,
) -> dict:
    return {
        "encounter_id": eid,
        "provider_npi": provider,
        "date_of_service": dos,
        "patient_label": "the patient",
        "findings": findings or [],
    }


def _finding(rule: str, severity: str = "medium", body_site: str = "") -> dict:
    return {
        "finding_id": f"f_{rule}",
        "rule_id": rule,
        "severity": severity,
        "body_site": body_site,
    }


# t_af26abdb: Doctor dashboard view -----------------------------------------


def test_doctor_encounters_filters_by_provider():
    log = [
        _enc("e1", "doc_a", "2026-06-20"),
        _enc("e2", "doc_b", "2026-06-20"),
        _enc("e3", "doc_a", "2026-06-22", findings=[_finding("MOD-25")]),
    ]
    out = dd.doctor_encounters_for("doc_a", log, lookback_days=30, now_ts=time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0)))
    assert len(out) == 2
    assert all(e["patient_label"] == "the patient" for e in out)


def test_doctor_encounters_empty_provider_returns_empty():
    assert dd.doctor_encounters_for("", [], lookback_days=30) == []


def test_doctor_encounters_clean_encounter_has_no_fix():
    log = [_enc("e1", "doc_a", "2026-06-20")]  # no findings
    out = dd.doctor_encounters_for("doc_a", log, lookback_days=30, now_ts=time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0)))
    assert len(out) == 1
    e = out[0]
    assert e["needs_fix"] is False
    assert e["what_wrong"] == ""
    assert e["fix_suggestion"] == ""


def test_doctor_encounters_flagged_uses_worst_finding():
    log = [
        _enc("e1", "doc_a", "2026-06-22", findings=[
            _finding("MOD-25", "low"),
            _finding("MOD-59", "high"),
        ]),
    ]
    out = dd.doctor_encounters_for("doc_a", log, lookback_days=30, now_ts=time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0)))
    assert out[0]["severity"] == "high"
    assert out[0]["needs_fix"] is True
    assert "modifier" in out[0]["what_wrong"].lower() or "bundled" in out[0]["what_wrong"].lower()


def test_doctor_encounters_lookback_window_filters_old():
    log = [
        _enc("e1", "doc_a", "2025-01-01", findings=[_finding("MOD-25")]),
        _enc("e2", "doc_a", "2026-06-22", findings=[_finding("MOD-25")]),
    ]
    out = dd.doctor_encounters_for("doc_a", log, lookback_days=14, now_ts=time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0)))
    assert len(out) == 1
    assert out[0]["encounter_id"] == "e2"


def test_doctor_encounters_sorted_most_recent_first():
    log = [
        _enc("e1", "doc_a", "2026-06-20"),
        _enc("e2", "doc_a", "2026-06-22"),
        _enc("e3", "doc_a", "2026-06-21"),
    ]
    out = dd.doctor_encounters_for("doc_a", log, lookback_days=30, now_ts=time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0)))
    assert [e["encounter_id"] for e in out] == ["e2", "e3", "e1"]


# t_df188436: Doctor-side suggestion ----------------------------------------


def test_suggest_fix_for_known_rules():
    assert "modifier" in dd.suggest_fix_for({"rule_id": "MOD-25"}).lower()
    assert "modifier" in dd.suggest_fix_for({"rule_id": "MOD-59"}).lower()
    assert "time" in dd.suggest_fix_for({"rule_id": "TIME"}).lower()
    assert "decision" in dd.suggest_fix_for({"rule_id": "E/M-LEVEL"}).lower()


def test_suggest_fix_for_unknown_rule_returns_generic():
    out = dd.suggest_fix_for({"rule_id": "WEIRD-RULE"})
    assert "decision" in out.lower() or "documentation" in out.lower()


# t_f5ea3bf2: Fix-it re-audit payload ---------------------------------------


def test_fixit_reaudit_payload_includes_note_hash():
    payload = dd.fixit_reaudit_payload(
        encounter_id="enc_123",
        updated_note_text="The patient is a 47yo female with cough x 3 weeks.",
        provider_npi="doc_a",
    )
    assert payload["encounter_id"] == "enc_123"
    assert payload["provider_npi"] == "doc_a"
    assert payload["job_type"] == "re_audit"
    assert payload["trigger"] == "doctor_fixit"
    assert len(payload["updated_note_sha256"]) == 64
    assert payload["updated_note_chars"] == len("The patient is a 47yo female with cough x 3 weeks.")


def test_fixit_reaudit_payload_has_job_id():
    p1 = dd.fixit_reaudit_payload(encounter_id="e1", updated_note_text="x", provider_npi="d")
    p2 = dd.fixit_reaudit_payload(encounter_id="e1", updated_note_text="x", provider_npi="d")
    assert p1["job_id"] != p2["job_id"]  # unique per click


def test_fixit_reaudit_payload_uses_tenant_depth_strategy():
    p = dd.fixit_reaudit_payload(encounter_id="e1", updated_note_text="x", provider_npi="d")
    assert p["depth_strategy"] == "tenant_default_or_global"


# t_585dcaed: Doctor weekly digest ----------------------------------------


def test_weekly_digest_clean_count():
    log = [
        _enc("e1", "doc_a", "2026-06-20"),
        _enc("e2", "doc_a", "2026-06-21"),
        _enc("e3", "doc_a", "2026-06-22", findings=[_finding("MOD-25")]),
    ]
    digest = dd.doctor_weekly_digest(
        "doc_a",
        log,
        to_email="doc@example.com",
        saved_per_clean_usd=200.0,
        lookback_days=7,
        now_ts=time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0)),
    )
    assert digest.clean_count == 2
    assert digest.flagged_count == 1
    assert digest.saved_usd == 400.0
    assert "2 clean" in digest.subject
    assert "1 flagged" in digest.subject
    assert "saved $400" in digest.body_text or "$400" in digest.body_text


def test_weekly_digest_positive_framing_comes_first():
    log = [
        _enc("e1", "doc_a", "2026-06-20"),
        _enc("e2", "doc_a", "2026-06-22", findings=[_finding("MOD-25")]),
    ]
    digest = dd.doctor_weekly_digest(
        "doc_a", log, lookback_days=7, now_ts=time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0))
    )
    # Subject opens with the win, not the loss
    assert digest.subject.index("clean") < digest.subject.index("flagged")


def test_weekly_digest_caps_flagged_listing():
    log = [
        _enc(f"e{i}", "doc_a", f"2026-06-{20 + (i % 5):02d}", findings=[_finding("MOD-25")])
        for i in range(10)
    ]
    digest = dd.doctor_weekly_digest(
        "doc_a", log, lookback_days=7, now_ts=time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0))
    )
    assert "and 5 more" in digest.body_text or "and 6 more" in digest.body_text


def test_weekly_digest_to_dict_round_trip():
    log = [_enc("e1", "doc_a", "2026-06-20")]
    d = dd.doctor_weekly_digest(
        "doc_a", log, to_email="d@x.com", lookback_days=7, now_ts=time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0))
    ).to_dict()
    for key in ("event_id", "subject", "body_text", "clean_count", "flagged_count", "saved_usd", "week_label", "queued_at"):
        assert key in d


# t_267a1ad6: Doctor effectiveness metric ----------------------------------


def test_effectiveness_no_data_returns_friendly_message():
    out = dd.doctor_effectiveness("doc_a", [], now_ts=time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0)))
    assert out["headline"] == "Not enough notes yet to measure."
    assert out["delta_pct_points"] == 0.0


def test_effectiveness_improvement_is_positive():
    # 30 days: 4 of 10 clean (40%); 30-60 days ago: 2 of 10 clean (20%).
    # delta should be +20 points.
    now = time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0))
    log = []
    for i in range(10):
        dos = time.strftime("%Y-%m-%d", time.gmtime(now - i * 86_400))  # recent
        log.append(_enc(f"r{i}", "doc_a", dos, findings=[] if i < 4 else [_finding("MOD-25")]))
    for i in range(10):
        dos = time.strftime("%Y-%m-%d", time.gmtime(now - 45 * 86_400 - i * 86_400))  # prior
        log.append(_enc(f"p{i}", "doc_a", dos, findings=[] if i < 2 else [_finding("MOD-25")]))
    out = dd.doctor_effectiveness("doc_a", log, prior_window_days=30, now_ts=now)
    assert out["n_recent"] == 10
    assert out["n_prior"] == 10
    assert out["clean_rate_recent"] == 0.4
    assert out["clean_rate_prior"] == 0.2
    assert out["delta_pct_points"] == 20.0
    assert "better" in out["headline"].lower()


def test_effectiveness_decline_is_negative():
    now = time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0))
    log = []
    for i in range(10):
        dos = time.strftime("%Y-%m-%d", time.gmtime(now - i * 86_400))
        log.append(_enc(f"r{i}", "doc_a", dos, findings=[] if i < 2 else [_finding("MOD-25")]))
    for i in range(10):
        dos = time.strftime("%Y-%m-%d", time.gmtime(now - 45 * 86_400 - i * 86_400))
        log.append(_enc(f"p{i}", "doc_a", dos, findings=[] if i < 8 else [_finding("MOD-25")]))
    out = dd.doctor_effectiveness("doc_a", log, prior_window_days=30, now_ts=now)
    assert out["delta_pct_points"] < 0
    assert "worse" in out["headline"].lower()


def test_effectiveness_steady_state_message():
    now = time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0))
    log = []
    for i in range(10):
        dos = time.strftime("%Y-%m-%d", time.gmtime(now - i * 86_400))
        log.append(_enc(f"r{i}", "doc_a", dos, findings=[] if i < 5 else [_finding("MOD-25")]))
    for i in range(10):
        dos = time.strftime("%Y-%m-%d", time.gmtime(now - 45 * 86_400 - i * 86_400))
        log.append(_enc(f"p{i}", "doc_a", dos, findings=[] if i < 5 else [_finding("MOD-25")]))
    out = dd.doctor_effectiveness("doc_a", log, prior_window_days=30, now_ts=now)
    assert "steady" in out["headline"].lower()


def test_effectiveness_no_prior_window_says_so():
    now = time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0))
    log = [_enc("e1", "doc_a", "2026-06-22")]
    out = dd.doctor_effectiveness("doc_a", log, prior_window_days=30, now_ts=now)
    assert "1 clean notes" in out["headline"] or "wrote" in out["headline"].lower()


def test_effectiveness_empty_provider():
    out = dd.doctor_effectiveness("", [], now_ts=time.mktime((2026, 6, 25, 0, 0, 0, 0, 0, 0)))
    assert out["provider_npi"] == ""
    assert out["n_recent"] == 0