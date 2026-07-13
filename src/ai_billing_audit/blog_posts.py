"""Full blog post bodies for the marketing site.

The metadata (id, title, published, summary) is also stored
in :mod:`ai_billing_audit.feeds` as ``BLOG_POSTS`` so the
RSS / Atom feed has the same source of truth. The bodies
live here because they're larger and only needed when a
prospect actually opens the per-post page.

To add a post:
  1. Append a new dict to ``BLOG_POSTS`` in feeds.py with
     id, title, published, summary, url_path.
  2. Add the matching entry here with the same id and the
     full body.
  3. Reference the slug in templates/blog.html and the
     sitemap (feeds.PUBLIC_MARKETING_PATHS).
"""
from __future__ import annotations

import datetime
from typing import Any


def _blog_body_why_we_built_zorva() -> str:
    return (
        "<p>Most AHCIP billing software falls into one of two categories. "
        "The first is a managed submission service — a human or vendor "
        "who takes your claims, scrubs them, and pushes them to Alberta "
        "Health. The second is an EMR billing module — a checkbox on the "
        "encounter screen that drops a fee code on the claim.</p>"
        "<p>Neither of them reads the clinical note against the AHCIP "
        "fee schedule. Neither of them asks: <em>given what the doctor "
        "actually documented, is the code on the claim the code that "
        "should be on the claim</em>?</p>"
        "<p>We built one that does.</p>"
        "<h2>The problem we kept seeing</h2>"
        "<p>In 2025 we ran shadow audits on 19 encounters pulled from a "
        "working Alberta family-medicine practice. Every claim was a "
        "real AHCIP submission with real fee codes and a real clinical "
        "note. We asked an LLM auditor: <em>is this claim correctly "
        "billed?</em></p>"
        "<p>Across those 19 encounters, the auditor found 23 findings the "
        "biller had missed. Eleven of those findings translated to "
        "missed revenue — underbilled modifiers, missed add-on codes, "
        "shadow-billed services where the work was documented but the "
        "code wasn't on the claim. The remaining 12 were denial-risk "
        "signals — the kind of pattern that gets a claim kicked back on "
        "first submission and burns biller hours on appeal.</p>"
        "<p>None of those 23 findings were caught by the EMR. None of "
        "them were caught by the submission service. The doctor had "
        "documented the work; the biller had submitted the claim; the "
        "revenue had quietly leaked out the door.</p>"
        "<h2>Why a decision-support tool, not a submission service</h2>"
        "<p>We could have built a managed billing service. The economics "
        "are attractive: clinics outsource, we capture a percentage of "
        "recovered revenue, and the business compounds with every new "
        "clinic signed. But that model has a fundamental conflict of "
        "interest — the more denials the clinic sees, the more appeals "
        "we bill for. We make more money when the clinic is worse off.</p>"
        "<p>A decision-support tool inverts the economics. We charge a "
        "flat monthly fee. Your recovery rate is yours. We get paid the "
        "same amount whether Zorva finds 100 errors or 1,000 — so the "
        "incentive to under-audit is gone.</p>"
        "<h2>Why we don't proxy the LLM call</h2>"
        "<p>Other AHCIP tools route your claim data through the vendor's "
        "OpenAI key. That means the vendor's account sees your patient "
        "data, your provider numbers, and your billing patterns. We "
        "think that's a non-starter for healthcare.</p>"
        "<p>Zorva is LLM-agnostic. You bring your own API key — OpenAI, "
        "Anthropic, Gemini, or any Ollama-compatible local endpoint. "
        "The auditor runs against your provider, in your tenant, and "
        "your claims never touch our LLM account.</p>"
        "<h2>What's next</h2>"
        "<p>We're running a 60-day no-cost pilot with two Alberta "
        "family-medicine clinics. After the pilot, the clinic either "
        "moves to a paid tier or the data is purged. The full pilot "
        "terms are at <a href=\"/pilot\">/pilot</a>.</p>"
        "<p>If you want to see what Zorva catches on your own claims, "
        "<a href=\"/contact\">send 100 de-identified claims</a>. We'll "
        "run the auditor and send back a 1-page finding-by-finding "
        "report. No fee, no follow-up unless the report is useful.</p>"
    )


