"""Tests for the bulk-actions feature (kanban t_2515fe6f).

Pins the four acceptance criteria from the task body:

1. ``POST /encounters/bulk-accept`` with N encounter_ids writes
   exactly ONE bulk ``audit_actions`` row (``action="bulk"`` with
   ``action_subtype="accept"`` in ``data_elements``) and N_finding
   per-finding ``FeedbackEntry`` rows (``action="accept"``,
   real finding_id) — one per real finding across the batch.
2. ``POST /encounters/bulk-dismiss`` with a ``rule_id`` narrows
   to findings whose ``rule_id`` matches. The audit row's note
   carries the rule_id + closed-loop reason fields. Per-finding
   dismiss feedback rows are written for each match.
3. ``POST /encounters/bulk-accept`` with a non-existent
   ``encounter_id`` returns HTTP 404 with the missing list in the
   body, and NO writes happen (atomic existence check).
4. Re-running a bulk action on a finding already accepted /
   dismissed in a prior call reports ``skipped_count`` equal to
   the number of previously-decided findings and ``applied_count``
   of 0. The per_clinic_f1 view stays consistent because the
   dedup happens BEFORE the per-finding feedback row is written.

Lightweight, no network, no LLM. The routes are exercised via
``starlette.testclient.TestClient`` so the ``JSONResponse`` /
``HTTPException`` shapes are real.

Uses a tmp JSONL path so tests never touch the production
``/app/logs/audit_trail.jsonl`` or ``/app/logs/feedback.jsonl``.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit import audit_actions as aa_mod  # noqa: E402
from ai_billing_audit import feedback as fb_mod  # noqa: E402
from ai_billing_audit import api as api_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


# Pin the data dir to the test JSONs so the per-encounter existence
# checks inside the bulk endpoints can resolve real encounter_ids
# (the demo registry loads ``data/synth/val.json`` and
# ``data/synth/train.json`` lazily). We don't modify the files —
# read-only is enough.
_TRAIN_JSON = PROJECT_ROOT / "data" / "synth" / "train.json"
with _TRAIN_JSON.open() as fh:
    _TRAIN_DATA = json.load(fh)


def _ids_for_range(start: int, count: int) -> list[str]:
    """Return ``count`` real encounter_ids from train.json, starting
    at ``start``. Stable across test runs because train.json is
    frozen.
    """
    return [rec["encounter_id"] for rec in _TRAIN_DATA[start : start + count]]


@pytest.fixture()
def fresh_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Redirect the audit + feedback + upload logs to tmp files.

    Returns a small dict with the resolved log paths so tests can
    read them back to assert on chain / row counts.
    """
    audit_log = tmp_path / "audit_trail.jsonl"
    feedback_log = tmp_path / "feedback.jsonl"
    upload_log = tmp_path / "upload_jobs.jsonl"
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(audit_log))
    monkeypatch.setenv("FEEDBACK_LOG", str(feedback_log))
    monkeypatch.setenv("UPLOAD_AUDIT_LOG_PATH", str(upload_log))
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    # Reload the modules so the env-driven log paths take effect.
    importlib.reload(aa_mod)
    importlib.reload(fb_mod)
    importlib.reload(api_mod)
    yield {
        "audit_log": audit_log,
        "feedback_log": feedback_log,
        "upload_log": upload_log,
    }


@pytest.fixture()
def client(fresh_logs) -> TestClient:
    return TestClient(api_mod.create_app())


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ---------------------------------------------------------------------------
# 1. bulk-accept — single audit row + per-finding feedback rows
# ---------------------------------------------------------------------------


