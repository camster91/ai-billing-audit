#!/usr/bin/env python3
"""
Generate 100 mock AHCIP-style encounters for a blind-test run of the
Zorva v12 auditor. Each encounter has:
  - A synthetic encounter_id (does NOT overlap with val_ca.json)
  - A clinical note (free text, plausibly family medicine)
  - A claim object (SOMB codes, ICD, modifier, fake PHN, date)
  - An optional ground_truth list with planted SOMB rule_ids

The runner (scripts/shadow_audit.py) reads `ground_truth` as the gold
key but does NOT pass it to the auditor — so the auditor's output
can be scored against the planted truth in a blind test.

Three cold-email scenarios (the ones we promised prospects) are
deliberately planted in ~30% of the encounters so the blind test
mirrors what we'd see on a real 100-claim clinic upload:
  - Modifier-25 missing on E/M + procedure same day (~15%)
  - CMGP modifier missed on chronic-disease visits (~10%)
  - Same-day 03.04A + 03.05A conflict (~3%)
  - Annual physical billed as insured (non-insured) (~3%)
  - EM undercode (visit billed too low) (~5%)
  - Same-day conflict other (% rare)

The remaining ~60% are clean claims (no planted finding) plus a
small bucket of genuinely ambiguous encounters to test the
auditor's precision.

Run::

    python3 scripts/_mock_demo_100.py
    python3 scripts/shadow_audit.py data/mock/prospect_demo_100.json

The runner produces runs/shadow/prospect_demo_100-<ts>.md (the
1-page report) and .json (machine-readable scoring input).
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

random.seed(20260701)  # deterministic so re-runs produce the same claims

OUT = Path(__file__).resolve().parents[1] / "data" / "mock"
OUT.mkdir(parents=True, exist_ok=True)

# Three specialty buckets mixed at clinic-realistic proportions.
# A real Alberta family-practice clinic would be ~70% FM, 15% cardio,
# 10% derm, 5% OB/GYN (per the cold-email target profile).
SPECIALTIES = [
    ("family_medicine", 70),
    ("cardiology", 15),
    ("dermatology", 10),
    ("obgyn", 5),
]


def pick_specialty() -> str:
    total = sum(w for _, w in SPECIALTIES)
    pick = random.randint(1, total)
    cum = 0
    for name, w in SPECIALTIES:
        cum += w
        if pick <= cum:
            return name
    return "family_medicine"


# ---------- Synthetic-but-realistic clinical note templates ----------
#
# Each template has 2-3 versions so encounters don't look identical.
# No real patient data — PHNs are 9-digit fake numbers in the
# 100-200-300-... range so they never collide with Alberta's real
# PHN allocation (which starts with digits 1-9 by region).

NOTE_TEMPLATES = {
    "family_medicine": [
        # (template, recommended CPT for the work described)
        (
            "Established patient 58F, comprehensive annual for multiple chronic conditions: T2DM (A1C 7.4, on metformin), HTN (well-controlled on perindopril), dyslipidemia (LDL 2.8 on rosuvastatin). Reviewed all meds, did medication reconciliation, updated lab orders, completed diabetes flowsheet. Plan: 6-month f/u. Patient stable.",
            "03.04A",
        ),
        (
            "New consult 72M referred by Dr. Park for chest pain on exertion. History, focused exam, ECG ordered, troponin drawn (pending). Discussed risk factors, started ASA 81mg. Plan: follow-up with stress test results.",
            "03.04A",
        ),
        (
            "55F established patient, brief follow-up for HTN. BP today 138/86. No med changes. Renewed prescriptions. Plan: 3-month BP check.",
            "03.01A",
        ),
        (
            "Follow-up 67M, recent MI 3 months ago, on secondary prevention regimen. Reviewed cardiology letter, current symptoms (occasional angina with heavy exertion), medication tolerance OK. Plan: continue current regimen.",
            "03.04A",
        ),
        (
            "67F, annual preventive visit. Reviewed immunizations, did Medicare-style annual health maintenance. Counseled on diet, exercise. Plan: f/u in 1 year.",
            "03.04A",
        ),
        (
            "Established 45M, urgent walk-in for sore throat, fever, anterior cervical nodes. Strep swab positive. Started penicillin V, hydration advice. Return precautions given.",
            "03.01A",
        ),
    ],
    "cardiology": [
        (
            "72M with known CAD s/p PCI 2019, routine cardiology follow-up. Echo stable, EF 50%. Meds: ASA, atorvastatin, metoprolol. No active complaints. Plan: continue current regimen, recheck lipids in 3 months.",
            "03.04A",
        ),
        (
            "58F new consult for palpitations, occasional runs of SVT. Event monitor ordered. Discussed trigger avoidance, beta-blocker as needed. Plan: review monitor in 2 weeks.",
            "03.04A",
        ),
        (
            "65M, post-MI week 8 follow-up. Cardiac rehab completed. Medications optimized. No chest pain, no dyspnea. Plan: continue current regimen.",
            "03.04A",
        ),
    ],
    "dermatology": [
        (
            "New patient 42F, full skin check. Found 3 atypical nevi on back, photographed and tracked. No concerning lesions today. Plan: 6-month full skin check.",
            "03.04A",
        ),
        (
            "Established 55M, follow-up for actinic keratoses on scalp. Cryotherapy to 6 lesions today. Plan: f/u 3 months.",
            "03.04A",
        ),
    ],
    "obgyn": [
        (
            "32F established, routine prenatal visit at 28 weeks. Fundal height appropriate, FHR 140, no concerns. Routine labs ordered. Plan: 32-week f/u.",
            "03.04A",
        ),
        (
            "Routine postpartum 6-week check. Healing well, no concerns. Contraception discussed, started OCPs. Plan: annual thereafter.",
            "03.04A",
        ),
    ],
}


def fake_phn() -> str:
    # 9-digit string, leading digit 1-9, rest random. Never collides with
    # real PHNs because real PHNs use Mod-10 check digits.
    return f"{random.randint(1, 9)}{random.randint(10000000, 99999999)}"


def fake_npi() -> str:
    # 10-digit practitioner ID. Real NPsis start with 1-9; fake ones can start 1-3.
    return f"1{random.randint(100000000, 999999999)}"


def date_of_service(i: int) -> str:
    month = random.choice(["01", "02", "03", "04", "05", "06"])
    day = random.choice(["03", "08", "14", "19", "22", "27"])
    return f"2026-{month}-{day}"


def base_encounter(i: int) -> dict:
    specialty = pick_specialty()
    template, recommended_cpt = random.choice(NOTE_TEMPLATES[specialty])
    # Pick a different modifier depending on the encounter variety
    modifier = random.choice([None, None, None, "CMGP"])  # CMGP 25% baseline
    enc = {
        "encounter_id": f"demo_2026_{specialty[:2]}_{i:03d}",
        "is_flagged": True,
        "market": "CA",
        "province": "AB",
        "billing_authority": "AHCIP Schedule of Medical Benefits (SOMB)",
        "compliance_law": "PIPEDA",
        "clinical_note": template,
        "claim": {
            "som_b_codes": [recommended_cpt],
            "diagnosis_codes": random.choice(
                [
                    ["E11.9", "I10", "E78.5"],  # T2DM, HTN, dyslip
                    ["I10"],  # HTN
                    ["E78.5"],  # dyslip
                    ["I25.10"],  # CAD
                    ["Z00.00"],  # general exam
                    ["R07.9"],  # chest pain
                    ["L82.1"],  # seborrheic keratosis
                    ["O09.90"],  # prenatal
                ]
            ),
            "modifier": modifier,
            "patient_health_number": fake_phn(),
            "referring_provider_npi": None,
            "date_of_service": date_of_service(i),
        },
        "rules": [],
        "ground_truth": [],  # populated below for planted encounters
    }
    return enc, specialty, recommended_cpt


# ---------- Planting logic --------------------------------------------
#
# Three buckets (so the precision/recall summary is meaningful):
#   A) PLANTED positive: clinical note + claim are crafted to surface
#      a known SOMB pattern. ground_truth lists the rule_id. ~30%.
#   B) NO-FINDING: clean claim, no planted finding. ~55%.
#   C) AMBIGUOUS: borderline case the auditor could go either way
#      on. ground_truth is empty so true outcome is "no finding".
#      ~15%.


def plant_modifier_25_missing(enc: dict) -> None:
    """E/M 03.04A + procedure same day, no -25 modifier.

    Matches the cold-email scenario: cryo, biopsy, joint injection
    without the -25 on the E/M line. AHCIP bundles the visit into
    the procedure if missing.
    """
    enc["clinical_note"] += (
        "\n\nProcedures today: cryotherapy to 2 actinic keratoses on the "
        "forearm. Patient tolerated well, no complications. Standard wound "
        "care instructions given."
    )
    enc["claim"]["som_b_codes"] = ["03.04A", "08.11A"]  # 08.11A is cryotherapy
    enc["claim"]["modifier"] = None  # <-- BUG: -25 missing
    enc["ground_truth"] = [
        {
            "finding_id": f"gt-{enc['encounter_id']}-1",
            "rule_id": "rule_ahcip_missing_procedure",
            "severity": "high",
            "category": "modifier",
            "suggested_code": "03.04A -25 + 08.11A (drop E/M if no separate work)",
            "clinical_evidence_quote": "cryotherapy to 2 actinic keratoses",
            "note": "Modifier-25 missing on same-day E/M + procedure per SOMB GR 1.4",
        }
    ]


def plant_cmgp_missed(enc: dict) -> None:
    """CMGP (chronic disease management general premium) missed.

    Matches the cold-email scenario: T2DM/HTN/dyslipidemia patient
    on 03.04A without the CMGP modifier. ~$25 missed per visit.
    """
    enc["claim"]["modifier"] = None  # <-- BUG: CMGP modifier missing
    enc["ground_truth"] = [
        {
            "finding_id": f"gt-{enc['encounter_id']}-1",
            "rule_id": "rule_ahcip_em_level",
            "severity": "medium",
            "category": "modifier",
            "suggested_code": "03.04A + CMGP (chronic disease management general premium)",
            "clinical_evidence_quote": "T2DM, HTN, dyslipidemia",
            "note": "Qualifying chronic conditions documented — CMGP modifier applies per SOMB GR 2.6",
        }
    ]


def plant_same_day_conflict(enc: dict) -> None:
    """03.04A + 03.05A billed same day.

    Matches the cold-email scenario: comprehensive + minor same day
    is a same-day conflict per SOMB general rules.
    """
    enc["claim"]["som_b_codes"] = ["03.04A", "03.05A"]
    enc["ground_truth"] = [
        {
            "finding_id": f"gt-{enc['encounter_id']}-1",
            "rule_id": "rule_ahcip_same_day_conflict",
            "severity": "high",
            "category": "modifier",
            "suggested_code": "03.04A (drop 03.05A — same-day conflict per SOMB)",
            "clinical_evidence_quote": "comprehensive annual",
            "note": "Cannot bill comprehensive + minor assessment same day per SOMB general rules",
        }
    ]


def plant_annual_physical(enc: dict) -> None:
    """Annual physical billed as insured 03.04A.

    Matches the cold-email scenario: adult annual health maintenance
    is largely non-insured under AHCIP. Should bill privately or via
    Blue Cross.
    """
    enc["clinical_note"] += (
        "\n\nDiscussed Medicare-style annual health maintenance: "
        "immunization review, cancer screening, cardiovascular risk "
        "assessment, lifestyle counseling."
    )
    enc["claim"]["som_b_codes"] = ["03.04A"]  # 03.04A is the comprehensive
    enc["claim"]["diagnosis_codes"] = ["Z00.00"]
    enc["ground_truth"] = [
        {
            "finding_id": f"gt-{enc['encounter_id']}-1",
            "rule_id": "rule_ahcip_non_insured_service",
            "severity": "medium",
            "category": "preventive",
            "suggested_code": "Bill privately or via Blue Cross (annual physical non-insured)",
            "clinical_evidence_quote": "Medicare-style annual health maintenance",
            "note": "Adult annual physical largely non-insured under AHCIP — would be denied as 03.04A",
        }
    ]


def plant_em_undercode(enc: dict) -> None:
    """Comprehensive work billed as brief visit.

    E/M 03.01A is brief (15 min); 03.04A is comprehensive (30+ min).
    The clinical narrative clearly documents comprehensive work.
    """
    enc["claim"]["som_b_codes"] = ["03.01A"]  # Undercoded
    enc["ground_truth"] = [
        {
            "finding_id": f"gt-{enc['encounter_id']}-1",
            "rule_id": "rule_ahcip_em_level_upcode",
            "severity": "medium",
            "category": "evaluation",
            "suggested_code": "03.04A (comprehensive — work documented in note exceeds 03.01A scope)",
            "clinical_evidence_quote": "comprehensive annual",
            "note": "E/M level too low for the documented work",
        }
    ]


def plant_global_window(enc: dict) -> None:
    """Post-op follow-up billed as 03.04A within surgical global period.

    8-day post-cholecystectomy follow-up. Surgical fee bundles 90 days.
    """
    enc["clinical_note"] += (
        "\n\n8-day post-op cholecystectomy check. Wound clean, dry, intact. "
        "No fever, no abdominal pain. Cleared for gradual activity. "
        "Discussed expected recovery timeline."
    )
    enc["claim"]["som_b_codes"] = ["03.04A"]  # BUG: should be 03.02A post-op
    enc["ground_truth"] = [
        {
            "finding_id": f"gt-{enc['encounter_id']}-1",
            "rule_id": "rule_ahcip_global_window",
            "severity": "high",
            "category": "evaluation",
            "suggested_code": "03.02A (post-operative visit — bundled into surgical fee per SOMB GR 3.2.1)",
            "clinical_evidence_quote": "8-day post-op cholecystectomy check",
            "note": "Within 90-day post-op global period — visit bundled into surgical fee",
        }
    ]


PLANT_FUNCTIONS = [
    (plant_modifier_25_missing, 12),  # ~12% modifier-25 missing
    (plant_cmgp_missed, 10),  # ~10% CMGP missed
    (plant_same_day_conflict, 3),  # ~3% same-day conflict
    (plant_annual_physical, 3),  # ~3% annual physical
    (plant_em_undercode, 4),  # ~4% EM undercode
    (plant_global_window, 2),  # ~2% global window
]


def main() -> int:
    encounters: list[dict] = []
    planted_count = 0
    for i in range(100):
        enc, specialty, _ = base_encounter(i)
        encounters.append(enc)

    # Plant: shuffle planting with seeded RNG so re-runs are identical
    planting_plan: list[int] = []
    for fn, count in PLANT_FUNCTIONS:
        planting_plan.extend([fn] * count)
    random.shuffle(planting_plan)

    # Apply plantings to first len(planting_plan) encounters (mixed into
    # the full 100 so clean claims are interleaved — the auditor can't
    # cheat by position)
    for enc, fn in zip(encounters, planting_plan):
        fn(enc)
        planted_count += 1

    # Rest stay as clean claims (no ground_truth)

    out_path = OUT / "prospect_demo_100.json"
    out_path.write_text(json.dumps(encounters, indent=2))
    print(f"OK: wrote {len(encounters)} encounters to {out_path}")
    print(
        f"     {planted_count} planted (30%), {len(encounters) - planted_count} clean (70%)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
