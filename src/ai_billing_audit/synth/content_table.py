"""Bundled content table for the synth.

The content table is the only place where the synth's clinical content
originates. It is plain Python data — strings, lists, dicts — loaded at
module import time. There is no I/O, no randomness, no LLM, no network
in this module: the table is the deterministic input the renderer
threads through the seed-driven RNG.

The nine scenarios below are a byte-for-byte lift of the
``_EASY_SCENARIOS`` / ``_MEDIUM_SCENARIOS`` / ``_HARD_SCENARIOS`` lists
that used to live in ``synth_agent.py``. The shape is preserved exactly
so the parent task's determinism tests still pass against the refactor
without modification.

A future "50 scenarios from a one-shot LLM pass" build-time task may
load ``data/content_table.json`` and replace this module's body; until
then, the inline table is the source of truth.
"""

from __future__ import annotations


from .template import Scenario

__all__ = [
    "DEFAULT_CONTENT",
    "EASY_CLEAN",
    "EASY_FLAGGED",
    "MEDIUM",
    "HARD",
]


# ---------------------------------------------------------------------------
# EASY scenarios — single-problem focus, no Rx, no modifiers.
# Each entry carries a ``benign_flag`` (used by the flagged variant to
# build the trigger_reason narrative). The clean variant ignores the
# benign_flag and uses a fixed "compliant" trigger_reason.
# ---------------------------------------------------------------------------

_EASY_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        hpi=(
            "55-year-old established patient presents with cough productive "
            "of clear sputum for 3 days. No fever, no shortness of breath."
        ),
        exam=(
            "Vitals stable. Lungs clear to auscultation bilaterally. No "
            "wheezing. Throat non-erythematous."
        ),
        mdm=(
            "Single acute problem of low complexity. Data review limited. "
            "Risk of complications low. No prescription drug management."
        ),
        icd10="R05",
        cpts=({"code": "99213"},),
        benign_flag=(
            "Patient demographic: age 55 recorded as 5 in intake form; "
            "documentation variance only, no clinical red flag."
        ),
    ),
    Scenario(
        hpi=(
            "Established patient here for routine follow-up of seasonal "
            "allergies. Reports mild nasal congestion, no rash, no "
            "wheezing."
        ),
        exam=("Nares mildly congested. No polyps. Lungs clear. Skin clear."),
        mdm=(
            "Single stable chronic problem of low complexity. No new data. "
            "Continue current over-the-counter regimen; no prescription."
        ),
        icd10="J30.9",
        cpts=({"code": "99213"},),
        benign_flag=(
            "Documentation note: middle initial transposed in chart header; "
            "no clinical impact, billing unaffected."
        ),
    ),
    Scenario(
        hpi=(
            "32-year-old with acute left ankle sprain after twisting it "
            "while running. Swelling and pain with weight bearing."
        ),
        exam=(
            "Left ankle tender over the lateral malleolus, mild edema, "
            "no deformity, full ROM with pain. Skin intact."
        ),
        mdm=(
            "Single acute uncomplicated injury. Low complexity. Recommend "
            "RICE; no prescription issued at this visit."
        ),
        icd10="S93.401A",
        cpts=({"code": "99213"},),
        benign_flag=(
            "Encounter timestamp recorded 5 minutes before patient arrival; "
            "scheduling transcription variance, no clinical consequence."
        ),
    ),
)


# ---------------------------------------------------------------------------
# MEDIUM scenarios — dual-problem + prescription drug management.
# The flagged variant pairs the same scenario with a documentation-gap
# trigger_reason. There is no separate benign_flag for MEDIUM (the gap
# is at the MDM-narrative level, not at the clinical-content level).
# ---------------------------------------------------------------------------

_MEDIUM_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        hpi=(
            "Established patient with type 2 diabetes and essential "
            "hypertension returns for follow-up. Reports home blood "
            "glucose logs averaging 140-160; BP at home 138/86."
        ),
        exam=(
            "BP 142/88, HR 78. Lungs clear. Heart RRR. Feet intact, no "
            "ulceration. Monofilament exam normal."
        ),
        mdm=(
            "Two stable chronic illnesses (diabetes, hypertension). "
            "Moderate complexity due to prescription drug management: "
            "metformin 1000 mg BID and lisinopril 20 mg daily reviewed "
            "and refilled. HbA1c ordered."
        ),
        icd10=["E11.9", "I10"],
        cpts=({"code": "99214"},),
    ),
    Scenario(
        hpi=(
            "Established patient with hyperlipidemia and osteoarthritis of "
            "the right knee. Knee pain worsening despite acetaminophen."
        ),
        exam=(
            "Right knee: mild crepitus, no effusion, ROM limited to 110 "
            "degrees. Gait steady."
        ),
        mdm=(
            "Two stable chronic problems. Moderate complexity. "
            "Prescription drug management: atorvastatin 20 mg continued; "
            "naproxen 500 mg BID added for OA flare with PPI coverage."
        ),
        icd10=["E78.5", "M17.11"],
        cpts=({"code": "99214"},),
    ),
    Scenario(
        hpi=(
            "Established patient with asthma and GERD presents for "
            "follow-up. Reports nighttime heartburn 3x/week; asthma "
            "well-controlled on current regimen."
        ),
        exam=(
            "Lungs clear, no wheeze. Abdomen soft, non-tender. PEF 85% of "
            "personal best."
        ),
        mdm=(
            "Two stable chronic problems. Moderate complexity. "
            "Prescription drug management: omeprazole 20 mg daily added; "
            "albuterol inhaler refilled."
        ),
        icd10=["J45.909", "K21.9"],
        cpts=({"code": "99214"},),
    ),
)


