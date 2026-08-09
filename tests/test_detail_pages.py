"""Tests for the per-term and per-release detail pages.

P0 audit fix 2026-07-13 (COMPLETENESS-AUDIT.md): the
glossary and changelog were flat list pages with no
per-term / per-version URLs. Privacy officers sharing
single-term definitions had no clean way to link to a
specific term. Added:
  - /glossary/{slug}   (22 terms)
  - /changelog/{version}   (5 releases)
"""

from __future__ import annotations

import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    import ai_billing_audit.api as api_mod

    importlib.reload(api_mod)
    app = api_mod.create_app()
    return TestClient(app)


# ─── /glossary/{slug} ─────────────────────────────────────────────


def test_glossary_index_renders_all_terms(client):
    resp = client.get("/glossary")
    assert resp.status_code == 200
    body = resp.text
    # All 22 term names should be visible
    for term in [
        "AHCIP",
        "AWV",
        "CMGP",
        "CPT",
        "E/M",
        "FHIR",
        "GR",
        "HIA",
        "HIPAA",
        "H-Link",
        "HMV",
        "IMA",
        "LLM",
        "Modifier-25",
        "MUE",
        "NCCI",
        "PCN",
        "PHIPA",
        "PIPEDA",
        "SOMB",
        "SFTP",
        "837P",
    ]:
        assert term in body, f"/glossary missing term: {term}"


def test_glossary_index_links_to_per_term_pages(client):
    resp = client.get("/glossary")
    assert resp.status_code == 200
    # Per-term link present
    assert 'href="/glossary/ahcip"' in resp.text
    assert 'href="/glossary/modifier-25"' in resp.text


def test_glossary_per_term_page_renders(client):
    resp = client.get("/glossary/ahcip")
    assert resp.status_code == 200
    body = resp.text
    assert "AHCIP" in body
    assert "Alberta Health Care Insurance Plan" in body
    # Back-link to the glossary index
    assert 'href="/glossary"' in body
    # OG meta for sharing
    assert 'property="og:title"' in body


def test_glossary_per_term_related_links_work(client):
    resp = client.get("/glossary/modifier-25")
    assert resp.status_code == 200
    # modifier-25 is related to GR + AHCIP + E/M per glossary.py
    body = resp.text
    assert "Related terms" in body
    assert 'href="/glossary/gr"' in body
    assert 'href="/glossary/ahcip"' in body
    assert 'href="/glossary/em-em"' in body


def test_glossary_404_for_unknown_term(client):
    resp = client.get("/glossary/this-term-does-not-exist")
    assert resp.status_code == 404
    body = resp.text
    # Branded 404
    assert "404" in body or "not found" in body.lower()


def test_glossary_per_term_uses_base_template(client):
    resp = client.get("/glossary/ahcip")
    body = resp.text
    # Topbar with brand SVG
    assert 'aria-label="Zorva home"' in body
    # Footer
    assert "<footer" in body


# ─── /changelog/{version} ─────────────────────────────────────────


def test_changelog_index_renders_all_releases(client):
    resp = client.get("/changelog")
    assert resp.status_code == 200
    body = resp.text
    # All 5 release versions should be visible
    for v in ["v0.5.0", "v0.4.0", "v0.3.0", "v0.2.0", "v0.1.0"]:
        assert v in body, f"/changelog missing version: {v}"


def test_changelog_per_release_page_renders(client):
    resp = client.get("/changelog/v0.5.0")
    assert resp.status_code == 200
    body = resp.text
    assert "v0.5.0" in body
    # Back-link to the changelog index
    assert 'href="/changelog"' in body
    # OG meta for sharing
    assert 'property="og:title"' in body
    # Body has the "Added" section from v0.5.0
    assert "Added" in body


