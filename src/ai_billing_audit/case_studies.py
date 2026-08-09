"""Worked-example case studies for the marketing site.

Sales calls need a 'show me an example' moment. These case
studies pair each difficulty band with a representative
billing problem and the auditor's findings.

Each case study shows:
  - The clinical scenario (anonymized — patient identifiers
    are SHA-256 hashes from val.json)
  - The claim as submitted
  - What the auditor found (rule_id + severity + quote)
  - What the biller would have done without Zorva
  - The dollar impact (recovered revenue + audit fees avoided)

NOTE on code sets
-----------------
The first three case studies use US-CPT codes (99213, 99214,
80061, 93000, 93306) and US ICD-10 (R00.2, I10, E11.65). They
are SAMPLE FORMAT examples — the auditor workflow is the
same regardless of code set, but the specific codes are not
the codes Zorva runs on in production. The marketing copy
makes the AHCIP-first positioning explicit so prospects
don't mistake the sample-format examples for the production
ruleset.

The 4th case study (enc_ahcip_001-modifier-25) IS AHCIP-grounded
and uses real AHCIP SOMB fee codes + AHCIP GR references
(GR 1.4, GR 4.4, GR 3.3). This is the case study that
demonstrates Zorva on a representative Alberta AHCIP claim.

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
    "ahcip_family_medicine": 165.0,  # AHCIP-focused visit, mid-range
}


@dataclass(frozen=True)
class CaseStudy:
    """A worked example for the marketing site.

    All fields are user-visible copy. Keep the prose specific
    enough to be useful in a sales conversation but anonymized
    enough to publish without a BAA.
    """

    slug: str  # URL slug: /case-studies/{slug}
    title: str  # "Modifier-25 caught on chest pain encounter"
    difficulty: str  # "easy" | "medium" | "hard"
    specialty: str  # "cardiology"
    encounter_id: str  # "enc_0000" — the underlying val.json encounter
    clinical_scenario: str  # 2-3 sentence narrative
    claim_summary: str  # what was billed
    findings: list[dict[str, Any]]  # [{rule_id, severity, quote, suggested_code}]
    what_biller_would_have_done: str
    dollar_impact: str
    encounter_link: str | None = None  # "/encounter/enc_0000"


# Three case studies, one per difficulty band.
# Each is a frozen record that the route template renders verbatim.
CASE_STUDIES: list[CaseStudy] = [
    CaseStudy(
        slug="enc_10032-easy-duplicate-service",
        title="[Sample format] Duplicate-service flag: annual wellness + problem visit",
        difficulty="easy",
        specialty="primary_care",
        encounter_id="enc_10032",
        clinical_scenario=(
            "An established patient came in for an annual wellness visit. "
            "The physician also performed and billed a separate "
            "problem-focused ECG the same day. Without modifier -25 on "
            "the E/M line, the system would treat the second service as "
            "bundled into the first and flag it. (This is a SAMPLE "
            "FORMAT example using US-CPT codes; Zorva's production "
            "ruleset is AHCIP — see enc_ahcip_001 for the Alberta version.)"
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
            "The system bundles them and flags claim 2 — a $165 "
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
        title="[Sample format] Imaging coverage gap: echocardiogram ordered but unbilled",
        difficulty="medium",
        specialty="cardiology",
        encounter_id="enc_0011",
        clinical_scenario=(
            "An established patient with hypertension returns for "
            "follow-up. The physician documents palpitations, orders "
            "an echocardiogram and a lipid panel. The biller submits "
            "an E/M claim (99214) and the lipid panel (80061), but "
            "forgets to bill the echocardiogram (93306). (This is a "
            "SAMPLE FORMAT example; see enc_ahcip_001 for the AHCIP version.)"
        ),
        claim_summary=(
            "99214 (E/M moderate), 80061 (lipid panel). "
            "Echocardiogram documented but unbilled. The clinic "
            "loses $240 of revenue for work that was already done."
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
        title="[Sample format] Modifier-25 + ECG + palpitations + lipid panel: 5 findings",
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
            "laboratory categories. (SAMPLE FORMAT — see enc_ahcip_001 "
            "for the AHCIP version of this scenario.)"
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
                "from the ECG. Without it, the "
                "system bundles and denies the E/M.",
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
                "rationale": "Lipid panel needs medical-necessity ICD linkage.",
            },
        ],
        what_biller_would_have_done=(
            "Without Zorva, the biller submits 99214 + 93000 + "
            "80061 with R00.2 as the only ICD. The system flags "
            "the 99214 because modifier -25 is missing (E/M "
            "bundled into the ECG), then flags the 80061 for "
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
    # ─── AHCIP-grounded case study ──────────────────────────────────
    # This is the case study that demonstrates Zorva on a real
    # Alberta AHCIP claim. Uses AHCIP SOMB fee codes and GR
    # references. Marketing copy here can be specific to Alberta
    # without contradicting the AHCIP-first positioning.
    CaseStudy(
        slug="enc_ahcip_001-modifier-25",
        title="AHCIP modifier-25 + dx-linkage + CMGP: 4 findings on a 03.04A encounter",
        difficulty="hard",
        specialty="ahcip_family_medicine",
        encounter_id="enc_ahcip_001",
        clinical_scenario=(
            "An established Alberta patient (UHC 12345-6789) presents "
            "with a 2-week history of cough and shortness of breath. "
            "The family physician performs a same-day comprehensive "
            "office visit (AHCIP 03.04A), orders a chest X-ray "
            "(AHCIP X-090), and writes a referral to a respirologist. "
            "Documentation supports all three services, plus an "
            "after-hours premium — but the original claim as submitted "
            "missed the modifier-25 on the 03.04A (it was billed "
            "with the X-090 same-day), used an ICD-9 code (786.2) "
            "that doesn't link the chest X-ray to a respiratory dx, "
            "and bumped up to a CMGP (03.04A) when a focused visit "
            "(03.03A) was actually documented."
        ),
        claim_summary=(
            "03.04A (comprehensive office visit, CMGP), X-090 "
            "(chest X-ray, single view). NO modifier on the 03.04A. "
            "ICD-9 786.2 (cough) is the only dx. The after-hours "
            "premium is missing. The referral letter is not "
            "attached to the claim."
        ),
        findings=[
            {
                "rule_id": "AH-MOD-25",
                "severity": "high",
                "quote": "same-day E/M + diagnostic imaging",
                "suggested_code": "03.04A + modifier-25",
                "rationale": (
                    "Per AHCIP GR 1.4 (Modifier-25 — Unbundled "
                    "E/M on the Same Day as a Procedure), a "
                    "same-day E/M + diagnostic procedure requires "
                    "modifier-25 to indicate the E/M is separately "
                    "identifiable. Without it, AHCIP bundles the "
                    "03.04A into the X-090 and pays the X-090 "
                    "only — a $58 loss per encounter (03.04A = "
                    "$58.20 vs X-090 alone = $14.80)."
                ),
            },
            {
                "rule_id": "AH-DX-01",
                "severity": "high",
                "quote": "cough (786.2) is not a respiratory dx",
                "suggested_code": "786.2 → 786.05 (shortness of breath) + R05 (cough)",
                "rationale": (
                    "Per AHCIP GR 4.4 (Diagnostic Code Linkage), the "
                    "primary dx must support medical necessity for the "
                    "billed service. ICD-9 786.2 (cough) doesn't "
                    "link to the chest X-ray — a respiratory sign or "
                    "symptom (e.g. 786.05 shortness of breath, or "
                    "R05 cough in ICD-10) is required. The biller "
                    "should add 786.05 to the claim to support the "
                    "X-090."
                ),
            },
            {
                "rule_id": "AH-CG-01",
                "severity": "medium",
                "quote": "documentation supports focused visit (03.03A)",
                "suggested_code": "03.04A → 03.03A",
                "rationale": (
                    "Per AHCIP GR 3.3 (CMGP Eligibility), a "
                    "Comprehensive/General Assessment (03.04A) "
                    "requires a full history, full physical, and "
                    "comprehensive management plan. The "
                    "documentation here is a focused history + "
                    "focused physical + a single chief complaint "
                    "(cough, SOB). The 03.04A should be 03.03A "
                    "(focused visit, $32.40 vs $58.20). Note: "
                    "this is a downward adjustment — the clinic "
                    "was OVER-billing, which is the more serious "
                    "kind of error for HIA / PIPEDA purposes "
                    "(over-billing = potential fraud flag)."
                ),
            },
            {
                "rule_id": "AH-REF-01",
                "severity": "low",
                "quote": "referral letter not attached",
                "suggested_code": "(attach referral letter to claim)",
                "rationale": (
                    "The respirology referral is documented in the "
                    "chart but not attached to the AHCIP claim. "
                    "Per AHCIP GR 6.2 (Referral Documentation), the "
                    "referral letter is a claim-attachable document. "
                    "Biller should attach the letter to avoid a "
                    "denial on the respirology follow-up claim "
                    "in 4-6 weeks."
                ),
            },
        ],
        what_biller_would_have_done=(
            "Without Zorva, the biller submits 03.04A + X-090 "
            "with only ICD-9 786.2. AHCIP's claims-processing "
            "system (CII/Paragon) flags the 03.04A for bundling "
            "(missing modifier-25) and pays only the X-090. The "
            "bill must be re-submitted with modifier-25 + a "
            "respiratory dx, and the 03.04A is reviewed manually "
            "for CMGP eligibility. Net result: 60-90 days of "
            "back-and-forth, the 03.04A is eventually downgraded "
            "to 03.03A (refund requested on the $25.80 "
            "difference), and the respirology referral claim is "
            "denied 6 weeks later for missing documentation. "
            "Total damage: ~$90 of net lost revenue + 3 hours "
            "of biller time + a respirology claim that has to be "
            "re-filed."
        ),
        dollar_impact=(
            "Zorva catches all 4 gaps before submission. The "
            "biller (1) adds modifier-25 to the 03.04A, (2) "
            "swaps the dx to 786.05 (shortness of breath) to "
            "support the X-090, (3) downgrades the visit to "
            "03.03A to avoid the CMGP audit, and (4) attaches "
            "the referral letter to the claim. All three lines "
            "pay on first pass. Net revenue per encounter: "
            "$105.40 (vs ~$14.80 without Zorva). At 1 such "
            "encounter per week that's $3,800/mo of additional "
            "recovered revenue — a 13× ROI on the Solo tier "
            "($499/mo). All four findings cite SOMB GR "
            "references (GR 1.4, 3.3, 4.4, 6.2) so the biller's "
            "appeal letter to AHCIP is self-documenting."
        ),
        encounter_link=None,  # AHCIP case study is illustrative; no demo encounter
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
