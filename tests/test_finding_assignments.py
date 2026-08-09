"""Tests for the finding-assignment feature (kanban t_54262d96).

What's pinned
-------------
1. **FindingAssignmentStore unit tests** (no FastAPI):
   - Append + read back a row.
   - ``current_assignee_for`` returns the most recent row, even
     after a re-assignment.
   - ``current_assignees_for_encounter`` collapses to one row
     per ``finding_id``.
   - ``workload_for_clinic`` groups by current assignee and
     produces ``n_assigned / n_completed / n_overdue`` correctly.
   - Per-biller-per-clinic scoping: workload for clinic A does
     NOT include billers from clinic B.

2. **HTTP endpoint tests** (FastAPI TestClient):
   - POST assign writes a row + an audit_actions row.
   - POST assign with missing ``assignee_id`` returns 400.
   - POST assign with malformed ``due_date`` returns 400.
   - POST re-assign with same assignee_id is idempotent (no
     new row written, response confirms the existing row).
   - POST re-assign with a NEW assignee_id writes a new row;
     ``current_assignee_for`` returns the new biller.
   - GET /api/clinics/{clinic_id}/workload returns per-biller
     rows after assignments have been written.
   - GET /api/clinics/{clinic_id}/workload returns 404 for an
     unknown clinic_id.
   - GET /api/encounters/{id}/finding/assignments returns the
     current map of finding_id → FindingAssignment.
   - Encounter detail page renders the "Assigned to" badge
     when an assignment exists.

No LLM, no network. Test logs redirected to tmp JSONL files so
the real /app/logs/* never gets touched.
"""

from __future__ import annotations

