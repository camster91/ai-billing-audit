"""Tests for the appeal-outcome tracking layer.

Covers the dataclass + log/read + win-rate helpers in
``appeal_letter.py`` and the
``POST /encounter/{id}/appeal/{appeal_id}/outcome`` route in
``api.py``.

What's pinned
-------------
* ``log_appeal_outcome`` round-trips through
  ``read_appeal_outcomes`` (every field survives)
* ``read_appeal_outcomes`` filters by ``encounter_id``
* ``read_appeal_outcomes`` skips malformed log rows
* ``appeal_win_rate`` returns None when no decided outcomes;
  counts only the latest outcome per appeal_id (later edits
  supersede earlier ones); computes won / (won + lost)
* The endpoint accepts a valid id + valid status, logs the
  outcome, and returns 200
* The endpoint returns 404 when ``appeal_id`` is empty
* The endpoint returns 400 when ``status`` is not in
  {won, lost, withdrawn, pending}
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_billing_audit import appeal_letter
from ai_billing_audit.clinical_note_storage import PhiStorageIntegrityError
from ai_billing_audit.appeal_letter import (
    AppealOutcome,
    appeal_win_rate,
    log_appeal_outcome,
    read_appeal_outcomes,
)


# ----- fixtures ---------------------------------------------------------


@pytest.fixture
def temp_logs_dir(tmp_path, monkeypatch):
    """Point the appeal_letter module at a temp logs directory.

    Both the letter log and the outcomes log live under tmp_path
    so the test never touches the real /app/logs/ directory.
    """
    monkeypatch.setattr(appeal_letter, "_LOGS_DIR", tmp_path)
    monkeypatch.setattr(appeal_letter, "_APPEAL_LOG", tmp_path / "appeal_letters.jsonl")
    monkeypatch.setattr(
        appeal_letter, "_APPEAL_OUTCOMES_LOG", tmp_path / "appeal_outcomes.jsonl"
    )
    return tmp_path


@pytest.fixture
def client(monkeypatch):
    """A FastAPI test client. The real app is not started.

    Auth is disabled for tests via ``AUDIT_ALLOW_NO_AUTH=1`` so
    the test client doesn't have to send a bearer token.
    """
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    # Re-import so the env var is read fresh at create_app() time
    from ai_billing_audit.api import create_app

    app = create_app()
    return TestClient(app)


# ----- dataclass + log/read round-trip ----------------------------------


def test_appeal_outcome_dataclass_fields():
    """The dataclass exposes every field the spec calls for."""
    o = AppealOutcome(
        appeal_id="A-1",
        encounter_id="E-1",
        status="won",
        timestamp="2026-06-24T00:00:00+00:00",
        biller_id="biller-7",
        notes="Payer reversed on review",
    )
    assert o.appeal_id == "A-1"
    assert o.encounter_id == "E-1"
    assert o.status == "won"
    assert o.biller_id == "biller-7"
    assert "reversed" in o.notes


def test_appeal_outcome_now_factory_sets_timestamp():
    """The .now() factory stamps the current UTC time."""
    o = AppealOutcome.now(
        appeal_id="A-1",
        encounter_id="E-1",
        status="pending",
    )
    assert o.timestamp  # non-empty
    # ISO 8601 with timezone — 'T' separator, '+' or 'Z' tz marker
    assert "T" in o.timestamp
    assert "+" in o.timestamp or o.timestamp.endswith("Z")


def test_log_and_read_round_trip(temp_logs_dir):
    """log_appeal_outcome + read_appeal_outcomes preserves every field."""
    log_appeal_outcome(
        AppealOutcome.now(
            appeal_id="A-1",
            encounter_id="E-1",
            status="won",
            biller_id="biller-1",
            notes="denial reversed on first review",
        )
    )
    log_appeal_outcome(
        AppealOutcome.now(
            appeal_id="A-2",
            encounter_id="E-1",
            status="lost",
            notes="payer upheld denial",
        )
    )
    log_appeal_outcome(
        AppealOutcome.now(
            appeal_id="A-3",
            encounter_id="E-2",
            status="withdrawn",
            notes="clinic pulled the appeal",
        )
    )

    rows = read_appeal_outcomes()
    assert len(rows) == 3
    by_id = {r.appeal_id: r for r in rows}
    assert by_id["A-1"].status == "won"
    assert by_id["A-1"].biller_id == "biller-1"
    assert "reversed" in by_id["A-1"].notes
    assert by_id["A-2"].status == "lost"
    assert by_id["A-3"].encounter_id == "E-2"


def test_read_filters_by_encounter_id(temp_logs_dir):
    """read_appeal_outcomes(encounter_id=...) drops other rows."""
    log_appeal_outcome(
        AppealOutcome.now(appeal_id="A-1", encounter_id="E-1", status="won")
    )
    log_appeal_outcome(
        AppealOutcome.now(appeal_id="A-2", encounter_id="E-2", status="lost")
    )

    e1 = read_appeal_outcomes(encounter_id="E-1")
    assert [r.appeal_id for r in e1] == ["A-1"]
    e2 = read_appeal_outcomes(encounter_id="E-2")
    assert [r.appeal_id for r in e2] == ["A-2"]
    assert read_appeal_outcomes(encounter_id="E-MISSING") == []


def test_read_returns_empty_when_log_missing(tmp_path, monkeypatch):
    """No log file on disk → empty list, no exception."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr(appeal_letter, "_LOGS_DIR", empty_dir)
    monkeypatch.setattr(
        appeal_letter, "_APPEAL_OUTCOMES_LOG", empty_dir / "appeal_outcomes.jsonl"
    )
    assert read_appeal_outcomes() == []


