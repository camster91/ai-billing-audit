"""Tests for the Zorva system context module.

The module encodes who Zorva is, who it serves, what compliance
framework applies per market, and how to compose a structured
context envelope for the auditor + downstream consumers.

What's pinned
-------------
* infer_market: explicit country_code > payer_id prefix >
  health-number digit heuristics > default CA
* build_context_for_encounter: returns the right per-market fields
  (compliance_law, billing_authority for CA provinces, etc.)
* appeal_recipient_for: returns a sensible per-market string
* MARKETS is the single source of truth — no duplicates elsewhere
"""
from __future__ import annotations

import pytest

from ai_billing_audit import zorva_context


# ----- infer_market -----


def test_infer_market_explicit_country_code_wins():
    assert zorva_context.infer_market(country_code="US") == "US"
    assert zorva_context.infer_market(country_code="mx") == "MX"
    assert zorva_context.infer_market(country_code="ca") == "CA"


def test_infer_market_unknown_country_falls_back():
    # Unknown country falls back to payer_id detection or CA default
    assert zorva_context.infer_market(country_code="XX") == "CA"


def test_infer_market_payer_id_canada_prefix():
    for pid in ("OHIP1234", "AHCIP-ON", "MSP-BC", "RAMQ-QUE"):
        assert zorva_context.infer_market(payer_id=pid) == "CA", pid


def test_infer_market_payer_id_us_prefix():
    for pid in ("BCBS-1234", "AETNA-MED", "UHC-COMMERCIAL", "MEDICARE"):
        assert zorva_context.infer_market(payer_id=pid) == "US", pid


def test_infer_market_payer_id_mexico_prefix():
    for pid in ("IMSS-1234", "ISSSTE-FED", "SAT-CFDI"):
        assert zorva_context.infer_market(payer_id=pid) == "MX", pid


def test_infer_market_payer_id_colombia_prefix():
    for pid in ("EPS-SURA", "EPS-SANITAS", "DIAN-FACT"):
        assert zorva_context.infer_market(payer_id=pid) == "CO", pid


def test_infer_market_health_number_heuristic():
    """9-12 digits default to CA (best-effort)."""
    assert zorva_context.infer_market(health_number="1234567890") == "CA"
    assert zorva_context.infer_market(health_number="12345") == "CA"  # too short, default


def test_infer_market_no_info_defaults_to_ca():
    assert zorva_context.infer_market() == "CA"


# ----- build_context_for_encounter -----


def test_context_ca_ontario_has_billing_authority():
    ctx = zorva_context.build_context_for_encounter(
        country_code="CA", province="ON"
    )
    assert ctx["market"] == "CA"
    assert ctx["province"] == "ON"
    assert "OHIP" in ctx["billing_authority"]
    assert ctx["compliance_law"] == "PIPEDA"
    assert ctx["data_residency_required"] is True
    assert ctx["phi_identifiers_required"] is False


def test_context_ca_alberta_has_billing_authority():
    ctx = zorva_context.build_context_for_encounter(
        country_code="CA", province="AB"
    )
    assert "AHCIP" in ctx["billing_authority"]
    assert "SOMB" in ctx["billing_authority"]


def test_context_ca_bc_has_billing_authority():
    ctx = zorva_context.build_context_for_encounter(
        country_code="CA", province="BC"
    )
    assert "MSP" in ctx["billing_authority"]


def test_context_us_has_hipaa_and_safe_harbor():
    ctx = zorva_context.build_context_for_encounter(country_code="US")
    assert ctx["market"] == "US"
    assert ctx["compliance_law"] == "HIPAA"
    assert ctx["ak_safe_harbor_pricing"] is True  # flat-fee SaaS mandate
    assert ctx["phi_identifiers_required"] is True
    # Data residency NOT required in the US (HIPAA doesn't mandate
    # data stay in-country the way PIPEDA does for Canada).
    assert ctx["data_residency_required"] is False


def test_context_mexico_has_cfdi_invoice_format():
    ctx = zorva_context.build_context_for_encounter(country_code="MX")
    assert ctx["market"] == "MX"
    assert ctx["compliance_law"] == "NOM-024 / SAT CFDI"
    assert "CFDI" in ctx["invoice_format"]
    assert ctx["data_residency_required"] is True


def test_context_colombia_has_dian_compliance():
    ctx = zorva_context.build_context_for_encounter(country_code="CO")
    assert ctx["market"] == "CO"
    assert "DIAN" in ctx["compliance_law"]
    assert "Factura" in ctx["invoice_format"] or "DIAN" in ctx["invoice_format"]
    assert ctx["data_residency_required"] is True


def test_context_province_ignored_outside_canada():
    """Province is a CA concept; for US encounters it stays None."""
    ctx = zorva_context.build_context_for_encounter(
        country_code="US", province="ON"  # province is irrelevant in US
    )
    assert ctx["province"] is None


def test_context_province_normalized_uppercase():
    ctx = zorva_context.build_context_for_encounter(
        country_code="CA", province="on"
    )
    assert ctx["province"] == "ON"


def test_context_includes_vision_summary():
    """The long-term-vision paragraph is included for downstream
    UI components (the dashboard's About page, the appeal-letter
    template) but the auditor never sees it."""
    ctx = zorva_context.build_context_for_encounter(country_code="CA")
    assert "revenue recovery" in ctx["long_term_vision"]
    assert "Canada" in ctx["long_term_vision"]
    assert "Mexico" in ctx["long_term_vision"]
    assert "Colombia" in ctx["long_term_vision"]


def test_context_empty_when_unclassifiable():
    """If country_code is None AND no other signals, we still return
    a default CA context (the runner logs a warning separately)."""
    ctx = zorva_context.build_context_for_encounter()
    assert ctx["market"] == "CA"
    assert ctx["province"] is None
    assert ctx["billing_authority"] is None


# ----- appeal_recipient_for -----


def test_appeal_recipient_per_market():
    assert "OHIP" in zorva_context.appeal_recipient_for("CA") or \
           "Provincial" in zorva_context.appeal_recipient_for("CA")
    assert "Payer" in zorva_context.appeal_recipient_for("US")
    assert "IMSS" in zorva_context.appeal_recipient_for("MX")
    assert "EPS" in zorva_context.appeal_recipient_for("CO")


def test_appeal_recipient_unknown_market_defaults_to_payer():
    assert "Payer" in zorva_context.appeal_recipient_for("XX")


# ----- structural integrity -----


def test_markets_contains_all_four_launch_markets():
    assert {"CA", "US", "MX", "CO"}.issubset(set(zorva_context.MARKETS.keys()))


def test_each_market_has_compliance_law():
    for code, profile in zorva_context.MARKETS.items():
        assert profile.get("compliance_law"), f"{code} missing compliance_law"
        # Every market has a name
        assert profile.get("name"), f"{code} missing name"


def test_ca_markets_have_all_provinces():
    """The plan calls out ON/AB/BC explicitly. v1 supports all 13."""
    provinces = zorva_context.MARKETS["CA"]["provinces"]
    for must in ("ON", "AB", "BC"):
        assert must in provinces, f"missing {must} from CA provinces"


def test_supported_markets_tuple_matches_markets_dict():
    assert set(zorva_context.SUPPORTED_MARKETS) == set(zorva_context.MARKETS.keys())