import importlib
import json
import sys
import time as time_mod
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from ai_billing_audit.clinical_note_storage import read_encrypted_json_records

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit import api as api_mod  # noqa: E402
from ai_billing_audit import audit_actions as aa_mod  # noqa: E402
from ai_billing_audit import (  # noqa: E402
    finding_assignments as fa_mod,
)
from ai_billing_audit import feedback as fb_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Redirect the audit + assignments logs to tmp files."""
    audit_log = tmp_path / "audit_trail.jsonl"
    assignment_log = tmp_path / "finding_assignments.jsonl"
    feedback_log = tmp_path / "feedback.jsonl"
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(audit_log))
    monkeypatch.setenv("FINDING_ASSIGNMENT_LOG", str(assignment_log))
    monkeypatch.setenv("FEEDBACK_LOG", str(feedback_log))
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    # Reload the modules so the env-driven log paths take effect.
    importlib.reload(aa_mod)
    importlib.reload(fb_mod)
    importlib.reload(fa_mod)
    importlib.reload(api_mod)
    yield {
        "audit_log": audit_log,
        "assignment_log": assignment_log,
        "feedback_log": feedback_log,
    }


@pytest.fixture()
def client(fresh_logs) -> TestClient:
    return TestClient(api_mod.create_app())


def _read_jsonl(path: Path) -> list[dict]:
    return read_encrypted_json_records(path)


def _iso(ts: float) -> str:
    return time_mod.strftime("%Y-%m-%dT%H:%M:%SZ", time_mod.gmtime(ts))


def _iso_dt(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# Pick a real encounter from the seeded train.json so the demo
# path in encounter_detail can resolve it.
_TRAIN_JSON = PROJECT_ROOT / "data" / "synth" / "train.json"
with _TRAIN_JSON.open() as fh:
    _TRAIN_DATA = json.load(fh)
_REAL_ENC = _TRAIN_DATA[0]["encounter_id"]
_REAL_FINDING = _TRAIN_DATA[0].get("ground_truth", [{}])[0].get("finding_id", "ft_1")


# ---------------------------------------------------------------------------
# 1. FindingAssignmentStore unit tests
# ---------------------------------------------------------------------------


def test_assignment_store_append_and_read(fresh_logs: dict[str, Path]) -> None:
    """An assigned row round-trips through the store."""
    store = fa_mod.FindingAssignmentStore()
    entry = store.assign(
        encounter_id="enc_1",
        finding_id="f_1",
        assignee_id="biller_a",
        assigned_by="manager",
    )
    assert entry.event_id
    assert entry.encounter_id == "enc_1"
    assert entry.finding_id == "f_1"
    assert entry.assignee_id == "biller_a"
    assert entry.assigned_by == "manager"
    assert b"enc_1" not in fresh_logs["assignment_log"].read_bytes()
    rows = store.entries_for("enc_1")
    assert len(rows) == 1
    assert rows[0].assignee_id == "biller_a"


def test_current_assignee_after_reassign(fresh_logs: dict[str, Path]) -> None:
    """Re-assignment: current assignee reflects the most recent row."""
    store = fa_mod.FindingAssignmentStore()
    store.assign("enc_1", "f_1", "biller_a")
    store.assign("enc_1", "f_1", "biller_b")
    cur = store.current_assignee_for("enc_1", "f_1")
    assert cur is not None
    assert cur.assignee_id == "biller_b"
    # History preserved
    rows = store.entries_for("enc_1", "f_1")
    assert [r.assignee_id for r in rows] == ["biller_a", "biller_b"]


def test_current_assignees_for_encounter_collapse(fresh_logs: dict[str, Path]) -> None:
    """Multiple findings on one encounter each have one current row."""
    store = fa_mod.FindingAssignmentStore()
    store.assign("enc_1", "f_1", "biller_a")
    store.assign("enc_1", "f_2", "biller_b")
    # Re-assign f_1 → newest row wins
    store.assign("enc_1", "f_1", "biller_c")
    cur = store.current_assignees_for_encounter("enc_1")
    assert set(cur.keys()) == {"f_1", "f_2"}
    assert cur["f_1"].assignee_id == "biller_c"
    assert cur["f_2"].assignee_id == "biller_b"


def test_workload_groups_by_current_assignee(fresh_logs: dict[str, Path]) -> None:
    """Workload rows are per-biller; only the CURRENT assignee counts."""
    store = fa_mod.FindingAssignmentStore()
    # biller_a was assigned f_1 then REASSIGNED to biller_b →
    # biller_a should not have f_1 in their current workload.
    store.assign("enc_1", "f_1", "biller_a")
    store.assign("enc_1", "f_1", "biller_b")
    store.assign("enc_1", "f_2", "biller_a")
    workload = store.workload_for_clinic("biller_a")
    assert len(workload) == 1
    assert workload[0]["biller_id"] == "biller_a"
    assert workload[0]["n_assigned"] == 1
    workload_b = store.workload_for_clinic("biller_b")
    assert len(workload_b) == 1
    assert workload_b[0]["biller_id"] == "biller_b"
    assert workload_b[0]["n_assigned"] == 1


def test_workload_per_biller_per_clinic_scoping(
    fresh_logs: dict[str, Path],
) -> None:
    """Workload for clinic A does NOT include billers from clinic B.

    The biller → clinic mapping defaults to ``biller_id == clinic_id``
    so we exercise that default by setting biller_ids that match
    distinct clinic_ids.
    """
    store = fa_mod.FindingAssignmentStore()
    store.assign("enc_1", "f_1", "clinic_a_biller")
    store.assign("enc_2", "f_1", "clinic_b_biller")
    a = store.workload_for_clinic("clinic_a_biller")
    b = store.workload_for_clinic("clinic_b_biller")
    assert {row["biller_id"] for row in a} == {"clinic_a_biller"}
    assert {row["biller_id"] for row in b} == {"clinic_b_biller"}
    # Cross-check with an explicit biller_to_clinic mapping
    mapped = store.workload_for_clinic(
        "shared_clinic",
        biller_to_clinic=lambda bid: "shared_clinic",
    )
    assert {row["biller_id"] for row in mapped} == {
        "clinic_a_biller",
        "clinic_b_biller",
    }


def test_workload_completed_and_overdue_counts(
    fresh_logs: dict[str, Path],
) -> None:
    """n_completed / n_overdue reflect feedback + due_date state."""
    from ai_billing_audit.feedback import FeedbackEntry, FeedbackStore

    fb_store = FeedbackStore(log_path=fresh_logs["feedback_log"])
    store = fa_mod.FindingAssignmentStore()
    # Three findings assigned to biller_a
    now = time_mod.time()
    store.assign("enc_1", "f_1", "biller_a", due_date=_iso(now - 60))  # overdue
    store.assign("enc_1", "f_2", "biller_a", due_date=_iso(now + 3600))  # future
    store.assign("enc_1", "f_3", "biller_a", due_date="")  # no due date
    # biller_a has accepted f_2 → counts as completed, no longer overdue
    fb_store.append(
        FeedbackEntry(
            encounter_id="enc_1",
            finding_id="f_2",
            action="accept",
            severity="medium",
            rule_id="rule_x",
            category="dx_linkage",
            timestamp=_iso(now),
            biller_id="biller_a",
        )
    )
    rows = store.workload_for_clinic("biller_a")
    assert len(rows) == 1
    row = rows[0]
    assert row["biller_id"] == "biller_a"
    assert row["n_assigned"] == 3
    assert row["n_completed"] == 1
    # f_1 is overdue AND not completed → n_overdue=1
    assert row["n_overdue"] == 1


# ---------------------------------------------------------------------------
# 2. HTTP endpoint tests
# ---------------------------------------------------------------------------


def test_assign_endpoint_writes_log_and_audit(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """POST /api/encounters/{id}/finding/{fid}/assign writes
    both an assignment row AND an audit_actions row.
    """
    resp = client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": "biller_alice"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["assignment"]["assignee_id"] == "biller_alice"
    # Assignment log got the row.
    rows = _read_jsonl(fresh_logs["assignment_log"])
    assert len(rows) == 1
    assert rows[0]["assignee_id"] == "biller_alice"
    # Audit chain got the row.
    audit_rows = _read_jsonl(fresh_logs["audit_log"])
    assert len(audit_rows) == 1
    assert audit_rows[0]["action"] == "assign"
    assert audit_rows[0]["data_elements"]["assignee_id"] == "biller_alice"


def test_assign_with_due_date_persists(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """due_date is accepted and round-tripped through the store."""
    due = _iso(time_mod.time() + 86400)
    resp = client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": "biller_bob", "due_date": due},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["assignment"]["due_date"] == due


def test_assign_missing_assignee_returns_400(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Empty assignee_id → 400, no log write."""
    resp = client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": ""},
    )
    assert resp.status_code == 400
    assert "assignee_id" in resp.json()["detail"]
    assert _read_jsonl(fresh_logs["assignment_log"]) == []