def test_read_refuses_plaintext_or_corrupt_rows(temp_logs_dir):
    log_path: Path = temp_logs_dir / "appeal_outcomes.jsonl"
    log_path.write_text(
        "\n".join(
            [
                "not json at all",
                json.dumps({"unrelated": "object"}),
                json.dumps(
                    {
                        "appeal_id": "A-OK",
                        "encounter_id": "E-1",
                        "status": "won",
                        "timestamp": "2026-06-24T00:00:00+00:00",
                    }
                ),
                "",
            ]
        )
        + "\n"
    )
    with pytest.raises(PhiStorageIntegrityError):
        read_appeal_outcomes()


def test_log_failure_does_not_raise(temp_logs_dir, monkeypatch):
    """A log write failure (e.g. read-only fs) does not propagate."""
    # Point the log path at a non-writable target
    monkeypatch.setattr(
        appeal_letter,
        "_APPEAL_OUTCOMES_LOG",
        temp_logs_dir / "not-a-dir" / "nope" / "outcomes.jsonl",
    )
    # Should not raise
    log_appeal_outcome(
        AppealOutcome.now(appeal_id="A-1", encounter_id="E-1", status="won")
    )


# ----- appeal_win_rate --------------------------------------------------


def test_win_rate_empty_log(temp_logs_dir):
    """No outcomes → decided=0, win_rate=None."""
    stats = appeal_win_rate()
    assert stats["total_won"] == 0
    assert stats["total_lost"] == 0
    assert stats["decided"] == 0
    assert stats["win_rate"] is None


def test_win_rate_counts_only_decided(temp_logs_dir):
    """win_rate = won / (won + lost); pending/withdrawn don't count."""
    for i, s in enumerate(["won", "lost", "won", "withdrawn", "pending", "lost"]):
        log_appeal_outcome(
            AppealOutcome.now(
                appeal_id=f"A-{i}",
                encounter_id="E-1",
                status=s,
            )
        )
    stats = appeal_win_rate()
    assert stats["total_won"] == 2
    assert stats["total_lost"] == 2
    assert stats["total_withdrawn"] == 1
    assert stats["total_pending"] == 1
    assert stats["decided"] == 4
    assert stats["win_rate"] == 0.5


def test_win_rate_all_won(temp_logs_dir):
    for i in range(3):
        log_appeal_outcome(
            AppealOutcome.now(appeal_id=f"A-{i}", encounter_id="E-1", status="won")
        )
    stats = appeal_win_rate()
    assert stats["win_rate"] == 1.0


def test_win_rate_all_lost(temp_logs_dir):
    for i in range(2):
        log_appeal_outcome(
            AppealOutcome.now(appeal_id=f"A-{i}", encounter_id="E-1", status="lost")
        )
    stats = appeal_win_rate()
    assert stats["win_rate"] == 0.0


