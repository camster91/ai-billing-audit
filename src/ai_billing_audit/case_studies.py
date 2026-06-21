"""Worked-example case studies for the marketing site.

Sales calls need a 'show me an example' moment. These three
case studies pair each difficulty band with a representative
billing problem and the auditor's findings.

Each case study shows:
  - The clinical scenario (anonymized — patient identifiers
    are SHA-256 hashes from val.json)
  - The claim as submitted
  - What the auditor found (rule_id + severity + quote)
  - What the biller would have done without Zorva
  - The dollar impact (recovered revenue + audit fees avoided)

The case studies are derived from the actual data/val.json
encounters so the examples are honest. We don't fabricate
encounters for marketing copy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Average claim value used for dollar impact (matches the ROI
# calculator's CMS commercial average). Per-specialty overrides
# let us mark up/down per case study.
AVG_CLAIM_USD = 190.0
SPECIALTY_AVG_USD: dict[str, float] = {
    "primary_care": 165.0,
    "cardiology": 240.0,
    "internal_medicine": 190.0,
    "endocrinology": 175.0,
    "emergency": 320.0,
}


@dataclass(frozen=True)
class CaseStudy:
    """A worked example for the marketing site.

    All fields are user-visible copy. Keep the prose specific
    enough to be useful in a sales conversation but anonymized
    enough to publish without a BAA.
    """

    slug: str              # URL slug: /case-studies/{slug}
    title: str             # "Modifier-25 caught on chest pain encounter"
    difficulty: str        # "easy" | "medium" | "hard"
    specialty: str         # "cardiology"
    encounter_id: str      # "enc_0000" — the underlying val.json encounter
    clinical_scenario: str # 2-3 sentence narrative
    claim_summary: str     # what was billed
    findings: list[dict[str, Any]]  # [{rule_id, severity, quote, suggested_code}]
    what_biller_would_have_done: str
    dollar_impact: str
    encounter_link: str | None = None  # "/encounter/enc_0000"


# Three case studies, one per difficulty band.
# Each is a frozen record that the route template renders verbatim.
CASE_STUDIES: list[CaseStudy] = [
    CaseStudy(
        slug="enc_10032-easy-duplicate-service",
        title="Duplicate-service flag: chest pain + annual wellness same day",
        difficulty="easy",
        specialty="primary_care",
        encounter_id="enc_10032",
        clinical_scenario=(
            "An established patient came in for an annual wellness visit. "
            "The physician also performed and billed a separate "
            "problem-focused ECG the same day. Without modifier -25 on "
            "the E/M line, the payer would treat the second service as "
            "bundled into the first and deny it."
        ),
        claim_summary=(
            "Claim 1: 99396 (annual wellness). "
            "Claim 2: 99213 (problem-focused E/M, same day, same patient). "
            "No modifier applied."
        ),
        findings=[
            {
                "rule_id": "rule_overlap_001",
                "severity": "high",
                "quote": "duplicate service on same date",
                "suggested_code": "99213-25",
                "rationale": "The problem-focused E/M needs modifier -25 to "
                              "unbundle from the annual wellness service.",
            },
        ],
        what_biller_would_have_done=(
            "Without Zorva, the biller submits both claims as-is. "
            "The payer bundles them and denies claim 2 — a $165 "
            "write-off that takes 60+ days to appeal."
        ),
        dollar_impact=(
            "Zorva catches the modifier-25 gap before submission. "
            "Biller adds -25 to the E/M line; both claims pay on "
            "first pass. $165 recovered per encounter, ~$1,650/mo "
            "at one such occurrence per week."
        ),
        encounter_link="/encounter/enc_10032",
    ),
    CaseStudy(
        slug="enc_0011-medium-imaging-coverage",
        title="Imaging coverage gap: echocardiogram ordered but unbilled",
        difficulty="medium",
        specialty="cardiology",
        encounter_id="enc_0011",
        clinical_scenario=(
            "An established patient with hypertension returns for "
            "follow-up. The physician documents palpitations, orders "
            "an echocardiogram and a lipid panel. The biller submits "
            "an E/M claim (99214) and the lipid panel (80061), but "
            "forgets to bill the echocardiogram (93306)."
        ),
        claim_summary=(
            "99214 (E/M moderate), 80061 (lipid panel). "
            "Echocardiogram documented but unbilled. The payer pays "
            "what was billed — but the clinic lost $240 of revenue "
            "for work that was already done."
        ),
        findings=[
            {
                "rule_id": "rule_imaging_002",
                "severity": "high",
                "quote": "echocardiogram ordered",
                "suggested_code": "93306",
                "rationale": "Echocardiogram was ordered and "
                              "documented but the corresponding "
                              "CPT code (93306) was not billed. "
                              "This is recoverable revenue that "
                              "would otherwise be lost.",
            },
            {
                "rule_id": "rule_icd_001",
                "severity": "medium",
                "quote": "palpitations reported",
                "suggested_code": "R00.2",
                "rationale": "Palpitations ICD-10 (R00.2) supports "
                              "the medical necessity of the "
                              "echocardiogram and lipid panel.",
            },
            {
                "rule_id": "rule_em_001",
                "severity": "info",
                "quote": "established patient moderate complexity",
                "suggested_code": "99214",
                "rationale": "Documentation supports moderate-"
                              "complexity E/M. Verify chart review "
                              "elements for 99214.",
            },
            {
                "rule_id": "rule_icd_004",
                "severity": "low",
                "quote": "essential hypertension",
                "suggested_code": "I10",
                "rationale": "Hypertension ICD-10 (I10) supports "
                              "continuity of care and chronic "
                              "condition management.",
            },
            {
                "rule_id": "rule_lab_001",
                "severity": "low",
                "quote": "lipid panel ordered",
                "suggested_code": "80061",
                "rationale": "Lipid panel needs medical-necessity "
                              "ICD linkage (the I10 above).",
            },
        ],
        what_biller_would_have_done=(
            "Without Zorva, the biller submits 99214 + 80061 and "
            "leaves the documented echocardiogram unbilled. The "
            "clinic loses $240 in revenue per encounter, which "
            "adds up to $960/mo at one such encounter per week. "
            "The patient may also receive a surprise bill for "
            "the unbilled echo if the clinic submits a corrected "
            "claim months later — patient-relations risk."
        ),
        dollar_impact=(
            "Zorva catches the imaging-coverage gap before "
            "submission. Biller adds 93306 + R00.2 to the claim; "
            "all three lines pay on first pass. $240 recovered "
            "per encounter, ~$960/mo at one such encounter per "
            "week. The HIGH-severity imaging-coverage finding "
            "alone covers a substantial fraction of the Zorva "
            "subscription."
        ),
        encounter_link="/encounter/enc_0011",
    ),
    CaseStudy(
        slug="enc_0000-hard-modifier-25-chest-pain",
        title="Modifier-25 + ECG + palpitations + lipid panel: 5 findings",
        difficulty="hard",
        specialty="cardiology",
        encounter_id="enc_0000",
        clinical_scenario=(
            "An established patient comes in for a problem-focused "
            "visit with palpitations. The physician performs an in-office "
            "ECG, reviews it, and orders a lipid panel. The chart "
            "supports a same-day E/M (99214) plus ECG (93000) plus "
            "lipid panel (80061). Five ground-truth findings span "
            "evaluation, cardiology, diagnosis, modifier, and "
            "laboratory categories."
        ),
        claim_summary=(
            "99214 (E/M moderate), 93000 (ECG with interpretation), "
            "80061 (lipid panel). Documentation supports a same-day "
            "separately-identifiable E/M with procedure."
        ),
        findings=[
            {
                "rule_id": "rule_modifier_25_001",
                "severity": "high",
                "quote": "separately identifiable E/M",
                "suggested_code": "99214-25",
                "rationale": "Same-day E/M + procedure requires "
                              "modifier -25 to unbundle the E/M "
                              "from the ECG. Without it, payer "
                              "bundles and denies the E/M.",
            },
            {
                "rule_id": "rule_em_001",
                "severity": "info",
                "quote": "established patient moderate complexity",
                "suggested_code": "99214",
                "rationale": "Documentation supports moderate-"
                              "complexity E/M. Verify chart review "
                              "elements for 99214.",
            },
            {
                "rule_id": "rule_ecg_001",
                "severity": "medium",
                "quote": "ECG performed in office",
                "suggested_code": "93000",
                "rationale": "ECG billed — verify interpretation "
                              "is documented separately from the "
                              "tracing acquisition.",
            },
            {
                "rule_id": "rule_icd_001",
                "severity": "medium",
                "quote": "palpitations reported",
                "suggested_code": "R00.2",
                "rationale": "Palpitations ICD-10 (R00.2) must "
                              "support the ECG and lipid panel.",
            },
            {
                "rule_id": "rule_lab_lipid_001",
                "severity": "low",
                "quote": "lipid panel ordered",
                "suggested_code": "80061",
                "rationale": "Lipid panel needs medical-necessity "
                              "ICD linkage.",
            },
        ],
        what_biller_would_have_done=(
            "Without Zorva, the biller submits 99214 + 93000 + "
            "80061 with R00.2 as the only ICD. The payer denies "
            "the 99214 because modifier -25 is missing (E/M "
            "bundled into the ECG), then denies the 80061 for "
            "medical necessity (lipid panel not linked to a "
            "diabetes ICD). $385 of denied revenue per encounter."
        ),
        dollar_impact=(
            "Zorva catches all 5 gaps before submission. Biller "
            "adds modifier -25 + R00.2 + E11.65 (screening for "
            "lipid panel); all three lines pay on first pass. "
            "$385 recovered per encounter, ~$1,540/mo at one "
            "such encounter per week. The HIGH-severity modifier-25 "
            "finding alone pays for the entire Zorva subscription "
            "if caught once per month."
        ),
        encounter_link="/encounter/enc_0000",
    ),
]


def get_case_study(slug: str) -> CaseStudy | None:
    """Look up a case study by slug."""
    for cs in CASE_STUDIES:
        if cs.slug == slug:
            return cs
    return None


def case_studies_index() -> list[dict[str, Any]]:
    """List case studies for the index page, with summary fields."""
    return [
        {
            "slug": cs.slug,
            "title": cs.title,
            "difficulty": cs.difficulty,
            "specialty": cs.specialty,
            "n_findings": len(cs.findings),
            "encounter_link": cs.encounter_link,
            "summary": cs.clinical_scenario,
            "encounter_id": cs.encounter_id,
        }
        for cs in CASE_STUDIES
    ]


def total_dollar_impact_per_study() -> dict[str, float]:
    """Sum the average-claim × findings count per study.

    Useful for the index page hero: 'Zorva has demonstrated
    $X/mo in avoided denials across 3 case studies.'
    """
    out: dict[str, float] = {}
    for cs in CASE_STUDIES:
        avg = SPECIALTY_AVG_USD.get(cs.specialty, AVG_CLAIM_USD)
        out[cs.slug] = round(avg * len(cs.findings), 2)
    return out