def test_assign_malformed_due_date_returns_400(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Bad due_date → 400, no log write."""
    resp = client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": "biller_x", "due_date": "not-a-date"},
    )
    assert resp.status_code == 400
    assert "iso-8601" in resp.json()["detail"].lower()
    assert _read_jsonl(fresh_logs["assignment_log"]) == []


def test_assign_idempotent_on_reassign_same_biller(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Re-assigning the same biller writes NO new row."""
    # First assignment
    r1 = client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": "biller_same"},
    )
    assert r1.status_code == 200
    assert r1.json()["reassigned"] is False
    # Second assignment with the same biller → idempotent
    r2 = client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": "biller_same"},
    )
    assert r2.status_code == 200
    assert r2.json()["reassigned"] is False
    # Still only ONE row in the assignments log
    rows = _read_jsonl(fresh_logs["assignment_log"])
    assert len(rows) == 1
    assert rows[0]["assignee_id"] == "biller_same"


def test_assign_reassign_to_new_biller_writes_new_row(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Re-assigning to a different biller writes a new row;
    current_assignee_for returns the new biller."""
    client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": "biller_first"},
    )
    r2 = client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": "biller_second"},
    )
    assert r2.status_code == 200
    assert r2.json()["reassigned"] is True
    # Two rows in the log (history preserved)
    rows = _read_jsonl(fresh_logs["assignment_log"])
    assert len(rows) == 2
    assert [r["assignee_id"] for r in rows] == [
        "biller_first",
        "biller_second",
    ]
    # Current assignee is the second one
    cur = client.get(f"/api/encounters/{_REAL_ENC}/finding/assignments")
    assert cur.status_code == 200
    assert cur.json()["assignments"][_REAL_FINDING]["assignee_id"] == ("biller_second")


def test_workload_endpoint_returns_per_biller_rows(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Workload endpoint groups by current assignee after a few assigns.

    We register ``biller_one`` and ``biller_two`` via feedback entries
    so they appear in ``list_clinics()`` (the workload endpoint's
    404 check), then re-assign across them and check the
    per-biller-per-clinic rollup.
    """
    from ai_billing_audit.feedback import FeedbackEntry, FeedbackStore

    fb_store = FeedbackStore(log_path=fresh_logs["feedback_log"])
    # One feedback entry per biller — that's how list_clinics()
    # learns about a biller in the first place.
    now = time_mod.time()
    for bid in ("biller_one", "biller_two"):
        fb_store.append(
            FeedbackEntry(
                encounter_id="warmup",
                finding_id="warmup",
                action="accept",
                severity="low",
                rule_id="warmup",
                category="warmup",
                timestamp=_iso(now),
                biller_id=bid,
            )
        )
    # Two billers, three findings, one re-assigned
    client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": "biller_one"},
    )
    # Use a different finding for biller_two
    other_finding = (
        _TRAIN_DATA[0].get("ground_truth", [{}, {}])[1].get("finding_id", "ft_2")
    )
    client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{other_finding}/assign",
        json={"assignee_id": "biller_two"},
    )
    # Reassign _REAL_FINDING to biller_two → biller_one drops to zero
    client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": "biller_two"},
    )
    # Workload for clinic_id == biller_one (no current assignments → empty)
    r_empty = client.get("/api/clinics/biller_one/workload")
    assert r_empty.status_code == 200, r_empty.text
    assert r_empty.json()["workload"] == []
    # Workload for clinic_id == biller_two → 2 assigned
    r = client.get("/api/clinics/biller_two/workload")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["clinic_id"] == "biller_two"
    assert body["n_billers"] == 1
    assert body["workload"][0]["biller_id"] == "biller_two"
    assert body["workload"][0]["n_assigned"] == 2


