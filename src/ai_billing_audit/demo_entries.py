"""Per-difficulty demo encounter registrations.

Each sibling kanban card (t_d33c5aca easy, t_5c741803 medium, t_d16db103
hard) adds its encounter to this module. The order of registration
determines the order on the index page, so easy comes first, then
medium, then hard.

Each registration is one line::

    register_demo_encounter(encounter_id=..., difficulty=..., summary=...)

Siblings are free to either append their line here OR import this
module's helpers and call ``register_demo_encounter(...)`` from their
own entry point — the registry is idempotent on encounter_id, so a
double registration is a no-op.
"""

from __future__ import annotations

from ai_billing_audit.demo_registry import register_demo_encounter

__all__: list[str] = []


# EASY — wired by t_d33c5aca (2026-06-16).
#
# enc_10032 is a one-finding encounter from data/val.json: a duplicate-
# service flag. Short clinical note, single rule, the evidence quote
# appears verbatim in the note so the highlight is unmistakable on the
# detail page. Ideal for an "easy" demo card because every element of
# the audit panel is exercised with no extra moving parts.
register_demo_encounter(
    encounter_id="enc_10032",
    difficulty="EASY",
    summary=(
        "Duplicate service billed same day as annual wellness visit — "
        "single rule (rule_overlap_001), evidence quote appears verbatim "
        "in the clinical note."
    ),
)


# MEDIUM — wired by t_5c741803 (2026-06-16).
#
# enc_0007 is a 4-finding encounter from data/train.json: a Type 2
# diabetes follow-up with HbA1c and an influenza vaccine. The findings
# span 3 categories (diagnosis / laboratory / procedure) and a mix of
# severities (1 medium, 3 low) — the "medium" complexity band the
# acceptance criteria for the task card calls out. Every evidence
# quote appears verbatim in the clinical note, so the highlight
# renders on all 4 findings (not just one) — the kind of multi-finding
# detail page the medium tier needs to demonstrate.
register_demo_encounter(
    encounter_id="enc_0007",
    difficulty="MEDIUM",
    summary=(
        "Type 2 diabetes follow-up with HbA1c and influenza vaccine — "
        "4 ground-truth findings across diagnosis / laboratory / procedure "
        "categories; one medium-severity ICD-linkage finding plus three "
        "low-severity rule-citation findings."
    ),
)


# HARD — wired by t_d16db103 (2026-06-16).
#
# enc_0000 is a 5-finding encounter from data/train.json: an established
# patient moderate-complexity E/M with an in-office ECG, palpitations,
# modifier 25 (the high-severity finding), and a lipid panel. The
# findings span 5 distinct categories (evaluation / cardiology /
# diagnosis / modifier / laboratory) and every severity tier the rubric
# defines (info / low / medium / high) — the "hard" complexity band the
# acceptance criteria for this card call out.
#
# The primary (highest-severity) finding is gt3 (rule_modifier_25_001,
# HIGH) with evidence quote "separately identifiable E/M" — that span
# is what the encounter detail page highlights. The other 4 findings
# have quotes that also appear verbatim in the clinical note, so the
# "show in note" / "copy quote" buttons have multiple destinations to
# jump to, which is the hard-tier audit cue the task body calls out
# ("all interactive buttons … are clickable").
register_demo_encounter(
    encounter_id="enc_0000",
    difficulty="HARD",
    summary=(
        "Established patient moderate-complexity E/M with in-office ECG, "
        "palpitations, modifier 25, and lipid panel — 5 ground-truth "
        "findings across evaluation / cardiology / diagnosis / modifier / "
        "laboratory categories, including a HIGH-severity modifier-25 "
        "finding (rule_modifier_25_001)."
    ),
)