def _blog_body_18_ahcip_rules() -> str:
    return (
        "<p>v12 of the Zorva prompt ships with 18 AHCIP rules covering "
        "the highest-yield patterns Alberta billers see on every claim. "
        "Here's the list, grouped by severity, with the rule code and a "
        "one-line description of what it catches.</p>"
        "<h2>High-severity (10 rules)</h2>"
        "<ul>"
        "<li><strong>AH-MOD-25</strong> — Modifier-25 misapplication: an "
        "E/M code billed with a procedure on the same day without "
        "documentation of a separately identifiable service.</li>"
        "<li><strong>AH-TELE-01</strong> — Telehealth consent missing "
        "or expired (HIA Schedule 1 requirement).</li>"
        "<li><strong>AH-CG-01</strong> — Comprehensive/General "
        "Assessment (CMGP) billed when the documentation only supports "
        "a focused visit.</li>"
        "<li><strong>AH-DX-01</strong> — Diagnosis code does not support "
        "the billed fee code (AHCIP GR 4.4).</li>"
        "<li><strong>AH-NPI-01</strong> — Referring practitioner NPI "
        "missing or invalid on a referral-required service.</li>"
        "<li><strong>AH-INS-01</strong> — Service billed to AHCIP for a "
        "non-insured service (e.g. third-party request, cosmetic).</li>"
        "<li><strong>AH-LAB-01</strong> — Lab code billed without "
        "documentation of the test being performed.</li>"
        "<li><strong>AH-TIME-01</strong> — Time-based code billed "
        "without the required start/stop time documentation.</li>"
        "<li><strong>AH-REF-01</strong> — Service requiring a referral "
        "submitted without an attached referral letter.</li>"
        "<li><strong>AH-PHIA-01</strong> — Clinical note contains a "
        "patient identifier that hasn't been de-identified per the "
        "HIA Information Manager Agreement.</li>"
        "</ul>"
        "<h2>Medium-severity (5 rules)</h2>"
        "<ul>"
        "<li><strong>AH-ADDON-01</strong> — Add-on code eligible based "
        "on the primary code but missing from the claim.</li>"
        "<li><strong>AH-AFTER-01</strong> — After-hours premium "
        "documented but not on the claim.</li>"
        "<li><strong>AH-PRV-01</strong> — Service billed under the "
        "wrong practitioner (specialty mismatch).</li>"
        "<li><strong>AH-CONS-01</strong> — Consultation code (03.xx) "
        "billed but the referral pattern doesn't support a consult.</li>"
        "<li><strong>AH-FUP-01</strong> — Follow-up visit within the "
        "AHCIP-stamped window, billed as a new visit.</li>"
        "</ul>"
        "<h2>Low-severity (3 rules)</h2>"
        "<ul>"
        "<li><strong>AH-COPY-01</strong> — Duplicate claim submission "
        "(same patient, same service, same day).</li>"
        "<li><strong>AH-MOD-01</strong> — Modifier present but not "
        "supported by the documentation (informational).</li>"
        "<li><strong>AH-PRG-01</strong> — Procedure code maps to a "
        "deprecated AHCIP GR; the modern equivalent should be used.</li>"
        "</ul>"
        "<h2>What's deliberately not in v12</h2>"
        "<p>We don't catch <em>everything</em>. The 18 rules above are "
        "the ones that, across the 19-encounter shadow audit, had the "
        "highest yield (most revenue recovered) and the lowest false-"
        "positive rate. The full long-tail — uncommon modifiers, "
        "specialty-specific GR nuances, regional pilot codes — is on "
        "the v13 and v14 roadmap.</p>"
        "<p>If a rule you need isn't on this list, the request goes to "
        "the same kanban board the rest of the rule backlog lives on. "
        "We tune the prompt quarterly with pilot clinics.</p>"
    )


