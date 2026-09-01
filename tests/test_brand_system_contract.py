"""Regression tests for Zorva's authoritative brand-system contract."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CONTRACT = json.loads((DOCS / "BRAND_SYSTEM_CONTRACT.json").read_text())
AUTHORITATIVE = [
    DOCS / "BRAND_BOOK.md",
    DOCS / "BRAND_NARRATIVE.md",
    DOCS / "VOICE.md",
    DOCS / "BRANDING_PITCH_DECK.md",
]


def test_contract_preserves_one_strategy_and_every_external_gate() -> None:
    assert CONTRACT["market"] == "Alberta primary-care clinics using AHCIP"
    assert CONTRACT["category"] == "human-reviewed pre-submit AHCIP claim review"
    assert CONTRACT["primaryCta"] == "Start a conversation."
    assert set(CONTRACT["touchpoints"]) == {
        "public_website",
        "customer_product",
        "zorva_hq",
        "launch_material",
        "discovery",
        "onboarding",
        "support",
        "company_reporting",
    }
    assert set(CONTRACT["separateApprovalGates"]) == {
        "production_release",
        "publication",
        "external_communication",
        "pricing_or_offer_change",
        "spending",
        "customer_material",
        "regulated_claim",
        "sensitive_data_access",
    }


def test_historical_unsafe_anchor_copy_is_absent_from_authoritative_brand_docs() -> (
    None
):
    corpus = "\n".join(path.read_text() for path in AUTHORITATIVE).casefold()
    for phrase in [
        "find the revenue your billers are leaving on the table",
        "catches 6–7 of 10 real billing errors",
        "data stays in a canadian data centre, region confirmed in the baa",
        "a self-improving billing intelligence layer",
        "$499/mo",
        "60-day no-cost pilot",
        "$4,200 per clinician per month",
        "alberta primary care is leaving $40k–$120k",
        "zorva audits every claim",
    ]:
        assert phrase not in corpus, phrase


def test_documented_typography_matches_the_implemented_portal_families() -> None:
    layout = (ROOT / "apps" / "portal" / "src" / "app" / "layout.tsx").read_text()
    book = (DOCS / "BRAND_BOOK.md").read_text()
    typography = (DOCS / "BRANDING_TYPOGRAPHY.md").read_text()

    for family in ["Inter", "Fraunces", "IBM_Plex_Mono", "JetBrains_Mono"]:
        assert family in layout
    for label in ["Inter", "Fraunces", "IBM Plex Mono", "JetBrains Mono"]:
        assert label in book
        assert label in typography


def test_proposed_visual_assets_are_not_misreported_as_existing() -> None:
    assert not (ROOT / "apps" / "portal" / "public" / "illustrations").exists()
    assert not (ROOT / "apps" / "portal" / "public" / "icon.svg").exists()
    book = (DOCS / "BRAND_BOOK.md").read_text()
    imagery = (DOCS / "BRANDING_IMAGERY.md").read_text()
    assert "promised files not found" in book
    assert "proposed backlog, not an asset inventory" in imagery
