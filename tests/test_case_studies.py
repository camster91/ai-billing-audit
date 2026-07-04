"""Tests for the case-studies module.

What's pinned
-------------
* Three case studies (easy / medium / hard), one per difficulty band
* Each case study has the required fields: title, difficulty,
  specialty, encounter_id, clinical_scenario, claim_summary,
  findings (>=1), what_biller_would_have_done, dollar_impact
* Each case study has at least one HIGH or CRITICAL finding
  (otherwise the story isn't compelling)
* The encounter_link points to a real route
* The slugs are URL-safe
* The dollar impact math is consistent: avg claim × findings
  matches the dollar mention (within reason)
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_billing_audit.case_studies import (
    CASE_STUDIES,
    case_studies_index,
    get_case_study,
    total_dollar_impact_per_study,
)


# ---------- module-level data tests ----------


def test_three_case_studies_defined():
    assert len(CASE_STUDIES) == 3


def test_one_per_difficulty_band():
    difficulties = {cs.difficulty for cs in CASE_STUDIES}
    assert difficulties == {"easy", "medium", "hard"}


def test_each_case_study_has_required_fields():
    required_fields = [
        "slug", "title", "difficulty", "specialty", "encounter_id",
        "clinical_scenario", "claim_summary", "findings",
        "what_biller_would_have_done", "dollar_impact",
    ]
    for cs in CASE_STUDIES:
        for field in required_fields:
            assert getattr(cs, field), (
                f"CaseStudy {cs.slug} missing field {field}"
            )


def test_each_case_study_has_at_least_one_high_or_critical_finding():
    """The story needs teeth — at least one HIGH/CRITICAL finding."""
    for cs in CASE_STUDIES:
        high_or_critical = [
            f for f in cs.findings
            if f.get("severity") in ("high", "critical")
        ]
        assert len(high_or_critical) >= 1, (
            f"{cs.slug} needs at least one HIGH or CRITICAL finding; "
            f"got severities {[f.get('severity') for f in cs.findings]}"
        )


def test_each_finding_has_rule_id_and_quote():
    for cs in CASE_STUDIES:
        for f in cs.findings:
            assert f.get("rule_id"), f"{cs.slug}: finding missing rule_id"
            assert f.get("quote"), f"{cs.slug}: finding missing quote"
            assert f.get("severity"), f"{cs.slug}: finding missing severity"
            assert f.get("severity") in (
                "info", "low", "medium", "high", "critical"
            ), f"{cs.slug}: bad severity {f.get('severity')}"


def test_slugs_are_url_safe():
    # Allow underscores + hyphens (we use underscore-prefixed
    # encounter_ids in slugs). All other URL-unsafe characters
    # are rejected.
    slug_pattern = re.compile(r"^[a-z0-9][a-z0-9_-]{1,80}$")
    for cs in CASE_STUDIES:
        assert slug_pattern.match(cs.slug), f"bad slug: {cs.slug}"


def test_slugs_are_unique():
    slugs = [cs.slug for cs in CASE_STUDIES]
    assert len(slugs) == len(set(slugs))


def test_encounter_ids_correspond_to_real_data():
    """Each case study's encounter_id should exist in either
    data/synth/val.json or data/synth/train.json. It doesn't have to be
    a registered demo (case studies point to working endpoints that
    load from the data files)."""
    import json
    val = {e["encounter_id"] for e in json.loads(
        (Path(__file__).parent.parent / "data" / "synth" / "val.json").read_text()
    )}
    train = {e["encounter_id"] for e in json.loads(
        (Path(__file__).parent.parent / "data" / "synth" / "train.json").read_text()
    )}
    for cs in CASE_STUDIES:
        assert cs.encounter_id in val or cs.encounter_id in train, (
            f"{cs.slug}: encounter_id {cs.encounter_id} not in val.json "
            f"or train.json"
        )


def test_encounter_links_use_real_route():
    for cs in CASE_STUDIES:
        if cs.encounter_link:
            assert cs.encounter_link.startswith("/encounter/")
            assert cs.encounter_link.endswith(cs.encounter_id)


def test_get_case_study_lookup():
    cs = get_case_study("enc_10032-easy-duplicate-service")
    assert cs is not None
    assert cs.encounter_id == "enc_10032"


def test_get_case_study_unknown_returns_none():
    cs = get_case_study("this-doesnt-exist")
    assert cs is None


def test_case_studies_index_returns_three():
    items = case_studies_index()
    assert len(items) == 3
    for item in items:
        # Index shape: slug, title, difficulty, specialty,
        # n_findings, encounter_link, summary, encounter_id
        for key in (
            "slug", "title", "difficulty", "specialty",
            "n_findings", "encounter_link", "summary",
            "encounter_id",
        ):
            assert key in item


def test_total_dollar_impact_per_study():
    impact = total_dollar_impact_per_study()
    assert len(impact) == 3
    # All values should be positive (specialty avg × findings count)
    for slug, v in impact.items():
        assert v > 0, f"{slug} should have a positive dollar impact, got {v}"


def test_dollar_impact_uses_specialty_overrides():
    """enc_0000 is cardiology at $240/claim; with 5 findings = $1,200."""
    impact = total_dollar_impact_per_study()
    cardiology_cs = next(cs for cs in CASE_STUDIES if cs.specialty == "cardiology")
    assert cardiology_cs.slug in impact
    # 5 findings × $240 = $1,200
    assert impact[cardiology_cs.slug] == 5 * 240


def test_clinical_scenarios_are_anonymized():
    """No patient names, addresses, or other PHI in the prose."""
    for cs in CASE_STUDIES:
        text = " ".join([
            cs.clinical_scenario, cs.claim_summary,
            cs.what_biller_would_have_done, cs.dollar_impact,
        ])
        # Common PHI patterns
        for pattern in ["John", "Jane", "123 Main", "555-"]:
            assert pattern not in text, (
                f"{cs.slug} contains potential PHI: {pattern}"
            )


def test_finding_count_matches_dollar_impact_text():
    """The 'n findings' count is consistent across the case study."""
    for cs in CASE_STUDIES:
        # The encounter detail page shows 'N findings' as a chip
        n = len(cs.findings)
        # The dollar impact text should not say a different number
        for wrong_n in range(1, 12):
            if wrong_n == n:
                continue
            assert f"{wrong_n} findings" not in cs.dollar_impact.lower(), (
                f"{cs.slug}: dollar_impact mentions {wrong_n} findings "
                f"but the case study has {n}"
            )


# ---------- HTTP route tests ----------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    import ai_billing_audit.api as api_mod
    importlib.reload(api_mod)
    app = api_mod.create_app()
    return TestClient(app)


def test_case_studies_index_returns_200(client):
    resp = client.get("/case-studies")
    assert resp.status_code == 200


def test_case_studies_index_lists_all_three(client):
    resp = client.get("/case-studies")
    html = resp.text
    # All three slugs should be linked
    assert "enc_10032-easy-duplicate-service" in html
    assert "enc_0011-medium-imaging-coverage" in html
    assert "enc_0000-hard-modifier-25-chest-pain" in html


def test_case_studies_index_shows_difficulty_chips(client):
    resp = client.get("/case-studies")
    html = resp.text
    assert "EASY" in html
    assert "MEDIUM" in html
    assert "HARD" in html


def test_case_studies_index_links_to_live_encounters(client):
    """Each case study points to its encounter detail page.
    The page exists at /encounter/{id} but may 404 if the
    encounter isn't registered as a demo (enc_0011, enc_10032,
    enc_0000 are all registered but future case studies might
    not be)."""
    resp = client.get("/case-studies")
    html = resp.text
    assert "/encounter/enc_10032" in html
    assert "/encounter/enc_0011" in html
    assert "/encounter/enc_0000" in html


def test_case_study_detail_returns_200(client):
    resp = client.get("/case-studies/enc_10032-easy-duplicate-service")
    assert resp.status_code == 200


def test_case_study_detail_shows_scenario_and_findings(client):
    resp = client.get(
        "/case-studies/enc_0000-hard-modifier-25-chest-pain"
    )
    html = resp.text
    # Title
    assert "Modifier-25" in html
    # The HIGH-severity modifier-25 finding should appear
    assert "rule_modifier_25_001" in html
    # HIGH severity badge
    assert "HIGH" in html
    # The dollar impact section
    assert "Dollar impact" in html or "dollar impact" in html


def test_case_study_detail_includes_quote_highlights(client):
    resp = client.get(
        "/case-studies/enc_0000-hard-modifier-25-chest-pain"
    )
    html = resp.text
    # Blockquote with verbatim quote from clinical note
    assert "<blockquote" in html
    assert "separately identifiable E/M" in html


def test_case_study_detail_unknown_slug_returns_404(client):
    resp = client.get("/case-studies/this-doesnt-exist")
    assert resp.status_code == 404


def test_case_study_detail_has_cta_to_roi(client):
    """Each case study should drive the prospect toward the ROI calc."""
    resp = client.get(
        "/case-studies/enc_10032-easy-duplicate-service"
    )
    html = resp.text
    assert "/roi" in html


def test_case_study_detail_links_back_to_index(client):
    """Each detail page should have a 'back to all case studies' link."""
    resp = client.get(
        "/case-studies/enc_0011-medium-imaging-coverage"
    )
    html = resp.text
    assert "/case-studies" in html
    assert "All case studies" in html or "case-studies" in html


def test_case_study_pages_use_base_template(client):
    """Case study pages share the layout with the rest of the app."""
    for path in [
        "/case-studies",
        "/case-studies/enc_10032-easy-duplicate-service",
    ]:
        resp = client.get(path)
        html = resp.text
        assert "<header" in html and "tenant-pill" in html
        assert "<footer" in html or "Zorva v0.1.0" in html


def test_case_studies_index_in_topbar_nav(client):
    """Add a Case Studies link to the topbar so it's discoverable."""
    resp = client.get("/")
    html = resp.text
    # Topbar nav should have a case studies link
    assert "/case-studies" in html