def _blog_body_why_flat_fee() -> str:
    return (
        "<p>Per-claim pricing punishes the clinics that need the most "
        "help. The clinics with the highest denial rates, the most "
        "complex patient panels, the oldest EMR data — those clinics "
        "submit the most claims, and a per-claim model charges them "
        "the most.</p>"
        "<p>That's the opposite of what we want. We want a model that "
        "rewards the clinic that uses us most aggressively — because "
        "that's the clinic where Zorva finds the most missed revenue.</p>"
        "<h2>The economics of per-claim</h2>"
        "<p>A per-claim model says: <em>we make X cents on every claim "
        "the auditor runs on</em>. The vendor's revenue is linearly "
        "tied to claim volume. The vendor's incentive is to push the "
        "clinic toward higher claim volume — even if that means "
        "running the auditor on claims the clinic already knows are "
        "clean.</p>"
        "<p>Or worse: the vendor's incentive is to silently drop "
        "claims that the auditor would have flagged, because every "
        "false-positive the biller dismisses is one less claim the "
        "vendor has to pay the LLM provider for.</p>"
        "<h2>Why flat-fee aligns the incentives</h2>"
        "<p>A flat monthly fee says: <em>we make the same amount whether "
        "Zorva runs 100 audits or 10,000</em>. The vendor's revenue is "
        "decoupled from claim volume. The vendor's incentive is to make "
        "the biller happy — because the biller is the one who decides "
        "whether to renew next month.</p>"
        "<p>This means we want the auditor to find real errors, not to "
        "look busy. If Zorva surfaces 100 false positives in a month, "
        "the biller churns. If Zorva surfaces 30 high-confidence "
        "findings, the biller renews and tells her peers.</p>"
        "<h2>How the tiers work</h2>"
        "<p>Three tiers, bracketed by encounter-audit volume:</p>"
        "<ul>"
        "<li><strong>Solo ($499/mo)</strong> — up to 1,000 encounter "
        "audits per month.</li>"
        "<li><strong>Practice ($1,499/mo)</strong> — up to 3,000 "
        "encounter audits per month.</li>"
        "<li><strong>Network ($2,999+/mo)</strong> — 3,000+ encounter "
        "audits per month, custom volume.</li>"
        "</ul>"
        "<p>We don't auto-upgrade you. If you hit 1,200 audits on the "
        "Solo tier, we reach out <em>before</em> the overage to talk "
        "about the upgrade. We don't bill the overage automatically.</p>"
        "<h2>What's not in the tiers</h2>"
        "<p>No per-claim charge. No percentage of recovered revenue. No "
        "recovery-linked fee. No setup fee. No minimum commitment "
        "longer than one month. You can cancel any time with 30 days' "
        "notice and export your data via the audit-trail chain.</p>"
        "<p>For US clinics, the same model is AKS safe-harbor-aligned — "
        "the per-claim or percentage-of-recovery model would be a "
        "Stark/AKS risk for any US-based practice.</p>"
    )


def _blog_body_why_alberta_first() -> str:
    return (
        "<p>Zorva started as an Ontario-pivot idea. We had OHIP fee "
        "schedules memorized, an Ontario PCN analog (the FHT) on the "
        "shortlist, and a half-built prompt tuned for OHIP-specific "
        "modifier rules.</p>"
        "<p>Then we looked at the Alberta AHCIP fee schedule, talked to "
        "six Alberta billers, and realized the entire competitive "
        "landscape was different.</p>"
        "<h2>What we heard from Alberta billers</h2>"
        "<p>Across the six biller interviews (March-May 2026), the "
        "common threads were:</p>"
        "<ul>"
        "<li><strong>The denial-rate ceiling is real.</strong> Alberta "
        "billers described denial rates between 4% and 12%, with the "
        "median around 7.5%. Most of the denials are not random — "
        "they cluster around specific patterns (modifier-25, "
        "telehealth consent, dx-linkage, CMGP-vs-focused-visit).</li>"
        "<li><strong>The submission-service options are weak.</strong> "
        "Three of the six billers had tried managed submission in the "
        "past two years and reverted to in-house. The reasons were "
        "consistent: cost (12-18% of recovered revenue is too much), "
        "loss of control (the service didn't escalate the way the "
        "clinic wanted), and audit-defensibility (the clinic couldn't "
        "verify the service's work after the fact).</li>"
        "<li><strong>EMR billing modules are not the answer.</strong> "
        "Telus PS Suite, OSCAR, Accuro, and Med Access all have "
        "billing modules, but the billers described them as \"a "
        "checkbox on the encounter screen\" — not a tool that reads "
        "the clinical note. The biller is still the one catching the "
        "modifier-25 misses and the dx-linkage errors.</li>"
        "</ul>"
        "<h2>Why Alberta specifically</h2>"
        "<p>Three reasons:</p>"
        "<ol>"
        "<li><strong>The fee schedule is well-defined and versioned.</strong> "
        "Alberta Health publishes the SOMB (Schedule of Medical "
        "Benefits) on a quarterly cadence with a clear changelog. The "
        "ruleset Zorva builds against has a stable, citable source.</li>"
        "<li><strong>The HIA framework is the gold standard.</strong> "
        "Alberta's Health Information Act is one of the strongest "
        "privacy frameworks in North America. The HIA Information "
        "Manager Agreement (IMA) template that Zorva signs with "
        "Alberta clinics is the same one used by Alberta Health "
        "Services. For clinics that already operate under HIA, the "
        "compliance path is short.</li>"
        "<li><strong>PCN density is high.</strong> Alberta's Primary "
        "Care Networks cover most family physicians in the province. "
        "The PCN central-office admin is the buyer for many clinics, "
        "and PCNs already run centralized billing-quality programs. "
        "Zorva slots into an existing program structure rather than "
        "asking the clinic to build a new one.</li>"
        "</ol>"
        "<h2>What about OHIP and MSP?</h2>"
        "<p>Ontario (OHIP) and British Columbia (MSP) are on the 2027 "
        "roadmap. The prompt architecture is jurisdiction-agnostic — "
        "the ruleset is the only thing that changes between AHCIP, "
        "OHIP, and MSP. We're building the v12 ruleset for AHCIP "
        "first, and the OHIP/MSP rulesets will be forks once the v12 "
        "AHCIP prompt is in production.</p>"
        "<h2>What this means for you</h2>"
        "<p>If you're an Alberta clinic or PCN, Zorva is built for you. "
        "If you're in Ontario or BC and want to be on the early-access "
        "list for the OHIP/MSP rulesets, send a note via "
        "<a href=\"/contact\">/contact</a> and we'll add you.</p>"
    )


