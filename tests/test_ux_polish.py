"""Tests for the UX-polish endpoints (kanban board: product-ux)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ai_billing_audit.clinical_note_storage import (
    append_encrypted_json_record,
    read_encrypted_json_records,
    write_encrypted_json_records,
)


@pytest.fixture
def ux_log_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("UX_POLISH_LOG_DIR", str(tmp_path))
    # Enable the no-auth dev mode so the FastAPI app accepts the
    # GET/POST calls below (see api.py _bearer_auth middleware).
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    yield tmp_path


@pytest.fixture
def client(ux_log_dir):
    from fastapi.testclient import TestClient
    from ai_billing_audit.api import app

    with TestClient(app) as c:
        yield c


# --- t_a852e3fb --------------------------------------------------------


def test_recent_activity_empty(client):
    r = client.get("/api/activity/recent")
    assert r.status_code == 200
    assert r.json() == {"events": []}


def test_recent_activity_returns_recent_rows(ux_log_dir, client):
    path = ux_log_dir / "audit_actions.jsonl"
    write_encrypted_json_records(
        path,
        [
            {
                "action": "audit_complete",
                "encounter_id": f"e{i}",
                "ts": time.time() - i,
            }
            for i in range(14, -1, -1)
        ],
    )
    # The ux_polish module captured _LOGS_DIR at import time; refresh
    # the path so the route sees the freshly-written fixture file.
    from ai_billing_audit import ux_polish

    ux_polish._LOGS_DIR = ux_log_dir
    r = client.get("/api/activity/recent?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert len(body["events"]) == 5
    # e0 is the most recent (ts=now-0), should be first after reverse.
    assert body["events"][0]["encounter_id"] == "e0"


# --- t_f9a8d929 --------------------------------------------------------


def test_undo_token_round_trip(client):
    r = client.post(
        "/api/undo-token",
        json={"action": "accept", "encounter_id": "e1", "finding_id": "f1"},
    )
    assert r.status_code == 200
    token = r.json()["token"]
    assert r.json()["window_seconds"] == 5
    r2 = client.post(f"/api/undo-token/{token}")
    assert r2.status_code == 200
    assert r2.json()["record"]["action"] == "accept"


def test_undo_token_expired(ux_log_dir, client):
    path = ux_log_dir / "undo_tokens.jsonl"
    append_encrypted_json_record(
        path,
        {
            "token": "abc",
            "action": "accept",
            "encounter_id": "e1",
            "finding_id": "f1",
            "ts": time.time() - 30,
        },
    )
    r = client.post("/api/undo-token/abc")
    assert r.status_code == 410


def test_undo_token_consume_writes_audit_row(ux_log_dir, client):
    from ai_billing_audit import ux_polish

    # The ux_polish module captured _LOGS_DIR at import; rebind it
    # to the fixture dir before either call so both writes land there.
    ux_polish._LOGS_DIR = ux_log_dir
    r = client.post(
        "/api/undo-token",
        json={"action": "dismiss", "encounter_id": "e9", "finding_id": "f3"},
    )
    assert r.status_code == 200
    token = r.json()["token"]
    r2 = client.post(f"/api/undo-token/{token}")
    assert r2.status_code == 200
    actions_path = ux_log_dir / "audit_actions.jsonl"
    assert actions_path.exists()
    rows = read_encrypted_json_records(actions_path)
    undo_rows = [r for r in rows if r.get("action") == "undo"]
    assert undo_rows, "consumed undo should write a tamper-evident row"
    assert undo_rows[0]["reverted_action"] == "dismiss"
    assert undo_rows[0]["encounter_id"] == "e9"


# --- t_28b8dbfa + t_af49b29a -------------------------------------------


def test_home_state_empty_when_no_encounters():
    from ai_billing_audit import ux_polish

    p = ux_polish.home_state_payload(0)
    assert p["empty"] is True
    assert "Upload" in p["empty_copy"] or "audit" in p["empty_copy"].lower()


def test_home_state_populated():
    from ai_billing_audit import ux_polish

    p = ux_polish.home_state_payload(5)
    assert p["empty"] is False


def test_error_state_copy_keys_present():
    from ai_billing_audit import ux_polish

    for k in ("audit_failed", "rate_limited", "tenant_unknown", "llm_unavailable"):
        assert k in ux_polish.ERROR_STATE_COPY
        assert ux_polish.ERROR_STATE_COPY[k]


# --- t_de2d2e0f --------------------------------------------------------


def test_sort_options_normalize():
    from ai_billing_audit import ux_polish

    assert ux_polish.normalize_sort(None) == "newest"
    assert ux_polish.normalize_sort("oldest") == "oldest"
    assert ux_polish.normalize_sort("highest_flagged") == "highest_flagged"
    assert ux_polish.normalize_sort("garbage") == "newest"
    assert ux_polish.normalize_sort("OLDEST_UNACTIONED") == "oldest_unactioned"


# --- t_ec0db7de --------------------------------------------------------


def test_quick_filters_known_and_unknown():
    from ai_billing_audit import ux_polish

    assert ux_polish.apply_quick_filter("only_critical") == {"min_severity": "critical"}
    assert ux_polish.apply_quick_filter("unknown") == {}


# --- t_71c708d3 --------------------------------------------------------


def test_this_week_summary_counts_only_recent():
    from ai_billing_audit import ux_polish

    now = time.time()
    events = [
        {"action": "audit_complete", "ts": now - 1},
        {"action": "flag", "ts": now - 2},
        {"action": "dismiss", "ts": now - 3},
        {"action": "audit_complete", "ts": now - 30 * 86400},  # old
    ]
    s = ux_polish.this_week_summary(events)
    assert s == {"audited": 1, "flagged": 1, "dismissed": 1}


# --- t_005e810a --------------------------------------------------------


def test_highlight_quote_wraps_match():
    from ai_billing_audit import ux_polish

    out = ux_polish.highlight_quote(
        "Patient has diabetes and hypertension.", "diabetes"
    )
    assert "<mark" in out and "diabetes" in out


def test_highlight_quote_no_match_returns_escaped():
    from ai_billing_audit import ux_polish

    out = ux_polish.highlight_quote("<script>x</script>", "nope")
    assert "&lt;script&gt;" in out


# --- t_aa36c525 --------------------------------------------------------


def test_rule_lookup_known_and_unknown():
    from ai_billing_audit import ux_polish

    rec = ux_polish.rule_lookup("AH.001")
    assert rec and "title" in rec and "text" in rec
    assert ux_polish.rule_lookup("ZZ.999") is None


def test_rule_lookup_endpoint(client):
    r = client.get("/rules/AH.001")
    assert r.status_code == 200
    body = r.json()
    assert body["rule_id"] == "AH.001"
    assert "title" in body


# --- t_d609557c --------------------------------------------------------


def test_audit_log_export_json(client):
    r = client.get("/api/audit-log/export?fmt=json")
    assert r.status_code == 200
    assert "json" in r.headers["content-type"]
    # body should be valid JSON (possibly empty list)
    json.loads(r.text)


def test_audit_log_export_csv(client):
    r = client.get("/api/audit-log/export?fmt=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]


def test_audit_log_export_jsonl(client):
    r = client.get("/api/audit-log/export?fmt=jsonl")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert r.headers["content-disposition"].endswith('audit-log.jsonl"')


def test_audit_log_export_bad_fmt(client):
    r = client.get("/api/audit-log/export?fmt=xml")
    assert r.status_code == 400


# --- t_d9713083 --------------------------------------------------------


def test_sticky_note_round_trip(ux_log_dir, client):
    # swarm-audit B-Sec-1: user_id is now from the authenticated
    # session (X-User-Id header), not from the request body. The
    # POST body must omit user_id; the GET no longer takes query
    # params; the test now sends the auth header explicitly.
    r = client.post(
        "/encounter/enc-9/note",
        headers={"X-User-Id": "u1", "X-User-Role": "biller"},
        json={"note": "follow-up Tue"},
    )
    assert r.status_code == 200
    assert b"follow-up Tue" not in (ux_log_dir / "sticky_notes.jsonl").read_bytes()
    r2 = client.get(
        "/encounter/enc-9/note",
        headers={"X-User-Id": "u1", "X-User-Role": "biller"},
    )
    assert r2.status_code == 200
    assert "follow-up Tue" in r2.text


# --- t_b0e3dd73 --------------------------------------------------------


def test_reorder_endpoint(client):
    r = client.post(
        "/api/encounters/reorder",
        headers={"X-User-Id": "u1", "X-User-Role": "biller"},
        json={"ordering": ["a", "b", "c"]},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "n": 3}


def test_reorder_rejects_non_list(client):
    r = client.post(
        "/api/encounters/reorder",
        headers={"X-User-Id": "u1", "X-User-Role": "biller"},
        json={"ordering": "not-a-list"},
    )
    assert r.status_code == 400


# --- t_0ea1cdce --------------------------------------------------------


def test_rule_tuning_round_trip(client):
    # swarm-audit H-Sec-1: rule tuning is admin-only now.
    admin_h = {"X-User-Id": "ops-1", "X-User-Role": "admin"}
    r = client.post(
        "/api/clinic/clinic-7/rules",
        headers=admin_h,
        json={"enabled": ["AH.001"], "suppressed": ["AH.014"]},
    )
    assert r.status_code == 200
    r2 = client.get("/api/clinic/clinic-7/rules", headers=admin_h)
    body = r2.json()
    assert "AH.001" in body["enabled"]
    assert "AH.014" in body["suppressed"]


# --- t_24c99ece --------------------------------------------------------


def test_llm_choice_endpoint(client):
    admin_h = {"X-User-Id": "ops-1", "X-User-Role": "admin"}
    r = client.get("/api/clinic/c1/llm", headers=admin_h)
    assert r.status_code == 200
    body = r.json()
    assert body["clinic_id"] == "c1"
    assert "provider" in body and "model" in body


# --- t_59fe7e05 --------------------------------------------------------


def test_notifications_endpoint(client):
    r = client.get("/api/notifications?user_id=u1")
    assert r.status_code == 200
    assert r.json() == {"items": []}


# --- t_b716e54c + t_77c0c140 + t_e7421098 -----------------------------


def test_email_prefs_defaults(client):
    r = client.get("/api/email-prefs?user_id=new-user")
    assert r.status_code == 200
    body = r.json()
    assert body["digest_daily"] is False
    assert body["welcome"] is True


def test_email_prefs_set(client):
    r = client.post("/api/email-prefs", json={"user_id": "u1", "digest_daily": True})
    assert r.status_code == 200
    r2 = client.get("/api/email-prefs?user_id=u1")
    assert r2.json()["digest_daily"] is True


# --- t_7e558a6a --------------------------------------------------------


def test_bulk_confirm_validate(client):
    r = client.post(
        "/api/bulk/confirm", json={"action": "accept", "encounter_ids": ["e1", "e2"]}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "2" in body["message"]


def test_bulk_confirm_rejects_bad_action(client):
    r = client.post(
        "/api/bulk/confirm", json={"action": "obliterate", "encounter_ids": ["e1"]}
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_bulk_confirm_rejects_too_many(client):
    r = client.post(
        "/api/bulk/confirm", json={"action": "accept", "encounter_ids": ["x"] * 501}
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False


# t_7e558a6a — destructive actions require typing "confirm"
def test_bulk_confirm_dismiss_requires_confirm_phrase(client):
    r = client.post(
        "/api/bulk/confirm",
        json={"action": "dismiss", "encounter_ids": ["e1", "e2"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "confirm" in body["message"].lower()


def test_bulk_confirm_dismiss_accepts_with_confirm_phrase(client):
    r = client.post(
        "/api/bulk/confirm",
        json={
            "action": "dismiss",
            "encounter_ids": ["e1", "e2"],
            "confirm_phrase": "confirm",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "2" in body["message"]


def test_bulk_confirm_large_accept_requires_confirm(client):
    # 25+ accept also requires the confirm phrase (mass-accept guard).
    ids = [f"e{i}" for i in range(30)]
    r = client.post(
        "/api/bulk/confirm", json={"action": "accept", "encounter_ids": ids}
    )
    assert r.json()["ok"] is False
    r2 = client.post(
        "/api/bulk/confirm",
        json={"action": "accept", "encounter_ids": ids, "confirm_phrase": "CONFIRM"},
    )
    assert r2.json()["ok"] is True


def test_bulk_confirm_small_accept_does_not_require_confirm(client):
    # 3-item accept is reversible via undo-token; no confirm phrase needed.
    r = client.post(
        "/api/bulk/confirm",
        json={"action": "accept", "encounter_ids": ["a", "b", "c"]},
    )
    assert r.json()["ok"] is True


# t_59fe7e05 — in-app notification record + mark-read
def test_notifications_record_then_list(client):
    # swarm-audit B-Sec-1: user_id comes from the X-User-Id header.
    rec = client.post(
        "/api/notifications",
        headers={"X-User-Id": "u-notify", "X-User-Role": "biller"},
        json={
            "title": "Audit flagged",
            "body": "Encounter enc-1 has 3 findings",
            "link": "/encounter/enc-1",
        },
    )
    assert rec.status_code == 200
    event_id = rec.json()["record"]["event_id"]
    listed = client.get(
        "/api/notifications",
        headers={"X-User-Id": "u-notify", "X-User-Role": "biller"},
    ).json()
    assert any(it.get("event_id") == event_id for it in listed["items"])


def test_notifications_mark_read(client):
    rec = client.post(
        "/api/notifications",
        headers={"X-User-Id": "u-mr", "X-User-Role": "biller"},
        json={"title": "hi"},
    ).json()
    eid = rec["record"]["event_id"]
    r = client.post(
        f"/api/notifications/{eid}/read",
        headers={"X-User-Id": "u-mr", "X-User-Role": "biller"},
    )
    assert r.status_code == 200
    items = client.get(
        "/api/notifications",
        headers={"X-User-Id": "u-mr", "X-User-Role": "biller"},
    ).json()["items"]
    latest = next(it for it in items if it.get("event_id") == eid)
    assert latest.get("read") is True


def test_notifications_mark_read_other_user_404(client):
    # Owner records a notification; stranger tries to mark it read.
    rec = client.post(
        "/api/notifications",
        headers={"X-User-Id": "owner", "X-User-Role": "biller"},
        json={"title": "hi"},
    ).json()
    eid = rec["record"]["event_id"]
    r = client.post(
        f"/api/notifications/{eid}/read",
        headers={"X-User-Id": "stranger", "X-User-Role": "biller"},
    )
    assert r.status_code == 404


# t_77c0c140 — re-engagement status
def test_re_engagement_no_login_yet(client):
    # Fresh user — no last_login row → should_send False.
    r = client.get(
        "/api/re-engagement",
        headers={"X-User-Id": "brand-new-user-xyz", "X-User-Role": "biller"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["last_login_ts"] is None
    assert body["days_since_login"] is None
    assert body["should_send"] is False


def test_re_engagement_recent_login_no_nudge(client):
    # Recent login → should_send False.
    from ai_billing_audit import ux_polish as up

    up._append_jsonl(
        up._log_path("last_login"),
        {"user_id": "u-recent", "ts": time.time()},
    )
    r = client.get(
        "/api/re-engagement",
        headers={"X-User-Id": "u-recent", "X-User-Role": "biller"},
    ).json()
    assert r["days_since_login"] < 7.0
    assert r["should_send"] is False


def test_re_engagement_old_login_should_send(client):
    # 8-day-old login, no recent nudge → should_send True.
    from ai_billing_audit import ux_polish as up

    eight_days_ago = time.time() - 8 * 86400.0
    up._append_jsonl(
        up._log_path("last_login"),
        {"user_id": "u-stale", "ts": eight_days_ago},
    )
    r = client.get(
        "/api/re-engagement",
        headers={"X-User-Id": "u-stale", "X-User-Role": "biller"},
    ).json()
    assert r["days_since_login"] >= 7.0
    assert r["should_send"] is True


# t_24c99ece — per-tenant LLM choice persistence
def test_llm_choice_set_and_get(client):
    r = client.post(
        "/api/clinic/clinic-llm-1/llm",
        json={"provider": "claude", "model": "claude-3-5-sonnet", "user_id": "admin"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "claude"
    assert body["model"] == "claude-3-5-sonnet"
    r2 = client.get("/api/clinic/clinic-llm-1/llm").json()
    assert r2["provider"] == "claude"
    assert r2["model"] == "claude-3-5-sonnet"


def test_llm_choice_set_rejects_bad_provider(client):
    r = client.post(
        "/api/clinic/clinic-llm-2/llm",
        json={"provider": "gpt-99-unknown", "model": "x"},
    )
    assert r.status_code == 400


# t_d9713083 — sticky notes are private (filter by user_id)
def test_sticky_note_private_to_user(client):
    # swarm-audit B-Sec-1: user_id is now resolved from the
    # authenticated session (X-User-Id header), not from the
    # request body or query string. Cross-user reads must fail.
    client.post(
        "/encounter/enc-priv/note",
        headers={"X-User-Id": "u-A", "X-User-Role": "biller"},
        json={"note": "A's private note"},
    )
    r_a = client.get(
        "/encounter/enc-priv/note",
        headers={"X-User-Id": "u-A", "X-User-Role": "biller"},
    )
    r_b = client.get(
        "/encounter/enc-priv/note",
        headers={"X-User-Id": "u-B", "X-User-Role": "biller"},
    )
    assert "A's private note" in r_a.text
    assert r_b.text == "", "user u-B saw u-A's sticky note — IDOR regression"


def test_sticky_note_admin_sees_all(client):
    # swarm-audit B-Sec-1: the user_id=* query param is REMOVED.
    # Admin role now sees across users (the role check is the gate).
    client.post(
        "/encounter/enc-admin/note",
        headers={"X-User-Id": "u-X", "X-User-Role": "biller"},
        json={"note": "shared admin"},
    )
    r = client.get(
        "/encounter/enc-admin/note",
        headers={"X-User-Id": "ops-1", "X-User-Role": "admin"},
    )
    assert "shared admin" in r.text
    # And a biller CANNOT see across users anymore (no query bypass).
    r_biller = client.get(
        "/encounter/enc-admin/note",
        headers={"X-User-Id": "u-Y", "X-User-Role": "biller"},
    )
    assert "shared admin" not in r_biller.text


# --- t_a5bd33af --------------------------------------------------------


def test_wcag_status(client):
    r = client.get("/api/wcag")
    assert r.status_code == 200
    body = r.json()
    assert body["n_ok"] >= 15
    assert "1.4.1_use_of_color" in body["criteria"]


# --- t_3f22b3b8 --------------------------------------------------------


def test_print_view_returns_html(client):
    r = client.get("/encounter/enc-77/print")
    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower()
    assert "@media print" in r.text


# t_7e558a6a — bulk confirm modal partial must ship the JS contract
def test_bulk_confirm_modal_template_exists():
    template = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ai_billing_audit"
        / "templates"
        / "_bulk_confirm_modal.html"
    )
    assert template.exists(), f"missing template: {template}"
    text = template.read_text()
    assert "data-bulk-confirm" in text
    assert "data-bulk-confirm-phrase" in text
    assert "data-bulk-confirm-submit" in text
    assert "openBulkConfirmModal" in text