def test_win_rate_uses_latest_outcome_per_appeal(temp_logs_dir):
    """A later outcome for the same appeal_id supersedes the earlier one.

    The biller can update an outcome (e.g. pending -> won). The
    win rate should reflect the current state, not the history.
    """
    log_appeal_outcome(
        AppealOutcome(
            appeal_id="A-1",
            encounter_id="E-1",
            status="pending",
            timestamp="2026-06-24T00:00:00+00:00",
        )
    )
    log_appeal_outcome(
        AppealOutcome(
            appeal_id="A-1",
            encounter_id="E-1",
            status="won",
            timestamp="2026-06-25T00:00:00+00:00",
        )
    )
    log_appeal_outcome(
        AppealOutcome(
            appeal_id="A-2",
            encounter_id="E-1",
            status="lost",
            timestamp="2026-06-24T00:00:00+00:00",
        )
    )
    stats = appeal_win_rate()
    assert stats["total_won"] == 1
    assert stats["total_lost"] == 1
    assert stats["total_pending"] == 0  # A-1's pending was superseded
    assert stats["win_rate"] == 0.5


# ----- endpoint ---------------------------------------------------------


def test_endpoint_returns_404_for_bad_appeal_id(client, temp_logs_dir):
    """Empty appeal_id in the path → 404."""
    # FastAPI treats an empty path segment as a route mismatch,
    # which surfaces as a 404 from the test client. Belt-and-
    # braces: a literal "%20" (single space) goes through route
    # matching but our handler treats whitespace as missing.
    response = client.post(
        "/encounter/E-1/appeal/%20/outcome",
        json={"status": "won", "notes": "irrelevant"},
    )
    # Either 404 (our handler) or 404 (route mismatch) is acceptable.
    assert response.status_code == 404


def test_endpoint_returns_400_for_bad_status(client, temp_logs_dir):
    """Unknown status value → 400 with a clear error."""
    response = client.post(
        "/encounter/E-1/appeal/A-1/outcome",
        json={"status": "victorious", "notes": "wrong enum"},
    )
    assert response.status_code == 400
    body = response.json()
    assert "status" in body["detail"].lower()


def test_endpoint_returns_200_and_logs_outcome(client, temp_logs_dir):
    """Valid request → 200, outcome appears in the log, read returns it."""
    response = client.post(
        "/encounter/E-1/appeal/A-100/outcome",
        json={
            "status": "won",
            "notes": "payer reversed on first review",
            "biller_id": "biller-42",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["encounter_id"] == "E-1"
    assert body["appeal_id"] == "A-100"
    assert body["outcome"]["status"] == "won"
    assert body["outcome"]["biller_id"] == "biller-42"
    assert "reversed" in body["outcome"]["notes"]
    assert body["outcome"]["timestamp"]

    # Confirm the outcome was actually persisted
    rows = read_appeal_outcomes(encounter_id="E-1")
    assert len(rows) == 1
    assert rows[0].appeal_id == "A-100"
    assert rows[0].status == "won"


def test_endpoint_accepts_withdrawn_and_pending(client, temp_logs_dir):
    """The other allowed statuses are accepted too."""
    for status in ("lost", "withdrawn", "pending"):
        response = client.post(
            f"/encounter/E-1/appeal/A-{status}/outcome",
            json={"status": status, "notes": f"case {status}"},
        )
        assert response.status_code == 200, (status, response.text)
        assert response.json()["outcome"]["status"] == status

    rows = read_appeal_outcomes()
    statuses = {r.status for r in rows}
    assert statuses == {"lost", "withdrawn", "pending"}


def test_endpoint_accepts_missing_optional_fields(client, temp_logs_dir):
    """notes / biller_id are optional — defaults are safe."""
    response = client.post(
        "/encounter/E-1/appeal/A-MIN/outcome",
        json={"status": "won"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"]["notes"] == ""
    assert body["outcome"]["biller_id"] is None


def test_endpoint_404_for_truly_missing_appeal_segment(client):
    """The 404 path is also returned when the route segment is absent."""
    # /encounter/E-1/appeal//outcome has an empty segment between
    # the two slashes; the handler treats this as 'appeal_id missing'.
    response = client.post(
        "/encounter/E-1/appeal//outcome",
        json={"status": "won"},
    )
    # FastAPI may either 404 the route or hit our handler — both
    # surface as 404 to the caller, which is what we promised.
    assert response.status_code == 404