# ---------------------------------------------------------------------------
# HARD scenarios — chronic + acute + surgery + 90-day global period.
# The clean variant applies modifier -25 to the E/M; the flagged
# variant omits the modifier (an auditor should catch that).
# ---------------------------------------------------------------------------

_HARD_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        hpi=(
            "58-year-old with longstanding type 2 diabetes and chronic "
            "kidney disease stage 3 presents with acute right inguinal "
            "hernia, reducible, symptomatic for 2 weeks. Scheduled for "
            "outpatient open inguinal hernia repair."
        ),
        exam=(
            "Right inguinal bulge, reducible, non-tender. No overlying "
            "skin change. No femoral hernia. Creatinine 1.6 (baseline)."
        ),
        mdm=(
            "One acute surgical problem and two chronic conditions "
            "(diabetes, CKD). E/M for pre-operative clearance with "
            "separate evaluation of the hernia and chronic disease "
            "management. Surgery scheduled within 90-day global period."
        ),
        icd10="",  # not used for HARD; chronic/acute are spelled out below
        cpts=(),  # not used for HARD; cpt_em and cpt_surgery are spelled out below
        icd10_chronic_a="E11.9",  # diabetes, uncomplicated
        icd10_chronic_b="N18.3",  # CKD stage 3
        icd10_acute="K40.90",  # unilateral inguinal hernia, no obstruction/gangrene
        cpt_em="99214",
        cpt_surgery="49505",
        global_period_days=90,
    ),
    Scenario(
        hpi=(
            "62-year-old with chronic atrial fibrillation and HTN presents "
            "with acute cholecystitis. Plan: laparoscopic cholecystectomy."
        ),
        exam=(
            "Abdomen tender RUQ with positive Murphy's sign. Afebrile. "
            "INR therapeutic on warfarin."
        ),
        mdm=(
            "Acute surgical problem layered on chronic conditions. "
            "Pre-operative E/M addresses chronic disease management in "
            "addition to the acute surgical indication. Surgery falls "
            "within 90-day global period."
        ),
        icd10="",
        cpts=(),
        icd10_chronic_a="I48.91",  # atrial fibrillation
        icd10_chronic_b="I10",  # essential hypertension
        icd10_acute="K81.0",  # acute cholecystitis
        cpt_em="99214",
        cpt_surgery="47562",
        global_period_days=90,
    ),
    Scenario(
        hpi=(
            "71-year-old with chronic osteoarthritis of the left knee and "
            "well-controlled type 2 diabetes presents with end-stage "
            "left knee OA. Plan: total knee arthroplasty."
        ),
        exam=(
            "Left knee: severe crepitus, fixed flexion contracture 10 "
            "degrees, varus deformity. Gait antalgic."
        ),
        mdm=(
            "Acute surgical indication (TKA) for chronic end-stage OA. "
            "Pre-operative E/M includes chronic disease optimization for "
            "diabetes. TKA carries a 90-day global period."
        ),
        icd10="",
        cpts=(),
        icd10_chronic_a="M17.11",  # unilateral primary OA, right knee
        icd10_chronic_b="E11.9",  # type 2 diabetes
        icd10_acute="M17.11",  # (acute-on-chronic; we keep the same code)
        cpt_em="99214",
        cpt_surgery="27447",
        global_period_days=90,
    ),
)


# ---------------------------------------------------------------------------
# Public content table — the (tier, variant) -> tuple[Scenario, ...] map.
# ---------------------------------------------------------------------------

DEFAULT_CONTENT: dict[tuple[str, str], tuple[Scenario, ...]] = {
    ("EASY", "clean"): _EASY_SCENARIOS,
    ("EASY", "flagged"): _EASY_SCENARIOS,
    ("MEDIUM", "clean"): _MEDIUM_SCENARIOS,
    ("MEDIUM", "flagged"): _MEDIUM_SCENARIOS,
    ("HARD", "clean"): _HARD_SCENARIOS,
    ("HARD", "flagged"): _HARD_SCENARIOS,
}


# Per-tier aliases for tests / introspection. Not part of the public
# renderer contract; downstream code should go through ``DEFAULT_CONTENT``.
EASY_CLEAN: tuple[Scenario, ...] = _EASY_SCENARIOS
EASY_FLAGGED: tuple[Scenario, ...] = _EASY_SCENARIOS
MEDIUM: tuple[Scenario, ...] = _MEDIUM_SCENARIOS
HARD: tuple[Scenario, ...] = _HARD_SCENARIOS


# A tiny sanity net: every scenario must declare the fields its tier
# relies on. A typo here is cheaper to catch at import time than at
# render time.
def _validate() -> None:
    for s in _EASY_SCENARIOS:
        assert isinstance(s.icd10, str) and s.icd10, "EASY scenario missing icd10"
        assert s.cpts, "EASY scenario missing cpts"
    for s in _MEDIUM_SCENARIOS:
        assert isinstance(s.icd10, list) and len(s.icd10) >= 2, (
            "MEDIUM scenario needs >= 2 distinct ICD-10 codes"
        )
        assert s.cpts, "MEDIUM scenario missing cpts"
    for s in _HARD_SCENARIOS:
        assert s.icd10_chronic_a and s.icd10_chronic_b and s.icd10_acute, (
            "HARD scenario missing chronic/acute codes"
        )
        assert s.cpt_em and s.cpt_surgery and s.global_period_days is not None, (
            "HARD scenario missing CPT/global-period fields"
        )


_validate()
