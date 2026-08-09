"""Tests for the /api/reports/monthly route (t_b15a1821).

The route wraps the ``monthly_report`` module behind an
insufficient_data gate (the real full report is owned by blocked
task t_f98a799f, which needs 3+ months of feedback). These tests
pin the three behaviours the task acceptance criteria call out:

1. **insufficient_data** — fewer than 3 months of feedback for
   the clinic → the stub JSON shape is returned.
2. **bad month format** — non-``YYYY-MM`` month → 400.
3. **3+ months path** — when 3+ distinct months of feedback
   exist, the route forwards to ``monthly_report.monthly_summary``
   and returns a non-empty payload.

Lightweight, no network, no LLM. The route is exercised via
``starlette.testclient.TestClient`` (httpx-backed) so the
``JSONResponse`` / ``HTTPException`` shapes are real.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.api import create_app  # noqa: E402
from ai_billing_audit.feedback import FeedbackEntry, FeedbackStore  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Test client with auth disabled.

    The API's bearer middleware captures ``AUDIT_ALLOW_NO_AUTH`` at
    ``create_app()`` time, so we must build the app *inside* the
    fixture — patching the env after the module-level ``api.app``
    was constructed (which happens at import time) is too late.
    """
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    return TestClient(create_app())


def _iso(ts: float) -> str:
    """Format a POSIX timestamp as the feedback log's expected ISO-8601 UTC."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_store_with_months(
    tmp_path: Path,
    *,
    biller_id: str,
    months_back: list[int],
) -> FeedbackStore:
    """Create a fresh FeedbackStore seeded with one accept event per
    ``months_back`` value. Each value is the number of months back
    from "now" (rounded to mid-month) to drop a feedback event.
    Used to simulate a clinic with N distinct months of activity.
    """
    store = FeedbackStore(log_path=tmp_path / "feedback.jsonl")
    now = datetime.now(tz=timezone.utc)
    for m_ago in months_back:
        # Land on the 15th of the month, ``m_ago`` months back.
        target = now.replace(day=15, hour=12, minute=0, second=0, microsecond=0)
        # Walk back ``m_ago`` months (clamp day if short month).
        for _ in range(m_ago):
            prev_month = target.month - 1
            prev_year = target.year
            if prev_month == 0:
                prev_month = 12
                prev_year -= 1
            target = target.replace(year=prev_year, month=prev_month)
        ts = target.timestamp()
        store.append(
            FeedbackEntry(
                encounter_id=f"enc-m{m_ago}",
                finding_id=f"f-m{m_ago}",
                action="accept",
                severity="medium",
                rule_id="R-MOD-25",
                category="modifier_required",
                timestamp=_iso(ts),
                biller_id=biller_id,
            )
        )
    return store


# ---------------------------------------------------------------------------
# 1. insufficient_data path
# ---------------------------------------------------------------------------


def test_insufficient_data_returns_stub_shape(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clinic with zero feedback months gets the insufficient_data stub.

    Verifies the exact response shape the task spec calls out:
    status, message, required_months=3, current_months=<int>,
    clinic_id, month. Uses an empty feedback store so the count
    is exactly 0.
    """
    # Inject an empty store so the route's ``get_default_store()``
    # returns our (empty) test store instead of the production
    # /app/logs/feedback.jsonl path.
    empty = FeedbackStore(log_path=tmp_path / "empty.jsonl")
    monkeypatch.setattr("ai_billing_audit.feedback._default", empty, raising=False)
    # The route's local import is ``from .feedback import get_default_store``;
    # the module-level singleton is shared, so the same patch works.

    r = client.get(
        "/api/reports/monthly",
        params={"clinic": "biller-EMPTY", "month": "2026-06"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "insufficient_data"
    assert body["message"] == (
        "Need 3+ months of feedback to generate a monthly report."
    )
    assert body["required_months"] == 3
    assert body["current_months"] == 0
    assert body["clinic_id"] == "biller-EMPTY"
    assert body["month"] == "2026-06"


def test_insufficient_data_with_some_feedback(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clinic with 2 months of feedback still hits the stub, and
    ``current_months`` reflects the actual count (not always 0)."""
    store = _build_store_with_months(
        tmp_path,
        biller_id="biller-PARTIAL",
        months_back=[1, 2],
    )
    monkeypatch.setattr(
        "ai_billing_audit.feedback._default",
        store,
        raising=False,
    )

    r = client.get(
        "/api/reports/monthly",
        params={"clinic": "biller-PARTIAL", "month": "2026-06"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "insufficient_data"
    assert body["required_months"] == 3
    # Exactly 2 distinct calendar months (this month and 1 month back)
    assert body["current_months"] == 2
    assert body["clinic_id"] == "biller-PARTIAL"


def test_insufficient_data_other_clinic_feedback_does_not_count(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Feedback for OTHER clinics must not bump the queried clinic's
    ``current_months`` count. The route scopes the count to
    ``biller_id`` (the same proxy the per_clinic_f1 dashboard uses).
    """
    store = _build_store_with_months(
        tmp_path,
        biller_id="biller-OTHER",
        months_back=[1, 2, 3, 4],
    )
    monkeypatch.setattr(
        "ai_billing_audit.feedback._default",
        store,
        raising=False,
    )

    r = client.get(
        "/api/reports/monthly",
        params={"clinic": "biller-QUERY", "month": "2026-06"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "insufficient_data"
    # The queried clinic has no feedback in the store → 0.
    assert body["current_months"] == 0


# ---------------------------------------------------------------------------
# 2. Bad month format
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_month",
    [
        "2025/01",  # wrong separator
        "25-01",  # 2-digit year
        "2025-1",  # 1-digit month
        "Jan 2025",  # free-form
        "",  # empty
        "2025-01-15",  # full date, not month
    ],
)
def test_bad_month_returns_400(
    client: TestClient,
    bad_month: str,
) -> None:
    """A month query param that doesn't match ``YYYY-MM`` → 400.

    The route's gate is a regex (``\d{4}-\d{2}``), so values
    that happen to pass the regex (e.g. ``2025-13``, an
    out-of-range month) are accepted and the route treats them
    as the ``month`` echo. Semantic month validation can be
    layered on later without breaking the route contract.
    """
    r = client.get(
        "/api/reports/monthly",
        params={"clinic": "biller-A", "month": bad_month},
    )
    assert r.status_code == 400, (
        f"expected 400 for month={bad_month!r}, got {r.status_code}: {r.text}"
    )
    detail = r.json().get("detail", "")
    assert "YYYY-MM" in detail, f"expected YYYY-MM hint in detail, got: {detail!r}"


def test_missing_month_returns_400(client: TestClient) -> None:
    """No month query param at all → 400 (the route needs it to
    render the report's header even in the insufficient_data stub)."""
    r = client.get(
        "/api/reports/monthly",
        params={"clinic": "biller-A"},
    )
    assert r.status_code == 400
    assert "month" in r.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# 3. 3+ months path
# ---------------------------------------------------------------------------


def test_three_plus_months_returns_full_report(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clinic with 4 distinct months of feedback gets the full
    report payload (not the insufficient_data stub). The payload
    is the dict returned by ``monthly_report.monthly_summary``,
    merged with the route's query metadata.

    This is the "3+ months" code path the task spec calls out as
    the deferred-report branch owned by t_f98a799f. The route
    must reach it; the actual report content lives elsewhere.
    """
    store = _build_store_with_months(
        tmp_path,
        biller_id="biller-FULL",
        months_back=[1, 2, 3, 4],
    )
    monkeypatch.setattr(
        "ai_billing_audit.feedback._default",
        store,
        raising=False,
    )

    r = client.get(
        "/api/reports/monthly",
        params={"clinic": "biller-FULL", "month": "2026-06"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # The full-report branch is taken (NOT the stub).
    assert body["status"] == "ok"
    # Query metadata is echoed back.
    assert body["month"] == "2026-06"
    assert body["clinic_id"] == "biller-FULL"
    # monthly_summary returns these keys; the route must pass them
    # through unchanged so the deferred full report can render
    # against the same response shape.
    assert "per_rule" in body
    assert "weekly" in body
    assert "insufficient_data" in body
    # The summary now has 4+ events, so the per_rule table is
    # non-empty (the "non-empty dict" the task spec calls out).
    assert body["per_rule"], f"expected non-empty per_rule, got {body['per_rule']}"
    # And the insufficient_data flag inside the summary should
    # be False (4 events >= threshold 3).
    assert body["insufficient_data"] is False
