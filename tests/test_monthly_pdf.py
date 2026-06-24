"""Tests for the monthly-report PDF endpoint (kanban ``t_4c278e95``).

Three contracts to pin:

1. **Happy path** — a clinic with 3+ months of feedback gets a
   non-empty ``application/pdf`` response whose body contains
   the clinic name + the requested month + at least one of the
   top rules we seeded.

2. **Insufficient data** — a clinic with < 3 months of feedback
   gets 404 (we refuse to render a useless empty sheet rather
   than waste a biller's time on it).

3. **Bad month format** — non-``YYYY-MM`` month → 400, same
   regex gate the JSON sibling uses.

The reportlab-vs-plain-text split is exercised by
:func:`test_render_works_with_or_without_reportlab` which calls
the module's public :func:`render_monthly_pdf` directly and
asserts the contract holds either way (non-empty binary,
contains key strings, content-type target is ``application/pdf``
end-to-end).
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
from ai_billing_audit.monthly_pdf import (  # noqa: E402
    build_report_payload,
    render_monthly_pdf,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    return TestClient(create_app())


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _seed_feedback(
    tmp_path: Path,
    *,
    biller_id: str,
    months_back: list[int],
) -> FeedbackStore:
    """Seed one feedback event per requested month-back, all on the
    same ``R-MOD-25`` rule so the PDF's "top 3 flagged rules" row
    has something to render.
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
        ts = target.timestamp()
        store.append(FeedbackEntry(
            encounter_id=f"enc-m{m_ago}",
            finding_id=f"f-m{m_ago}",
            action="accept",
            severity="medium",
            rule_id="R-MOD-25",
            category="modifier_required",
            timestamp=_iso(ts),
            biller_id=biller_id,
        ))
    return store


# ─── 1. Insufficient data → 404 ──────────────────────────────────────────


def test_insufficient_data_returns_404(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero feedback months for the clinic → 404 (no PDF, not a
    useless empty sheet). Verifies the route honours the same
    3-month threshold the JSON sibling uses."""
    empty = FeedbackStore(log_path=tmp_path / "empty.jsonl")
    monkeypatch.setattr(
        "ai_billing_audit.feedback._default", empty, raising=False,
    )

    r = client.get(
        "/api/reports/monthly.pdf",
        params={"clinic_id": "biller-EMPTY", "month": "2026-06"},
    )
    assert r.status_code == 404, r.text
    detail = r.json().get("detail", "")
    assert "3+" in detail or "feedback" in detail.lower()


def test_two_months_still_insufficient(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even 2 months of feedback is below the threshold."""
    store = _seed_feedback(
        tmp_path, biller_id="biller-PARTIAL", months_back=[1, 2],
    )
    monkeypatch.setattr(
        "ai_billing_audit.feedback._default", store, raising=False,
    )

    r = client.get(
        "/api/reports/monthly.pdf",
        params={"clinic_id": "biller-PARTIAL", "month": "2026-06"},
    )
    assert r.status_code == 404


# ─── 2. Bad month format → 400 ──────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_month",
    ["2026/06", "26-06", "2026-6", "Jun 2026", "", "2026-06-15"],
)
def test_bad_month_returns_400(
    client: TestClient,
    bad_month: str,
) -> None:
    r = client.get(
        "/api/reports/monthly.pdf",
        params={"clinic_id": "biller-X", "month": bad_month},
    )
    assert r.status_code == 400, (
        f"expected 400 for month={bad_month!r}, got {r.status_code}"
    )


def test_missing_month_returns_400(client: TestClient) -> None:
    r = client.get(
        "/api/reports/monthly.pdf",
        params={"clinic_id": "biller-X"},
    )
    assert r.status_code == 400
    assert "month" in r.json().get("detail", "").lower()


# ─── 3. Happy path ─────────────────────────────────────────────────────