def test_changelog_per_release_body_has_findings(client):
    """Each release body should have the long-form 'Added /
    Changed / Fixed' sections (or at minimum a 'Added' section
    for a marketing-readable release note)."""
    for v in ["v0.5.0", "v0.4.0", "v0.3.0", "v0.2.0", "v0.1.0"]:
        resp = client.get(f"/changelog/{v}")
        assert resp.status_code == 200, f"/changelog/{v} returned {resp.status_code}"
        body = resp.text
        # Each release has at least one <h2>Added</h2> in the body
        assert "Added" in body, f"/changelog/{v} body is missing 'Added' section"


def test_changelog_404_for_unknown_version(client):
    resp = client.get("/changelog/v999.0.0")
    assert resp.status_code == 404
    body = resp.text
    assert "404" in body or "not found" in body.lower()


def test_changelog_per_release_uses_base_template(client):
    resp = client.get("/changelog/v0.5.0")
    body = resp.text
    assert 'aria-label="Zorva home"' in body
    assert "<footer" in body


# ─── /blog/{slug} (cross-link integration test) ──────────────────


def test_blog_post_links_in_sitemap_match_routes(client):
    """The feeds.PUBLIC_MARKETING_PATHS sitemap must list the
    same blog slugs the /blog/{slug} route serves."""
    from ai_billing_audit.feeds import BLOG_POSTS, PUBLIC_MARKETING_PATHS

    feed_slugs = {p["url_path"] for p in BLOG_POSTS}
    # All blog slug paths in the sitemap must be reachable
    for path in feed_slugs:
        if path.startswith("/blog/"):
            assert path in PUBLIC_MARKETING_PATHS, (
                f"{path} is in BLOG_POSTS but not in PUBLIC_MARKETING_PATHS"
            )
            # And the route must work
            resp = client.get(path)
            assert resp.status_code == 200, f"{path} is not 200"


# ─── Case study index (4th AHCIP case study) ──────────────────────


def test_case_studies_includes_ahcip_grounded_study(client):
    """The case_studies index should include the 4th AHCIP-
    grounded case study (enc_ahcip_001) that demonstrates
    Zorva on a real Alberta AHCIP claim with SOMB fee
    codes and GR references (P0 audit fix)."""
    from ai_billing_audit.case_studies import CASE_STUDIES

    ahcip_cs = [cs for cs in CASE_STUDIES if cs.specialty == "ahcip_family_medicine"]
    assert len(ahcip_cs) == 1, (
        f"Expected exactly 1 AHCIP-grounded case study, got {len(ahcip_cs)}"
    )
    cs = ahcip_cs[0]
    # AHCIP-grounded body uses SOMB fee codes + GR references
    # (check across all body fields, not just scenario/summary)
    all_text = " ".join(
        [
            cs.clinical_scenario,
            cs.claim_summary,
            cs.what_biller_would_have_done,
            cs.dollar_impact,
            " ".join(f.get("rationale", "") for f in cs.findings),
        ]
    )
    # SOMB mentioned in the rationale + dollar impact
    assert "SOMB" in all_text, "AHCIP case study should mention SOMB"
    # 03.04A is the comprehensive office visit SOMB code
    assert "03.04A" in cs.claim_summary
    # The case study lists AHCIP rule IDs (AH-MOD-25, AH-DX-01, etc.)
    rule_ids = {f["rule_id"] for f in cs.findings}
    assert any(rid.startswith("AH-") for rid in rule_ids), (
        f"AHCIP case study should use AHCIP rule IDs, got {rule_ids}"
    )


def test_ahcip_case_study_detail_page_renders(client):
    """The AHCIP-grounded case study detail page renders and
    mentions both SOMB and a GR reference."""
    resp = client.get("/case-studies/enc_ahcip_001-modifier-25")
    assert resp.status_code == 200
    body = resp.text
    # SOMB fee code 03.04A appears
    assert "03.04A" in body
    # AHCIP GR reference (GR 1.4 — modifier-25)
    assert "GR 1.4" in body or "GR&nbsp;1.4" in body
