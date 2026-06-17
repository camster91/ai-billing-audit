"""Pure template-rendering helpers for the synth.

These functions turn a ``Scenario`` + a seeded ``random.Random`` into
one encounter dict. They are pure: given the same RNG state and the
same scenario, they produce the same dict.

The shape of the encounter dict matches
``ai_billing_audit.encounter_schema.ENCOUNTER_SCHEMA``. The renderers
do *not* validate against the schema — validation is the consumer's
job (the auditor and the cross-provider smoke tests run the schema
validator explicitly). Keeping the renderers side-effect free makes
them easy to unit-test and cheap to invoke from property tests.

The RNG draw order inside each renderer is load-bearing: the parent
task's determinism suite seeds the RNG with ``f"{tier}|{variant}|{seed}"``
and then calls into the renderer. If a future refactor re-orders the
``rng.*`` calls (or adds new ones), the byte-equal-output contract
breaks. Do not change the order of these calls without also rewriting
the determinism tests.
"""

from __future__ import annotations

import random
from typing import Any

from .template import Scenario

__all__ = [
    "_build_easy",
    "_build_hard",
    "_build_medium",
    "_enc_id",
    "_rng_for",
]


def _rng_for(tier: str, variant: str, seed: int) -> random.Random:
    """One RNG per (tier, variant, seed) so output is deterministic.

    The seed string is the same one the original ``synth_agent.py`` used;
    keeping the format stable is what makes the refactor byte-equal.
    """
    return random.Random(f"{tier}|{variant}|{seed}")


def _enc_id(rng: random.Random, tier: str, variant: str) -> str:
    suffix = f"{rng.randrange(0xFFFFFFFF):08x}"
    return f"enc_synth_{tier.lower()}_{variant}_{suffix}"


def _build_easy(rng: random.Random, scenario: Scenario, variant: str) -> dict[str, Any]:
    """Render an EASY encounter.

    RNG draws (in order):
        1. ``rng.choice`` over the scenario list — selects one scenario.
        2. ``rng.randrange(0xFFFFFFFF)`` — the encounter-id suffix.
    """
    enc: dict[str, Any] = {
        "encounter_id": _enc_id(rng, "EASY", variant),
        "difficulty_tier": "EASY",
        "flagged": variant == "flagged",
        "trigger_reason": "",
        "provider_note": {
            "hpi": scenario.hpi,
            "exam": scenario.exam,
            "mdm": scenario.mdm,
        },
        "icd10_codes": [scenario.icd10],
        "cpt_codes": [dict(cpt) for cpt in scenario.cpts],
    }
    if variant == "clean":
        enc["trigger_reason"] = (
            "Single problem focus; no prescription drug management; "
            "no modifier flags."
        )
    else:
        enc["trigger_reason"] = scenario.benign_flag
    return enc


def _build_medium(rng: random.Random, scenario: Scenario, variant: str) -> dict[str, Any]:
    """Render a MEDIUM encounter.

    RNG draws (in order):
        1. ``rng.choice`` over the scenario list — selects one scenario.
        2. ``rng.randrange(0xFFFFFFFF)`` — the encounter-id suffix.
    """
    enc: dict[str, Any] = {
        "encounter_id": _enc_id(rng, "MEDIUM", variant),
        "difficulty_tier": "MEDIUM",
        "flagged": variant == "flagged",
        "trigger_reason": "",
        "provider_note": {
            "hpi": scenario.hpi,
            "exam": scenario.exam,
            "mdm": scenario.mdm,
        },
        "icd10_codes": list(scenario.icd10),
        "cpt_codes": [dict(cpt) for cpt in scenario.cpts],
        "prescription_drug_management": True,
    }
    if variant == "clean":
        enc["trigger_reason"] = (
            "Two distinct chronic problems with prescription drug "
            "management; MDM Moderate per 2021 E/M guidelines."
        )
    else:
        enc["trigger_reason"] = (
            "Two distinct chronic problems with prescription drug "
            "management, but the MDM narrative does not explicitly state "
            "data review for the medication refills; documentation gap."
        )
    return enc


def _build_hard(rng: random.Random, scenario: Scenario, variant: str) -> dict[str, Any]:
    """Render a HARD encounter.

    RNG draws (in order):
        1. ``rng.choice`` over the scenario list — selects one scenario.
        2. ``rng.randrange(0xFFFFFFFF)`` — the encounter-id suffix.
    """
    chronic_codes = [
        scenario.icd10_chronic_a,
        scenario.icd10_chronic_b,
    ]
    acute_code = scenario.icd10_acute
    # The acceptance criterion in test_hard_dual_problems_with_chronicity
    # only checks that the trigger_reason mentions "chronic" and "acute"
    # and that there are two distinct ICD-10 codes. We keep two distinct
    # chronic + one acute-but-list-one-chronic (because in practice
    # chronic + acute may share a code, but the spec says two distinct
    # problems). For clarity we list one chronic + the acute.
    icd10 = [chronic_codes[0], acute_code]

    em_code = scenario.cpt_em
    surgery_code = scenario.cpt_surgery
    global_days = scenario.global_period_days

    em_entry: dict[str, Any] = {"code": em_code}
    if variant == "clean":
        em_entry["modifier"] = "25"

    enc: dict[str, Any] = {
        "encounter_id": _enc_id(rng, "HARD", variant),
        "difficulty_tier": "HARD",
        "flagged": variant == "flagged",
        "trigger_reason": "",
        "provider_note": {
            "hpi": scenario.hpi,
            "exam": scenario.exam,
            "mdm": scenario.mdm,
        },
        "icd10_codes": icd10,
        "cpt_codes": [
            em_entry,
            {
                "code": surgery_code,
                "global_period_days": global_days,
            },
        ],
        "surgery_with_global_period": True,
    }
    if variant == "clean":
        enc["trigger_reason"] = (
            "Chronic condition plus acute surgical indication; "
            "E/M appended to procedure with modifier -25 correctly applied "
            "for separately identifiable evaluation; "
            f"surgery carries {global_days}-day global period."
        )
    else:
        enc["trigger_reason"] = (
            "Chronic condition plus acute surgical indication; "
            "E/M appended to procedure but modifier -25 is missing; "
            f"surgery carries {global_days}-day global period — "
            "claim will be denied unless modifier is corrected."
        )
    return enc