BLOG_POSTS_DETAIL: dict[str, dict[str, Any]] = {
    "why-we-built-zorva": {
        "id": "why-we-built-zorva",
        "title": "Why we built Zorva (and not a billing service)",
        "published": datetime.datetime(2026, 7, 13, 9, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "Most AHCIP billing software falls into one of two "
            "categories: a managed submission service, or an EMR "
            "billing module. Neither of them reads the clinical "
            "note against the AHCIP fee schedule. We built one that does."
        ),
        "author": "Cameron Ashley",
        "tags": ["about", "AHCIP"],
        "body_html": _blog_body_why_we_built_zorva(),
    },
    "18-ahcip-rules": {
        "id": "18-ahcip-rules",
        "title": "The 18 AHCIP rules in v12",
        "published": datetime.datetime(2026, 7, 8, 9, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "v12 of the Zorva prompt ships with 18 AHCIP rules "
            "covering the highest-yield patterns Alberta billers see "
            "on every claim."
        ),
        "author": "Cameron Ashley",
        "tags": ["AHCIP", "rules"],
        "body_html": _blog_body_18_ahcip_rules(),
    },
    "why-flat-fee": {
        "id": "why-flat-fee",
        "title": "Why we charge flat-fee, not per-claim",
        "published": datetime.datetime(2026, 7, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "Per-claim pricing punishes the clinics that need the "
            "most help. We picked flat-fee because the alternative "
            "rewards us for not running the auditor on the trickiest claims."
        ),
        "author": "Cameron Ashley",
        "tags": ["pricing"],
        "body_html": _blog_body_why_flat_fee(),
    },
    "why-alberta-first": {
        "id": "why-alberta-first",
        "title": "Why Alberta first",
        "published": datetime.datetime(2026, 6, 22, 9, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "Zorva started as an Ontario-pivot idea. Then we looked "
            "at the Alberta AHCIP fee schedule, talked to six "
            "Alberta billers, and realized the entire competitive "
            "landscape was different."
        ),
        "author": "Cameron Ashley",
        "tags": ["go-to-market"],
        "body_html": _blog_body_why_alberta_first(),
    },
}


def list_posts() -> list[dict[str, Any]]:
    """Return posts sorted newest-first with their full body."""
    return sorted(
        BLOG_POSTS_DETAIL.values(),
        key=lambda p: p["published"],
        reverse=True,
    )


def get_post(slug: str) -> dict[str, Any] | None:
    """Return one post by slug, or None if not found."""
    return BLOG_POSTS_DETAIL.get(slug)