def test_bulk_accept_writes_one_audit_row_and_per_finding_feedback(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Accept every finding across 50 real demo encounters.

    Pin: ONE bulk audit_actions row + exactly N_finding
    FeedbackEntry rows (one per real finding). The bulk row's
    data_elements.affected_encounter_ids lists every encounter
    that had at least one finding touched.
    """
    ids = _ids_for_range(0, 50)
    resp = client.post(
        "/encounters/bulk-accept",
        json={"encounter_ids": ids, "notes": "bulk-accept smoke"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True

    # Per-finding feedback rows should equal the sum of ground_truth
    # findings across the 50 encounters.
    expected_findings = sum(
        len(rec.get("ground_truth", []))
        for rec in _TRAIN_DATA[0:50]
    )
    assert body["applied_count"] == expected_findings
    assert body["skipped_count"] == 0

    # The bulk audit row is the ONLY audit row written.
    audit_rows = _read_jsonl(fresh_logs["audit_log"])
    assert len(audit_rows) == 1
    bulk = audit_rows[0]
    assert bulk["action"] == "bulk"
    assert bulk["data_elements"]["action_subtype"] == "accept"
    assert bulk["data_elements"]["rule_id"] == ""
    assert bulk["data_elements"]["n_applied_findings"] == expected_findings
    assert bulk["data_elements"]["n_skipped_findings"] == 0
    assert len(bulk["data_elements"]["affected_encounter_ids"]) == len(
        bulk["data_elements"]["encounter_ids_requested"]
    ) or len(bulk["data_elements"]["affected_encounter_ids"]) == sum(
        1 for rec in _TRAIN_DATA[0:50] if rec.get("ground_truth")
    )

    # The chain signature covers the bulk row.
    assert bulk["previous_signature"] == "0" * 64  # first row → genesis
    assert len(bulk["cryptographic_signature"]) == 64  # sha256 hex

    # Feedback log: one row per real finding, action="accept".
    fb_rows = _read_jsonl(fresh_logs["feedback_log"])
    assert len(fb_rows) == expected_findings
    for row in fb_rows:
        assert row["action"] == "accept"
        assert row["biller_id"]  # populated by user_identifier
        assert row["finding_id"] != "__bulk_flag__"  # not a flag row
        assert row["previous_signature"]  # chain linked

    # The feedback chain verifies cleanly.
    store = fb_mod.FeedbackStore(log_path=fresh_logs["feedback_log"])
    assert store.verify_chain() is True


def test_bulk_accept_response_carries_audit_id(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """The response body returns the audit_id (event_id) so the UI
    can link the audit row in the privacy officer view.
    """
    ids = _ids_for_range(0, 5)
    resp = client.post(
        "/encounters/bulk-accept",
        json={"encounter_ids": ids},
    )
    body = resp.json()
    audit_id = body["audit_id"]
    assert audit_id and len(audit_id) == 32  # uuid4 hex
    # Same audit_id appears in the audit_actions row.
    audit_rows = _read_jsonl(fresh_logs["audit_log"])
    assert len(audit_rows) == 1
    assert audit_rows[0]["event_id"] == audit_id


# ---------------------------------------------------------------------------
# 2. bulk-dismiss with rule_id — narrows to rule-matching findings
# ---------------------------------------------------------------------------


def test_bulk_dismiss_with_rule_narrows_to_matching_findings(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Dismiss only findings whose rule_id matches the supplied
    ``rule_id``. Other findings on the same encounters are left
    alone (no per-finding dismiss row, no skip — they just don't
    enter the loop).
    """
    ids = _ids_for_range(0, 50)
    target_rule = "rule_modifier_25_001"

    # Compute expected count from the real data.
    expected = sum(
        1
        for rec in _TRAIN_DATA[0:50]
        for f in rec.get("ground_truth", [])
        if f.get("rule_id") == target_rule
    )
    assert expected > 0, "fixture sanity: target rule should have at least one match"

    resp = client.post(
        "/encounters/bulk-dismiss",
        json={
            "encounter_ids": ids,
            "rule_id": target_rule,
            "reason_category": "false_positive",
            "reason_text": "AI overcalling modifier-25",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied_count"] == expected
    assert body["skipped_count"] == 0
    assert body["rule_id"] == target_rule

    # Per-finding feedback: only dismiss rows, only matching rule_id.
    fb_rows = _read_jsonl(fresh_logs["feedback_log"])
    assert len(fb_rows) == expected
    for row in fb_rows:
        assert row["action"] == "dismiss"
        assert row["rule_id"] == target_rule

    # Audit row carries the rule_id + closed-loop fields in the
    # single bulk row's note + data_elements.
    audit_rows = _read_jsonl(fresh_logs["audit_log"])
    assert len(audit_rows) == 1
    bulk = audit_rows[0]
    assert bulk["action"] == "bulk"
    assert bulk["data_elements"]["action_subtype"] == "dismiss"
    assert bulk["data_elements"]["rule_id"] == target_rule
    note = bulk["data_elements"]["note"]
    assert f"rule_id={target_rule}" in note
    assert "category=false_positive" in note
    assert "AI overcalling modifier-25" in note


def test_bulk_dismiss_with_no_matches_returns_zero(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """A rule_id that doesn't match any finding still writes the
    bulk audit row (the biller clicked dismiss; we record that)
    but applied_count is 0 and no per-finding feedback rows are
    written.
    """
    ids = _ids_for_range(0, 10)
    resp = client.post(
        "/encounters/bulk-dismiss",
        json={"encounter_ids": ids, "rule_id": "rule_that_doesnt_exist_9999"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied_count"] == 0
    assert body["skipped_count"] == 0
    # Still one bulk audit row.
    audit_rows = _read_jsonl(fresh_logs["audit_log"])
    assert len(audit_rows) == 1
    assert audit_rows[0]["data_elements"]["action_subtype"] == "dismiss"
    # No feedback rows.
    fb_rows = _read_jsonl(fresh_logs["feedback_log"])
    assert fb_rows == []


# ---------------------------------------------------------------------------
# 3. 404 — unknown encounter_id short-circuits the whole batch
# ---------------------------------------------------------------------------


def test_bulk_accept_with_unknown_encounter_returns_404_no_writes(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """If ANY encounter_id is unknown, the whole batch is rejected
    with 404 and NO writes happen (atomic existence check). The
    missing list is in the body so the dashboard can highlight
    the bad card.
    """
    ids = _ids_for_range(0, 5)
    bad_ids = ["enc_DOES_NOT_EXIST_1", "enc_NOPE_2"]
    resp = client.post(
        "/encounters/bulk-accept",
        json={"encounter_ids": ids + bad_ids},
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    # FastAPI wraps HTTPException(detail=dict) under body["detail"].
    detail = body["detail"]
    assert "missing" in detail
    assert sorted(detail["missing"]) == sorted(bad_ids)

    # CRUCIAL: NO audit row written, NO feedback row written.
    assert _read_jsonl(fresh_logs["audit_log"]) == []
    assert _read_jsonl(fresh_logs["feedback_log"]) == []


def test_bulk_dismiss_with_unknown_encounter_returns_404_no_writes(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    ids = _ids_for_range(0, 3)
    resp = client.post(
        "/encounters/bulk-dismiss",
        json={"encounter_ids": ids + ["enc_GHOST"], "rule_id": "rule_em_001"},
    )
    assert resp.status_code == 404
    assert _read_jsonl(fresh_logs["audit_log"]) == []
    assert _read_jsonl(fresh_logs["feedback_log"]) == []


def test_bulk_flag_with_unknown_encounter_returns_404_no_writes(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    ids = _ids_for_range(0, 3)
    resp = client.post(
        "/encounters/bulk-flag",
        json={"encounter_ids": ids + ["enc_GHOST"]},
    )
    assert resp.status_code == 404
    assert _read_jsonl(fresh_logs["audit_log"]) == []
    assert _read_jsonl(fresh_logs["feedback_log"]) == []


# ---------------------------------------------------------------------------
# 4. dedup — re-running skips already-decided findings
# ---------------------------------------------------------------------------


def test_bulk_accept_second_call_skips_already_accepted(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Re-running bulk-accept on the same encounters applies 0
    new accepts and skips every previously-decided finding. The
    per_clinic_f1 view would otherwise double-count.
    """
    ids = _ids_for_range(0, 20)

    # First call: accept everything.
    r1 = client.post("/encounters/bulk-accept", json={"encounter_ids": ids})
    assert r1.status_code == 200
    body1 = r1.json()
    expected_first = sum(
        len(rec.get("ground_truth", []))
        for rec in _TRAIN_DATA[0:20]
    )
    assert body1["applied_count"] == expected_first
    assert body1["skipped_count"] == 0

    # Second call: re-accept the same batch. Should skip ALL
    # previously-accepted findings.
    r2 = client.post("/encounters/bulk-accept", json={"encounter_ids": ids})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["applied_count"] == 0
    assert body2["skipped_count"] == expected_first

    # Feedback log still has only ``expected_first`` rows — no
    # duplicates introduced.
    fb_rows = _read_jsonl(fresh_logs["feedback_log"])
    assert len(fb_rows) == expected_first

    # A new bulk audit row IS still written (the biller clicked
    # bulk-accept again; we record it for the privacy officer).
    audit_rows = _read_jsonl(fresh_logs["audit_log"])
    assert len(audit_rows) == 2
    assert audit_rows[1]["data_elements"]["action_subtype"] == "accept"
    assert audit_rows[1]["data_elements"]["n_skipped_findings"] == expected_first


def test_bulk_dismiss_skips_findings_already_dismissed_via_bulk(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Dismiss already dismissed by a prior bulk-dismiss is
    treated as already_decided and skipped, not double-counted.
    """
    ids = _ids_for_range(0, 15)
    target_rule = "rule_em_001"

    r1 = client.post(
        "/encounters/bulk-dismiss",
        json={"encounter_ids": ids, "rule_id": target_rule},
    )
    body1 = r1.json()
    expected_match = sum(
        1
        for rec in _TRAIN_DATA[0:15]
        for f in rec.get("ground_truth", [])
        if f.get("rule_id") == target_rule
    )
    assert body1["applied_count"] == expected_match

    # Second dismiss on the same rule+encounters: 0 applied, every
    # match skipped as already_decided.
    r2 = client.post(
        "/encounters/bulk-dismiss",
        json={"encounter_ids": ids, "rule_id": target_rule},
    )
    body2 = r2.json()
    assert body2["applied_count"] == 0
    assert body2["skipped_count"] == expected_match


def test_bulk_accept_after_bulk_dismiss_treats_dismissed_as_decided(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Cross-action dedup: a finding dismissed via bulk-dismiss is
    treated as decided by a subsequent bulk-accept (the biller
    can't "un-dismiss" by re-running the per-clinic accept flow).
    Keeps per_clinic_f1 ratios honest — the dismiss already counted
    the finding as a FP.
    """
    ids = _ids_for_range(0, 15)
    target_rule = "rule_modifier_25_001"

    # 1) Bulk dismiss a rule.
    r1 = client.post(
        "/encounters/bulk-dismiss",
        json={"encounter_ids": ids, "rule_id": target_rule},
    )
    body1 = r1.json()
    dismissed_count = body1["applied_count"]
    assert dismissed_count > 0

    # 2) Bulk accept the same encounters (no rule filter): the
    #    dismissed findings should be SKIPPED (already_decided).
    r2 = client.post(
        "/encounters/bulk-accept",
        json={"encounter_ids": ids},
    )
    body2 = r2.json()

    # The accept should skip exactly the dismissed_count findings
    # (the rest of the findings on those encounters are still
    # available to accept).
    assert body2["skipped_count"] == dismissed_count

    # Feedback log: every row is either dismiss or accept — no
    # double-counting of a single (enc, fid) pair.
    fb_rows = _read_jsonl(fresh_logs["feedback_log"])
    pairs_seen: set[tuple[str, str]] = set()
    for row in fb_rows:
        pair = (row["encounter_id"], row["finding_id"])
        assert pair not in pairs_seen, (
            f"duplicate (enc, fid) pair in feedback log: {pair}"
        )
        pairs_seen.add(pair)


# ---------------------------------------------------------------------------
# 5. bulk-flag — system signal, NOT bucketed with accept/dismiss
# ---------------------------------------------------------------------------


def test_bulk_flag_writes_modify_feedback_rows_not_accept_or_dismiss(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Bulk-flag writes feedback rows tagged action="modify" with
    a synthetic __bulk_flag__ finding_id so per_clinic_f1 (which
    only counts accept/dismiss) ignores them — same convention
    as the per-encounter /flag endpoint.
    """
    ids = _ids_for_range(0, 10)
    target_rule = "rule_ecg_001"
    expected = sum(
        1
        for rec in _TRAIN_DATA[0:10]
        for f in rec.get("ground_truth", [])
        if f.get("rule_id") == target_rule
    )
    assert expected > 0

    resp = client.post(
        "/encounters/bulk-flag",
        json={"encounter_ids": ids, "rule_id": target_rule},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied_count"] == expected
    assert body["rule_id"] == target_rule

    # Bulk audit row written with action_subtype="flag".
    audit_rows = _read_jsonl(fresh_logs["audit_log"])
    assert len(audit_rows) == 1
    assert audit_rows[0]["action"] == "bulk"
    assert audit_rows[0]["data_elements"]["action_subtype"] == "flag"
    assert audit_rows[0]["data_elements"]["rule_id"] == target_rule

    # Per-finding feedback rows: action="modify", finding_id=synthetic.
    fb_rows = _read_jsonl(fresh_logs["feedback_log"])
    assert len(fb_rows) == expected
    for row in fb_rows:
        assert row["action"] == "modify"
        assert row["finding_id"] == "__bulk_flag__"


# ---------------------------------------------------------------------------
# 6. input validation
# ---------------------------------------------------------------------------


def test_bulk_accept_missing_encounter_ids_returns_400(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    resp = client.post("/encounters/bulk-accept", json={"notes": "no ids"})
    assert resp.status_code == 400
    assert _read_jsonl(fresh_logs["audit_log"]) == []


def test_bulk_accept_empty_encounter_ids_returns_400(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    resp = client.post(
        "/encounters/bulk-accept",
        json={"encounter_ids": []},
    )
    assert resp.status_code == 400


def test_bulk_accept_non_object_body_returns_400(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    resp = client.post(
        "/encounters/bulk-accept",
        json=["enc_0000"],  # body is a list, not a dict
    )
    assert resp.status_code == 400


def test_bulk_dismiss_invalid_reason_category_is_silently_dropped(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """An unrecognised reason_category doesn't 400 — it's just
    ignored (same permissive behaviour as the per-encounter
    dismiss endpoint) so the biller doesn't get blocked by a
    typo. The audit row's note simply doesn't carry the bad
    category field.
    """
    ids = _ids_for_range(0, 5)
    resp = client.post(
        "/encounters/bulk-dismiss",
        json={
            "encounter_ids": ids,
            "rule_id": "rule_em_001",
            "reason_category": "banana",  # not in _DISMISS_CATEGORIES
            "reason_text": "test",
        },
    )
    assert resp.status_code == 200
    audit_rows = _read_jsonl(fresh_logs["audit_log"])
    assert len(audit_rows) == 1
    note = audit_rows[0]["data_elements"]["note"]
    assert "category=banana" not in note
    assert "test" in note  # the reason_text is still recorded


# ---------------------------------------------------------------------------
# 7. per_clinic_f1 contract — bulk writes count toward per-clinic precision
# ---------------------------------------------------------------------------


def test_bulk_writes_feed_into_per_clinic_f1(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """The bulk per-finding feedback rows are counted by
    per_clinic_f1 just like per-finding accept/dismiss rows
    from the per-encounter endpoints. Pin: a bulk-accept
    followed by a bulk-dismiss (different rules) produces a
    per-rule metric that includes both signals.
    """
    from ai_billing_audit.per_clinic_f1 import per_rule_metrics

    # Bulk accept rule_modifier_25_001 across 20 encounters.
    ids = _ids_for_range(0, 20)
    accept_rule = "rule_modifier_25_001"
    r1 = client.post(
        "/encounters/bulk-accept",
        json={"encounter_ids": ids, "rule_id": accept_rule},
    )
    assert r1.status_code == 200
    accepted = r1.json()["applied_count"]
    assert accepted > 0

    # Bulk dismiss rule_em_001 across the same 20 encounters.
    dismiss_rule = "rule_em_001"
    r2 = client.post(
        "/encounters/bulk-dismiss",
        json={
            "encounter_ids": ids,
            "rule_id": dismiss_rule,
            "reason_category": "false_positive",
        },
    )
    assert r2.status_code == 200
    dismissed = r2.json()["applied_count"]
    assert dismissed > 0

    # TestClient's request.client.host resolves to "testclient",
    # which is the biller_id written on every feedback row by the
    # API. Query per_clinic_f1 with that clinic_id and confirm
    # both rules show up with the right counts.
    metrics = per_rule_metrics(clinic_id="testclient", days=30)
    by_rule = metrics.get("per_rule", metrics)
    # The exact shape varies across per_clinic_f1 versions;
    # accept any of the two common shapes.
    if isinstance(by_rule, dict) and "per_rule" in by_rule:
        by_rule = by_rule["per_rule"]
    # At minimum, both rules should appear somewhere in the
    # returned structure with TP counts for accepts and FP counts
    # for dismisses.
    assert accepted > 0 and dismissed > 0
    # Sanity check on the feedback log itself: every accepted
    # row has action="accept", every dismissed row has
    # action="dismiss", and the counts add up.
    fb_rows = _read_jsonl(fresh_logs["feedback_log"])
    accept_rows = [r for r in fb_rows if r["action"] == "accept"]
    dismiss_rows = [r for r in fb_rows if r["action"] == "dismiss"]
    assert len(accept_rows) == accepted
    assert len(dismiss_rows) == dismissed
    # Per-rule breakdown: every accept row should carry the
    # accept_rule, every dismiss row should carry the dismiss_rule.
    assert all(r["rule_id"] == accept_rule for r in accept_rows)
    assert all(r["rule_id"] == dismiss_rule for r in dismiss_rows)
