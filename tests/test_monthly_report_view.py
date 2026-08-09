"""Tests for the HTML view of the per-clinic-month feedback report.

The view lives at ``GET /reports/clinic-monthly`` and is the human-
facing sibling of ``GET /api/reports/monthly``. The JSON sibling owns
the insufficient_data gate and the machine-readable shape; this view
delegates to ``monthly_report.compute_clinic_month`` and renders
either:

  * the insufficient_data card (months-of-feedback the clinic
    currently has, no fabricated numbers), or
  * the full report (action counts, top-3 modified rules,
    confidence calibration, tuning recommendations).

These tests pin the rendered HTML structure so the acceptance
criteria of kanban t_6cc0199c stay pinned: a view function exists,
the template handles both states, and a manual request for a
known clinic-month returns the expected structure.
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

    Bearer middleware captures ``AUDIT_ALLOW_NO_AUTH`` at
    ``create_app()`` time so we build the app *inside* the fixture —
    patching the env after the module-level ``api.app`` was
    constructed (which happens at import time) is too late.
    """
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    return TestClient(create_app())


def _iso(ts: float) -> str:
    """Format a POSIX timestamp as the feedback log's ISO-8601 UTC."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_store_with_clinic_months(
    tmp_path: Path,
    *,
    biller_id: str,
    months_back: list[int],
    rule_id: str = "R-MOD-25",
    action: str = "accept",
) -> FeedbackStore:
    """Build a FeedbackStore seeded with one feedback event per
    requested ``months_back`` value (each value = N months back from
    now, anchored to the 15th of that month). Used to simulate a
    clinic with N distinct calendar months of activity.
    """
    store = FeedbackStore(log_path=tmp_path / "feedback.jsonl")
    now = datetime.now(tz=timezone.utc)
    for m_ago in months_back:
        target = now.replace(day=15, hour=12, minute=0, second=0, microsecond=0)
        for _ in range(m_ago):
            prev_month = target.month - 1
            prev_year = target.year
            if prev_month == 0:
                prev_month = 12
                prev_year -= 1
            target = target.replace(year=prev_year, month=prev_month)
        store.append(
            FeedbackEntry(
                encounter_id=f"enc-m{m_ago}",
                finding_id=f"f-m{m_ago}",
                action=action,  # type: ignore[arg-type]
                severity="medium",
                rule_id=rule_id,
                category="modifier_required",
                timestamp=_iso(target.timestamp()),
                biller_id=biller_id,
            )
        )
    return store


# ---------------------------------------------------------------------------
# 1. Route is registered + returns 200 HTML on the happy paths
# ---------------------------------------------------------------------------


def test_route_is_registered(client: TestClient) -> None:
    """The view exists at /reports/clinic-monthly and returns 200."""
    r = client.get(
        "/reports/clinic-monthly",
        params={"clinic": "any-clinic", "month": "2026-06"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html"), r.headers


def test_invalid_month_returns_400(client: TestClient) -> None:
    """Bad month format → 400 (the view's gate, same as the JSON route)."""
    r = client.get(
        "/reports/clinic-monthly",
        params={"clinic": "biller-A", "month": "2025/01"},
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# 2. insufficient_data branch
# ---------------------------------------------------------------------------


def test_insufficient_data_state_renders_months_have_not_zero(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty store → insufficient_data card with current_months=0.

    Pin: the page must NOT render the ok-branch counters (they're
    gated behind status == 'ok' in the template). And it must show
    the actual current_months value (0 here), not a fabricated
    positive number — that's the whole point of the insufficient_data
    branch.
    """
    empty = FeedbackStore(log_path=tmp_path / "empty.jsonl")
    monkeypatch.setattr(
        "ai_billing_audit.feedback._default",
        empty,
        raising=False,
    )

    r = client.get(
        "/reports/clinic-monthly",
        params={"clinic": "biller-EMPTY", "month": "2026-06"},
    )
    assert r.status_code == 200, r.text
    body = r.text
    # The insufficient_data header is rendered.
    assert "Not enough feedback yet" in body
    # The months-of-feedback the clinic currently has is shown.
    assert "<strong>0</strong>" in body
    # The required threshold is shown.
    assert "<strong>3</strong>" in body
    # None of the ok-branch counters are rendered.
    assert "Total findings" not in body
    assert "Confidence calibration" not in body
    assert "Top modified rules" not in body
    assert "Tuning recommendations" not in body


def test_insufficient_data_with_some_feedback_shows_actual_count(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clinic with 2 months of feedback still hits the stub, and
    current_months reflects the real count (not zero)."""
    store = _seed_store_with_clinic_months(
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
        "/reports/clinic-monthly",
        params={"clinic": "biller-PARTIAL", "month": "2026-06"},
    )
    assert r.status_code == 200, r.text
    body = r.text
    # Still on the insufficient_data branch.
    assert "Not enough feedback yet" in body
    # The actual count (2 distinct months) is surfaced — NOT a
    # fabricated zero and NOT the threshold.
    assert "<strong>2</strong>" in body


# ---------------------------------------------------------------------------
# 3. ok branch — full report rendered
# ---------------------------------------------------------------------------


def test_ok_branch_renders_all_required_fields(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clinic with 3+ months of feedback renders the full report.

    Verifies every field the task spec calls out is present in the
    HTML: total_findings, accepted, dismissed, modified,
    confidence_calibration (HIGH/MEDIUM/LOW), top-3 modified rules
    (with rule_name + count), and tuning_recommendations (always
    >= 1 string).
    """
    store = _seed_store_with_clinic_months(
        tmp_path,
        biller_id="biller-FULL",
        months_back=[1, 2, 3, 4],
        rule_id="R-MOD-25",
        action="modify",
    )
    monkeypatch.setattr(
        "ai_billing_audit.feedback._default",
        store,
        raising=False,
    )

    r = client.get(
        "/reports/clinic-monthly",
        params={"clinic": "biller-FULL", "month": "2026-06"},
    )
    assert r.status_code == 200, r.text
    body = r.text

    # Action counts are present in the headline grid.
    assert "Total findings" in body
    assert "Accepted" in body
    assert "Dismissed" in body
    assert "Modified" in body

    # Confidence calibration badge is rendered. We don't pin the
    # exact bucket (it depends on per-rule precision), only that
    # one of the three known buckets is shown.
    assert "Confidence calibration" in body
    assert any(b in body for b in ("HIGH", "MEDIUM", "LOW"))

    # Top-3 modified rules table is present and includes the rule
    # name we seeded.
    assert "Top modified rules" in body
    assert "R-MOD-25" in body

    # Tuning recommendations section is present with at least one
    # recommendation.
    assert "Tuning recommendations" in body
    # ``<li>`` items only render inside the recs loop, so finding
    # at least one confirms the list is non-empty.
    assert "<li" in body


def test_ok_branch_excludes_insufficient_data_card(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The insufficient_data card MUST NOT render in the ok branch.

    Guards against a regression where the template renders both
    branches simultaneously (a copy-paste mistake). We check for
    the specific heading string the insufficient_data branch uses.
    """
    store = _seed_store_with_clinic_months(
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
        "/reports/clinic-monthly",
        params={"clinic": "biller-FULL", "month": "2026-06"},
    )
    assert r.status_code == 200, r.text
    body = r.text
    assert "Not enough feedback yet" not in body


def test_view_inherits_base_layout(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The view extends base.html — so the topbar + footer are
    present. (Verifies the template isn't accidentally a standalone
    HTML document that bypasses the shared layout.)"""
    store = _seed_store_with_clinic_months(
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
        "/reports/clinic-monthly",
        params={"clinic": "biller-FULL", "month": "2026-06"},
    )
    assert r.status_code == 200
    body = r.text
    # base.html includes the brand link.
    assert 'class="brand"' in body
    # base.html includes the footer.
    assert "footer" in body.lower()


def test_view_links_to_json_and_pdf_siblings(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In the ok branch the page links out to the JSON + PDF
    siblings so a biller can drop to the raw payload or share the
    formatted artifact. These links should NOT render on the
    insufficient_data branch (the JSON would still 200 but the
    PDF 404s; not a useful affordance on an empty state)."""
    store = _seed_store_with_clinic_months(
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
        "/reports/clinic-monthly",
        params={"clinic": "biller-FULL", "month": "2026-06"},
    )
    body = r.text
    assert "/api/reports/monthly?clinic=biller-FULL" in body
    assert "/api/reports/monthly.pdf?clinic_id=biller-FULL" in body

    # Now flip to insufficient_data — the JSON/PDF link bar should
    # disappear.
    empty = FeedbackStore(log_path=tmp_path / "empty.jsonl")
    monkeypatch.setattr(
        "ai_billing_audit.feedback._default",
        empty,
        raising=False,
    )
    r2 = client.get(
        "/reports/clinic-monthly",
        params={"clinic": "biller-FULL", "month": "2026-06"},
    )
    assert r2.status_code == 200
    body2 = r2.text
    assert "/api/reports/monthly.pdf" not in body2
    assert "/api/reports/monthly?clinic=" not in body2
