"""Smoke tests for the mobile-responsive encounter detail page (kanban ``t_807bfae4``).

Pins three things the task body calls out:

1. The encounter detail page still renders cleanly at the
   desktop endpoint (HTTP 200, all sections present) after
   the responsive CSS was added — i.e. the new media queries
   did not break the rendered DOM.
2. The new ``@media`` rules live in the dashboard stylesheet
   that the page references, so a future refactor that drops
   them would fail this test.
3. Every selector we rely on for the responsive behaviour
   actually exists in the static CSS, so a typo in either
   the CSS or the test gets caught at CI time rather than at
   the coffee shop.

There is no automated visual regression test (out of scope
per the task body). The two breakpoint sizes (768px tablet,
480px phone) are exercised by parsing the CSS text directly,
which is cheap and deterministic.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_billing_audit import api as api_mod
from ai_billing_audit.api import create_app


class _Fixture:
    def __init__(self, app, log, client):
        self.app = app
        self.log = log
        self.client = client


@pytest.fixture
def fx(tmp_path, monkeypatch):
    """Build an app + TestClient + audit log redirect.

    Mirrors the ``fx`` fixture in test_encounter_detail_uploaded.py
    so this test stays compatible with the existing upload-encounter
    rendering path.
    """
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("MIN_SEVERITY_TO_SHOW", "info")
    log = tmp_path / "upload_jobs.jsonl"
    monkeypatch.setenv("UPLOAD_AUDIT_LOG_PATH", str(log))
    app = create_app()
    return _Fixture(app, log, TestClient(app))


def _write_log_row(log: Path, encounter_id: str, ran_via: str = "upload_portal_with_user_note") -> None:
    """Write a single demo row with one medium-severity finding.

    Mirrors the helper from test_encounter_detail_uploaded.py so
    the rendered HTML exercises the same finding-actions row
    that the responsive CSS targets.
    """
    row = {
        "job_id": f"job-{encounter_id}",
        "encounter_id": encounter_id,
        "status": "done",
        "result": {
            "audit_status": "ok",
            "ran_via": ran_via,
            "findings_count": 1,
            "findings": [
                {
                    "finding_id": "F1",
                    "severity": "high",
                    "category": "documentation_gap",
                    "rule_id": "DX_LINKAGE_REQUIRED",
                    "suggested_code": "99213",
                    "quote": "Documentation lacks diagnosis linkage for the hypertension code billed at the visit.",
                    "explanation": "Test explanation for the responsive-CSS smoke test.",
                }
            ],
            "summary": f"Test audit summary for {encounter_id}",
            "difficulty_tier": "HARD",
            "variant": "flagged",
        },
    }
    with log.open("a") as f:
        f.write(json.dumps(row) + "\n")


def test_encounter_detail_renders_with_findings(fx):
    """The encounter detail page still renders 200 with all
    sections present after the responsive CSS was added.

    This is the headline smoke test from the task body: existing
    functionality survives the responsive refactor.
    """
    _write_log_row(fx.log, "ENC-MOBILE-001")
    r = fx.client.get("/encounter/ENC-MOBILE-001")
    assert r.status_code == 200, r.text

    body = r.text
    # Encounter id surfaces
    assert "ENC-MOBILE-001" in body
    # Finding card rendered (so the CSS targets something real)
    assert "DX_LINKAGE_REQUIRED" in body
    assert "Documentation lacks diagnosis linkage" in body
    # The three per-finding action buttons are present (they're
    # what the responsive CSS targets at the 768px breakpoint).
    # Match leniently: the template emits ``>Modify\n          ``
    # inside the <button> tag, so we just look for the label.
    for label in ("Accept", "Dismiss", "Modify"):
        assert label in body, f"missing {label} button in rendered HTML"
    # The .action-bar (Re-run / Flag / View raw JSON) is what the
    # 768px rule stacks — verify the class is in the rendered HTML
    # so the CSS has a target.
    assert "action-bar" in body
    # The detail-grid container is what the 768px rule collapses
    # to a single column.
    assert "detail-grid" in body


def test_responsive_css_present_in_stylesheet():
    """Both new breakpoints live in the static CSS.

    Pinned so a future refactor that drops one of them
    (e.g. a copy/paste regression during a dashboard CSS
    split) fails this test instead of being caught by a
    biller on their phone.
    """
    css_path = (
        Path(api_mod.__file__).resolve().parent
        / "static"
        / "dashboard.css"
    )
    css = css_path.read_text(encoding="utf-8")
    # The two new breakpoints
    assert "@media (max-width: 768px)" in css
    assert "@media (max-width: 480px)" in css
    # Required responsive behaviours from the task body
    # (string-anchored so a typo gets caught).
    assert "detail-grid" in css  # target sidebar
    assert "finding-actions" in css  # target Accept/Dismiss/Modify
    assert "min-height: 44px" in css  # tap-target floor
    assert "flex-basis: 100%" in css  # badge wrap to new line


def test_each_responsive_selector_targets_a_real_class():
    """Sanity-check the selectors we depend on actually exist
    in either the static CSS (so they style something) or in
    the template (so they have something to style).

    This is the cheap version of a visual regression test —
    it doesn't render the page at 360px but it catches the
    common regressions of "renamed the class in CSS but not
    in the template" and vice versa.
    """
    css_path = (
        Path(api_mod.__file__).resolve().parent
        / "static"
        / "dashboard.css"
    )
    css = css_path.read_text(encoding="utf-8")
    tmpl_path = (
        Path(api_mod.__file__).resolve().parent
        / "templates"
        / "encounter_detail.html"
    )
    tmpl = tmpl_path.read_text(encoding="utf-8")
    for cls in (
        "detail-grid",
        "finding-actions",
        "finding-item__head",
        "chip-rule",
        "action-bar",
        "page-head",
        "revenue-opportunity-card",
        "audit-trail-table",
        "clinical-note",
    ):
        assert cls in css, f"CSS missing class .{cls}"
        # Template check: the class should appear in at least
        # one of the templates this dashboard renders. We
        # check encounter_detail.html + the base for safety.
        assert cls in tmpl or cls in (Path(api_mod.__file__).resolve().parent / "templates" / "base.html").read_text(), (
            f"class .{cls} not referenced from any template"
        )


def test_320px_baseline_no_horizontal_scroll_rules():
    """Pins that the 480px breakpoint — which the task body
    pins as the floor for 320px phones — actually has rules
    that reduce layout pressure (smaller root font, tighter
    padding, badge wrap).

    The fix is ``flex-basis: 100%`` on the per-finding badge
    classes; this test reads the CSS in order to verify the
    exact selector list is present, so a future "I'll just
    remove these one by one, they're not used" edit gets
    caught.
    """
    css_path = (
        Path(api_mod.__file__).resolve().parent
        / "static"
        / "dashboard.css"
    )
    css = css_path.read_text(encoding="utf-8")
    # Find the 480px block and assert each badge class is wrapped.
    start = css.find("@media (max-width: 480px)")
    assert start != -1, "no @media (max-width: 480px) block"
    end = css.find("@media", start + 1)
    block = css[start:end if end != -1 else len(css)]
    # All severity badge variants + the chip-rule + confidence badge
    # appear inside the 480px block as flex-basis: 100% targets.
    for token in (
        "chip-rule",
        "badge-sev-info",
        "badge-sev-low",
        "badge-sev-medium",
        "badge-sev-high",
        "badge-sev-critical",
        "badge-confidence",
    ):
        assert token in block, f"480px block missing {token}"
    assert "flex-basis: 100%" in block