def test_workload_endpoint_unknown_clinic_returns_404(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """Unknown clinic_id returns 404 (matches the dashboard's 404 contract)."""
    r = client.get("/api/clinics/does-not-exist-xyz-clinic/workload")
    assert r.status_code == 404
    assert "does-not-exist-xyz-clinic" in r.json()["detail"]


def test_encounter_assignments_endpoint_returns_current_map(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """GET /api/encounters/{id}/finding/assignments returns
    {finding_id: FindingAssignment} of CURRENT assignees only.
    """
    client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": "biller_x"},
    )
    r = client.get(f"/api/encounters/{_REAL_ENC}/finding/assignments")
    assert r.status_code == 200
    body = r.json()
    assert body["encounter_id"] == _REAL_ENC
    assert body["count"] == 1
    assert body["assignments"][_REAL_FINDING]["assignee_id"] == "biller_x"


def test_encounter_detail_renders_assigned_to_badge(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """The encounter detail page renders the 'Assigned to' badge
    when an assignment exists for a finding on this encounter.
    """
    client.post(
        f"/api/encounters/{_REAL_ENC}/finding/{_REAL_FINDING}/assign",
        json={"assignee_id": "biller_visible"},
    )
    r = client.get(f"/encounter/{_REAL_ENC}")
    assert r.status_code == 200, r.text
    assert "Assigned to biller_visible" in r.text
    assert 'class="badge badge-assigned"' in r.text


def test_encounter_detail_no_badge_when_unassigned(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """The encounter detail page does NOT render the assignment
    badge when no assignment exists for the findings on it.
    """
    r = client.get(f"/encounter/{_REAL_ENC}")
    assert r.status_code == 200, r.text
    assert "Assigned to" not in r.text
