"""The pilot offer is decided, and every live surface must agree.

The offer was recorded on 2026-09-20 (issues #76/#108): a **60-day paid
pilot at CAD $1,500 one-time**, credited against the first month if the
clinic continues, with no automatic conversion. Before that decision four
in-repo documents asserted four different offers — 60 days free with no
contract (`docs/PILOT_OFFER.md`), 60 days free then $499/mo (the pricing
page), 30 days free (the prospect list), and free of charge
(`docs/DATA_AGREEMENT_TEMPLATE.md`). Two of them were live customer-facing
surfaces.

This pins the decided terms against the surfaces a clinic or a member of the
sales team would actually read, so the contradiction cannot quietly return.
Historical snapshots (`research/`, `audits/`, `changelogs/`, dated
`daily_report_*`, and the changelog) are deliberately **not** scanned — they
record what was believed at the time and are not rewritten.

A separate, deliberately free offer exists: a 100-claim de-identified sample
report used for first contact. It is not the pilot, and this test must not
be read as forbidding it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Surfaces a customer, prospect, or sales team member actually reads.
LIVE_SURFACES = [
    "README.md",
    "docs/PILOT_OFFER.md",
    "docs/ONE_PAGER_WHAT_WE_DO.md",
    "docs/DATA_AGREEMENT_TEMPLATE.md",
    "docs/legal/HIA-DPA-TEMPLATE.md",
    "docs/ALBERTA_PROSPECT_LIST.md",
    "docs/gtm/STRATHCONA-PCN-PITCH.md",
    "docs/press/PRESS-KIT.md",
    "docs/EXHIBITOR_KIT.md",
    "docs/QUICKSTART.md",
    "apps/portal/src/app/pricing/page.tsx",
    "apps/portal/src/app/pilot/page.tsx",
    "apps/portal/src/app/for/family-medicine/page.tsx",
    "templates/email/alberta_clinic_v1.txt",
    "templates/email/alberta_pcn_v1.txt",
    "templates/email/cold_outreach_v1.txt",
    "templates/email/cold_outreach_v2.txt",
    "templates/email/cold_followup_v1.txt",
    "templates/email/HANDOFF.md",
    "qa-bundle/01-cold-email-red-deer-pcn.txt",
]

# Phrases that describe the pilot as free. The pilot is paid; the free
# 100-claim sample report is a different thing and does not use these.
FREE_PILOT_PHRASES = [
    "no-cost pilot",
    "free pilot",
    "free 30-day pilot",
    "free 60-day pilot",
    "30-day free",
    "60-day free",
    "pilot remains free",
    "free of charge",
]

# Claims of a completed customer engagement. The investor one-pager records
# 0 clinics in pilot as of 2026-07-01, so no live asset may assert otherwise.
FABRICATED_CUSTOMER_PHRASES = [
    "we just finished",
    "we've been working with",
    "in the ontario pilot",
]


def _flatten(text: str) -> str:
    """Lowercase and collapse whitespace so line wrapping can't hide a phrase."""
    return " ".join(text.casefold().split())


@pytest.mark.parametrize("rel", LIVE_SURFACES)
def test_live_surface_does_not_describe_a_free_pilot(rel: str) -> None:
    path = ROOT / rel
    assert path.is_file(), f"live surface listed here no longer exists: {rel}"
    flat = _flatten(path.read_text(encoding="utf-8"))
    for phrase in FREE_PILOT_PHRASES:
        assert _flatten(phrase) not in flat, (
            f"{rel} still describes a free pilot: {phrase!r}"
        )


@pytest.mark.parametrize("rel", LIVE_SURFACES)
def test_live_surface_does_not_claim_a_completed_pilot(rel: str) -> None:
    """No live asset may assert a customer engagement that did not happen."""
    flat = _flatten((ROOT / rel).read_text(encoding="utf-8"))
    for phrase in FABRICATED_CUSTOMER_PHRASES:
        assert _flatten(phrase) not in flat, (
            f"{rel} claims a customer result: {phrase!r}"
        )


def test_canonical_offer_states_the_decided_terms() -> None:
    """`docs/PILOT_OFFER.md` is the source of truth; pin the decided numbers."""
    flat = _flatten((ROOT / "docs/PILOT_OFFER.md").read_text(encoding="utf-8"))
    assert "1,500" in flat, "the pilot fee is missing from the canonical offer"
    assert "60-day" in flat, "the pilot duration is missing from the canonical offer"
    assert "credited against" in flat, "the credit terms are missing"
    assert "no automatic conversion" in flat, "the no-auto-conversion term is missing"


def test_the_free_sample_report_is_still_offered() -> None:
    """The decided offer keeps a free first-touch diagnostic.

    Guards against 'fix the price' being over-applied: the free 100-claim
    sample report is intentional and must survive.
    """
    flat = _flatten((ROOT / "docs/PILOT_OFFER.md").read_text(encoding="utf-8"))
    assert "sample report" in flat and "de-identified" in flat


def test_pricing_page_cta_matches_the_decided_offer() -> None:
    src = (ROOT / "apps/portal/src/app/pricing/page.tsx").read_text(encoding="utf-8")
    assert "1,500" in src, "the pricing-page CTA does not mention the pilot fee"
