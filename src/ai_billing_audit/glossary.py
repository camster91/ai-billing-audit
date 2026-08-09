"""Glossary terms for /glossary and /glossary/{slug}.

P0 audit fix 2026-07-13: the glossary was a flat list of 20
<details> blocks in templates/glossary.html with no per-term
URLs. The marketing completeness audit recommended per-term
detail pages so the privacy officer / new hire can share a
single link to a single term definition.

This module is the source of truth for the term list. The
glossary.html template iterates over ``list_terms()`` to
render the index; /glossary/{slug} serves the per-term
detail page from ``get_term(slug)``.
"""

from __future__ import annotations

from typing import Any


# Each term: slug, name, short (one-line) name, body, related
# (cross-link slugs). Slugs are URL-safe lowercase.
GLOSSARY: list[dict[str, Any]] = [
    {
        "slug": "ahcip",
        "name": "AHCIP",
        "short": "Alberta Health Care Insurance Plan",
        "body": (
            "The publicly-funded health insurance plan for "
            "Alberta residents, administered by Alberta Health. "
            "Physicians submit claims to AHCIP for the insured "
            "services they provide. Zorva is built around the "
            "AHCIP fee schedule (SOMB)."
        ),
        "related": ["somb", "gr", "pcn"],
    },
    {
        "slug": "awv",
        "name": "AWV",
        "short": "Annual Wellness Visit",
        "body": (
            "A scheduled, once-per-year comprehensive visit "
            "for an established patient. AHCIP SOMB 03.04A. "
            "Common Zorva finding: AWV billed with a same-day "
            "problem-focused visit missing modifier-25 (Zorva "
            "rule AH-MOD-25)."
        ),
        "related": ["ahcip", "modifier-25"],
    },
    {
        "slug": "cmgp",
        "name": "CMGP",
        "short": "Comprehensive Care Management / General Practice",
        "body": (
            "AHCIP GR 3.3 (CMGP Eligibility). A Comprehensive "
            "Care Management / General Practice visit (03.04A) "
            "requires a full history, full physical, and "
            "comprehensive management plan. Common Zorva "
            "finding: a focused visit was documented but a "
            "CMGP code was billed (rule AH-CG-01). The audit "
            "flags this because over-billing a CMGP is a "
            "potential fraud flag for HIA / PIPEDA purposes."
        ),
        "related": ["ahcip", "gr"],
    },
    {
        "slug": "cpt",
        "name": "CPT",
        "short": "Current Procedural Terminology",
        "body": (
            "The US procedural code set maintained by the "
            "AMA. AHCIP uses the SOMB instead; CPT codes are "
            "not part of the AHCIP ruleset. Zorva's sample-"
            "format case studies use CPT to demonstrate the "
            "auditor workflow, but production AHCIP audits "
            "use SOMB fee codes and AHCIP GR references."
        ),
        "related": ["somb", "ahcip"],
    },
    {
        "slug": "em-em",
        "name": "E/M",
        "short": "Evaluation and Management",
        "body": (
            "Office-visit codes. In AHCIP, the 03.xx series "
            "(03.03A focused, 03.04A comprehensive, 03.05A "
            "complex). In US-CPT, the 992xx series (99213 "
            "focused, 99214 moderate, 99215 complex). E/M "
            "billing is the highest-yield audit area because "
            "modifier-25, dx-linkage, and time-based coding "
            "all cluster here."
        ),
        "related": ["ahcip", "cpt"],
    },
    {
        "slug": "fhir",
        "name": "FHIR",
        "short": "Fast Healthcare Interoperability Resources",
        "body": (
            "The HL7 standard for exchanging healthcare data. "
            "Zorva's upload portal accepts FHIR-formatted "
            "claims (JSON or XML) alongside 837P and CSV. FHIR "
            "is the future of EMR integration for Zorva — "
            "Accuro, TELUS PS Suite, and OSCAR Pro all "
            "support FHIR exports."
        ),
        "related": ["837p"],
    },
    {
        "slug": "gr",
        "name": "GR",
        "short": "General Rule (AHCIP GR)",
        "body": (
            "A general rule published in the AHCIP Schedule "
            "of Medical Benefits. GRs govern eligibility, "
            "documentation requirements, modifier use, and "
            "modifier-25 application. Zorva's 18 AHCIP rules "
            "cite GR 1.4 (modifier-25), GR 3.3 (CMGP), GR 4.4 "
            "(dx-linkage), GR 6.2 (referral documentation), "
            "and others."
        ),
        "related": ["ahcip", "somb", "cmgp"],
    },
    {
        "slug": "hia",
        "name": "HIA",
        "short": "Alberta Health Information Act",
        "body": (
            "Alberta's health-information privacy law. "
            "Governs how custodians (clinics) and information "
            "managers (Zorva) handle personally-identifying "
            "health information. The HIA requires an "
            "Information Manager Agreement (IMA) between the "
            "custodian and the information manager before any "
            "PHI moves. Zorva's IMA template is in lawyer "
            "review (target sign-off 2026-Q3)."
        ),
        "related": ["ima", "phipa", "hipaa"],
    },
    {
        "slug": "hipaa",
        "name": "HIPAA",
        "short": "Health Insurance Portability and Accountability Act",
        "body": (
            "The US federal health-privacy law. Zorva is "
            "Alberta-first and signs HIA IMAs; HIPAA BAA "
            "templates are available for US pilots. The "
            "patient-hash design, audit-trail chain, and "
            "encryption-at-rest posture satisfy both HIA and "
            "HIPAA security rule requirements."
        ),
        "related": ["hia", "phipa"],
    },
    {
        "slug": "h-link",
        "name": "H-Link",
        "short": "Alberta Health's electronic claims system",
        "body": (
            "The Alberta Health claims-submission system. "
            "Physicians and clinics submit AHCIP claims via "
            "H-Link. Zorva's audit output is the biller's "
            "review pass BEFORE the claim hits H-Link — we "
            "don't replace H-Link, we pre-flight the claim."
        ),
        "related": ["ahcip", "837p"],
    },
    {
        "slug": "hmv",
        "name": "HMV",
        "short": "Health Maintenance Visit",
        "body": (
            "A scheduled preventive visit for an established "
            "patient. Like AWV, common Zorva finding: same-day "
            "problem-focused E/M billed with HMV missing "
            "modifier-25 (rule AH-MOD-25)."
        ),
        "related": ["awv", "em-em"],
    },
    {
        "slug": "ima",
        "name": "IMA",
        "short": "Information Manager Agreement",
        "body": (
            "The HIA-required contract between a custodian (a "
            "clinic) and an information manager (Zorva). Sets "
            "out what Zorva can and can't do with the data. "
            "Zorva's IMA template is in lawyer review (target "
            "sign-off 2026-Q3). The IMA must be signed BEFORE "
            "any PHI moves to Zorva's environment."
        ),
        "related": ["hia"],
    },
    {
        "slug": "llm",
        "name": "LLM",
        "short": "Large Language Model",
        "body": (
            "The AI class of model that Zorva uses for the "
            "audit. Brought in by the customer — Zorva ships "
            "the prompt, the rules, the audit trail. Your "
            "data does not train anyone else's model. The "
            "MiniMax-M3 model with date-pinned snapshot is "
            "the default; OpenAI, Anthropic, Gemini, or any "
            "Ollama-compatible local endpoint is supported."
        ),
        "related": [],
    },
    {
        "slug": "modifier-25",
        "name": "Modifier-25",
        "short": "Unbundled E/M on the Same Day as a Procedure",
        "body": (
            "AHCIP GR 1.4. When a same-day E/M is billed "
            "alongside a procedure (e.g. office visit + joint "
            "injection, or office visit + chest X-ray), the "
            "E/M must carry modifier-25 to indicate it is a "
            "separately-identifiable service. Without "
            "modifier-25, AHCIP bundles the E/M into the "
            "procedure and pays only the procedure. Zorva's "
            "rule AH-MOD-25 is the highest-yield catch — "
            "modifier-25 gaps are the most common denial "
            "pattern in Alberta family-medicine claims."
        ),
        "related": ["gr", "ahcip", "em-em"],
    },
    {
        "slug": "mue",
        "name": "MUE",
        "short": "Medically Unlikely Edit",
        "body": (
            "A payer rule that caps the number of units of a "
            "procedure that can be billed in a day. Zorva "
            "flags when a claim's units exceed the MUE limit. "
            "MUE is more relevant to US-CPT claims; AHCIP "
            "uses SOMB-defined unit limits instead."
        ),
        "related": ["cpt"],
    },
    {
        "slug": "ncci",
        "name": "NCCI",
        "short": "National Correct Coding Initiative",
        "body": (
            "A US-based code-pair edit system. Less directly "
            "relevant to AHCIP (which has its own equivalent "
            "in the SOMB) but Zorva's NCCI coverage is wired "
            "in for US pilots."
        ),
        "related": ["cpt", "mue"],
    },
    {
        "slug": "pcn",
        "name": "PCN",
        "short": "Primary Care Network",
        "body": (
            "Alberta-specific organizational structure that "
            "coordinates billing, panel management, and "
            "after-hours coverage across member clinics. ~42 "
            "PCNs province-wide. The PCN central office is "
            "often the right first call for Zorva outreach — "
            "centralized billing-quality programs at PCN "
            "scale benefit most from a pre-submit auditor."
        ),
        "related": ["ahcip"],
    },
    {
        "slug": "phipa",
        "name": "PHIPA",
        "short": "Personal Health Information Protection Act (Ontario)",
        "body": (
            "Ontario's health-privacy law. Distinct from HIA "
            "in that PHIPA uses 'Health Information Custodian' "
            "and 'agent' terminology; HIA uses 'custodian' "
            "and 'information manager.' Zorva is Alberta-"
            "first; PHIPA templates are on request for "
            "Ontario pilots."
        ),
        "related": ["hia", "hipaa"],
    },
    {
        "slug": "pipeda",
        "name": "PIPEDA",
        "short": "Personal Information Protection and Electronic Documents Act",
        "body": (
            "Canada's federal private-sector privacy law. "
            "Zorva covers PIPEDA in addition to HIA / PHIPA / "
            "HIPAA depending on jurisdiction. The "
            "patient_hash salt design follows PIPEDA's "
            "'de-identify at the earliest practical point' "
            "requirement."
        ),
        "related": ["hia", "phipa", "hipaa"],
    },
    {
        "slug": "somb",
        "name": "SOMB",
        "short": "Schedule of Medical Benefits",
        "body": (
            "Alberta's billing code reference. The 18 AHCIP "
            "rules in v12 cite SOMB rule numbers and GR "
            "references. The SOMB is the source of truth for "
            "what AHCIP will and won't pay. Updated quarterly "
            "by Alberta Health; Zorva's ruleset is versioned "
            "to each SOMB release."
        ),
        "related": ["ahcip", "gr"],
    },
    {
        "slug": "sftp",
        "name": "SFTP",
        "short": "SSH File Transfer Protocol",
        "body": (
            "The Zorva pilot accepts 837P / CSV / paste-form. "
            "For clinics that prefer file drop, SFTP upload "
            "is available. Zorva does not require SFTP for "
            "the pilot — the contact form and the upload "
            "portal both accept direct file upload."
        ),
        "related": ["837p"],
    },
    {
        "slug": "837p",
        "name": "837P",
        "short": "Professional 837P claim format",
        "body": (
            "The standard electronic claim format for "
            "professional services. 837P is the most common "
            "Zorva input. The Zorva auditor reads the "
            "encounter header (NM1*85, NM1*87, HI, DTP*472) "
            "and the service lines (LX, SV1). .edi, .837, "
            "and .txt are all accepted filename extensions."
        ),
        "related": ["fhir"],
    },
]


def list_terms() -> list[dict[str, Any]]:
    """Return all terms, alphabetized by name."""
    return sorted(GLOSSARY, key=lambda t: t["name"].lower())


def get_term(slug: str) -> dict[str, Any] | None:
    """Look up a single term by slug."""
    for t in GLOSSARY:
        if t["slug"] == slug:
            return t
    return None


def get_terms_by_slugs(slugs: list[str]) -> list[dict[str, Any]]:
    """Resolve a list of slugs to term dicts (for the 'related' links)."""
    by_slug = {t["slug"]: t for t in GLOSSARY}
    out: list[dict[str, Any]] = []
    for s in slugs:
        if s in by_slug:
            out.append(by_slug[s])
    return out