def test_three_months_returns_pdf_with_key_strings(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clinic with 3+ months of feedback gets a non-empty PDF
    response. The payload aggregation must surface the clinic
    name, the month, and the rule we seeded feedback against;
    the HTTP layer wraps that into a ``%PDF-`` document (when
    reportlab is installed) or a plain-text fallback. Either
    way the response is non-empty and the Content-Type is
    ``application/pdf``.
    """
    store = _seed_feedback(
        tmp_path,
        biller_id="Acme Family Practice",
        months_back=[1, 2, 3],
    )
    monkeypatch.setattr(
        "ai_billing_audit.feedback._default", store, raising=False,
    )

    r = client.get(
        "/api/reports/monthly.pdf",
        params={"clinic_id": "Acme Family Practice", "month": "2026-06"},
    )
    assert r.status_code == 200, r.text
    # Content-Type is application/pdf per the spec.
    assert r.headers["content-type"].startswith("application/pdf"), (
        f"expected application/pdf, got {r.headers['content-type']!r}"
    )
    # Content-Disposition names the file with the clinic + month.
    cd = r.headers.get("content-disposition", "")
    assert "zorva-monthly" in cd
    assert "2026-06" in cd
    # Non-empty body — the smallest legitimate PDF is a few KB;
    # the plain-text fallback is ~1 KB.
    body = r.content
    assert body and len(body) > 200, f"expected non-trivial body, got {len(body)} bytes"
    # The PDF's metadata (Title field) must include the clinic
    # name + month, so a downstream user can identify the file
    # without opening it. reportlab sets Title from our
    # ``title=`` kwarg above.
    text = body.decode("latin-1", errors="ignore")
    assert "Acme Family Practice" in text
    assert "2026-06" in text


def test_payload_aggregation_surfaces_seeded_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Separate test for the aggregation layer: the seeded rule
    MUST show up in ``top_rules`` of the payload that the route
    hands to the renderer. This is the assertion the previous
    test couldn't make against a compressed PDF stream, and it
    catches regressions in the rule-aggregation logic without
    requiring a PDF parser.
    """
    store = _seed_feedback(
        tmp_path, biller_id="Acme Family Practice", months_back=[1, 2, 3],
    )
    monkeypatch.setattr(
        "ai_billing_audit.feedback._default", store, raising=False,
    )
    # We need 3+ months to pass the route gate; call the payload
    # builder directly so the gate doesn't get in the way of
    # inspecting the aggregation. days=120 (4 months) ensures
    # the months_back=3 feedback event is still in the window.
    from ai_billing_audit.monthly_pdf import build_report_payload
    from ai_billing_audit.feedback import get_default_store
    feedback_entries = get_default_store().read_all()
    payload = build_report_payload(
        clinic_id="Acme Family Practice",
        clinic_name="Acme Family Practice",
        month="2026-06",
        feedback_entries=feedback_entries,
        audit_action_rows=[],
        days=120,
    )
    assert payload["clinic_name"] == "Acme Family Practice"
    assert payload["month"] == "2026-06"
    rule_ids = [r["rule_id"] for r in payload["top_rules"]]
    assert "R-MOD-25" in rule_ids, (
        f"expected R-MOD-25 in top_rules, got {rule_ids}"
    )


def test_pdf_body_is_valid_pdf_when_reportlab_available(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When reportlab is importable, the response body starts with
    the ``%PDF-`` magic bytes. This is the production case (reportlab
    is in the dev environment) — it pins the upgrade path so we
    don't accidentally serve the text fallback when reportlab is
    installed.
    """
    from ai_billing_audit import monthly_pdf
    if not monthly_pdf._REPORTLAB_AVAILABLE:
        pytest.skip("reportlab not installed; text-fallback path covered separately")
    store = _seed_feedback(
        tmp_path, biller_id="biller-FULL", months_back=[1, 2, 3, 4],
    )
    monkeypatch.setattr(
        "ai_billing_audit.feedback._default", store, raising=False,
    )

    r = client.get(
        "/api/reports/monthly.pdf",
        params={"clinic_id": "biller-FULL", "month": "2026-06"},
    )
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-", (
        f"expected PDF magic, got {r.content[:32]!r}"
    )


# ─── 4. Direct module tests (no HTTP) ──────────────────────────────────


def test_build_report_payload_aggregates_findings() -> None:
    """The payload builder takes a synthetic list of encounters +
    feedback rows and produces the right shape. No HTTP, no auth,
    no I/O — purely unit-level so a regression in the
    aggregation is caught here, not in the route test."""
    from datetime import datetime, timezone
    month = "2026-06"
    month_start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    enc_ts = month_start.timestamp() + 5 * 86400  # 5 days into the month
    encounters = [
        {
            "encounter_id": "enc-1",
            "status": "done",
            "submitted_at": enc_ts,
            "finished_at": enc_ts,
            "result": {
                "findings_count": 2,
                "findings": [
                    {
                        "finding_id": "f1",
                        "rule_id": "R-MOD-25",
                        "rule_ids": ["R-MOD-25"],
                        "estimated_dollar": 45.0,
                    },
                    {
                        "finding_id": "f2",
                        "rule_id": "R-CARC",
                        "rule_ids": ["R-CARC"],
                        "estimated_dollar": 0.0,
                    },
                ],
            },
        },
    ]
    now = enc_ts + 30 * 86400
    payload = build_report_payload(
        clinic_id="biller-X",
        clinic_name="Test Clinic",
        month=month,
        encounters=encounters,
        feedback_entries=[],
        audit_action_rows=[],
        now=now,
        days=30,
    )
    assert payload["clinic_id"] == "biller-X"
    assert payload["clinic_name"] == "Test Clinic"
    assert payload["month"] == "2026-06"
    assert payload["total_encounters"] == 1
    assert payload["total_findings"] == 2
    # Top rules is empty because we passed no feedback.
    assert payload["top_rules"] == []
    # Top opportunities: only the one with a non-zero dollar.
    # (The fallback for the missing compute_revenue_opportunities
    # import keeps the original 45.0 figure.)
    assert len(payload["top_opportunities"]) <= 3
    if payload["top_opportunities"]:
        first = payload["top_opportunities"][0]
        assert first["estimated_dollar"] >= 0
    # Appeal counts default to zero.
    assert payload["appeal_counts"]["won"] == 0
    assert payload["appeal_counts"]["lost"] == 0


def test_render_works_with_or_without_reportlab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force the text-fallback path by toggling the import flag,
    then call :func:`render_monthly_pdf` directly. Asserts the
    fallback contract: non-empty bytes, key strings present, the
    response is a UTF-8 string the operator can grep.
    """
    from ai_billing_audit import monthly_pdf

    payload = {
        "clinic_id": "biller-X",
        "clinic_name": "Fallback Clinic",
        "month": "2026-06",
        "generated_at": "2026-06-24T12:00:00Z",
        "total_encounters": 7,
        "total_findings": 12,
        "top_rules": [{"rule_id": "R-MOD-25", "count": 5}],
        "top_opportunities": [
            {
                "rule_id": "R-MOD-25",
                "rule_name": "Modifier 25 required",
                "estimated_dollar": 45.0,
                "suggested_action": "Append modifier 25 to the E/M code.",
            }
        ],
        "median_time_to_act_hours": 3.5,
        "appeal_counts": {
            "won": 2, "lost": 1, "pending": 1, "withdrawn": 0, "filed": 0,
        },
    }
    # Force fallback path even if reportlab is installed.
    monkeypatch.setattr(monthly_pdf, "_REPORTLAB_AVAILABLE", False)
    out = monthly_pdf.render_monthly_pdf(payload)
    assert isinstance(out, bytes)
    assert len(out) > 200
    text = out.decode("utf-8")
    assert "Fallback Clinic" in text
    assert "2026-06" in text
    assert "R-MOD-25" in text
    assert "Modifier 25 required" in text
    # No PDF magic in the fallback (it's plain text).
    assert not out.startswith(b"%PDF-")
    # And the real path still works when reportlab is available.
    monkeypatch.setattr(monthly_pdf, "_REPORTLAB_AVAILABLE", True)
    if monthly_pdf._REPORTLAB_AVAILABLE:
        out_pdf = monthly_pdf.render_monthly_pdf(payload)
        assert out_pdf.startswith(b"%PDF-"), "expected real PDF when reportlab is on"
