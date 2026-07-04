"""Synthetic encounter dataset (100 train / 50 val) and deterministic
ground-truth generator.

The encounters are clinical-note snippets that each contain 0-2 billing
findings. The ground-truth is a fixed, hand-coded set of (rule_id,
category, suggested_code, clinical_evidence_quote) tuples derived from
the encounter content. A prompt that, via the deterministic extractor,
emits exactly these tuples scores R=1, P=1 on that encounter.

The split is deterministic via a fixed seed. Train and val are disjoint.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "get_train",
    "get_val",
    "ground_truth_for",
    "load_split",
    "write_split",
    "generate_train_split",
    "generate_val_split",
]


# -----------------------------------------------------------------------------
# Rule taxonomy
# -----------------------------------------------------------------------------


# Each rule has:
#   - category: short slug
#   - trigger: lower-case phrase that must appear in the clinical_note
#   - suggested_code: CPT or ICD-10
#   - severity: default severity for the rule
#   - clinical_evidence_quote: the exact span the auditor must cite
#     (computed below; for some rules it's the trigger itself)
#
# Quotes are anchored to a 12-40 char substring of the clinical note.
# The dataset below crafts clinical notes that include the trigger
# phrase verbatim; the ground-truth quote is the trigger phrase.

RULES: list[dict[str, str]] = [
    {
        "rule_id": "rule_ecg_001",
        "category": "cardiology",
        "trigger": "ECG performed in office",
        "suggested_code": "93000",
        "severity": "medium",
    },
    {
        "rule_id": "rule_ecg_002",
        "category": "cardiology",
        "trigger": "rhythm strip reviewed",
        "suggested_code": "93040",
        "severity": "low",
    },
    {
        "rule_id": "rule_em_001",
        "category": "evaluation",
        "trigger": "established patient moderate complexity",
        "suggested_code": "99214",
        "severity": "info",
    },
    {
        "rule_id": "rule_em_002",
        "category": "evaluation",
        "trigger": "new patient low complexity",
        "suggested_code": "99203",
        "severity": "info",
    },
    {
        "rule_id": "rule_em_003",
        "category": "evaluation",
        "trigger": "established patient high complexity",
        "suggested_code": "99215",
        "severity": "info",
    },
    {
        "rule_id": "rule_modifier_25_001",
        "category": "modifier",
        "trigger": "separately identifiable E/M",
        "suggested_code": "modifier 25",
        "severity": "high",
    },
    {
        "rule_id": "rule_icd_001",
        "category": "diagnosis",
        "trigger": "palpitations reported",
        "suggested_code": "R00.2",
        "severity": "medium",
    },
    {
        "rule_id": "rule_icd_002",
        "category": "diagnosis",
        "trigger": "chest pain on exertion",
        "suggested_code": "I20.9",
        "severity": "high",
    },
    {
        "rule_id": "rule_icd_003",
        "category": "diagnosis",
        "trigger": "type 2 diabetes follow-up",
        "suggested_code": "E11.9",
        "severity": "medium",
    },
    {
        "rule_id": "rule_icd_004",
        "category": "diagnosis",
        "trigger": "essential hypertension",
        "suggested_code": "I10",
        "severity": "low",
    },
    {
        "rule_id": "rule_lab_001",
        "category": "laboratory",
        "trigger": "lipid panel ordered",
        "suggested_code": "80061",
        "severity": "low",
    },
    {
        "rule_id": "rule_lab_002",
        "category": "laboratory",
        "trigger": "HbA1c drawn",
        "suggested_code": "83036",
        "severity": "low",
    },
    {
        "rule_id": "rule_imaging_001",
        "category": "imaging",
        "trigger": "chest x-ray performed",
        "suggested_code": "71046",
        "severity": "medium",
    },
    {
        "rule_id": "rule_imaging_002",
        "category": "imaging",
        "trigger": "echocardiogram ordered",
        "suggested_code": "93306",
        "severity": "high",
    },
    {
        "rule_id": "rule_preventive_001",
        "category": "preventive",
        "trigger": "annual wellness visit",
        "suggested_code": "G0438",
        "severity": "info",
    },
    {
        "rule_id": "rule_injection_001",
        "category": "procedure",
        "trigger": "influenza vaccine administered",
        "suggested_code": "90686",
        "severity": "low",
    },
    {
        "rule_id": "rule_missing_dx_001",
        "category": "missing-dx",
        "trigger": "documentation lacks diagnosis linkage",
        "suggested_code": "REVIEW",
        "severity": "critical",
    },
    {
        "rule_id": "rule_overlap_001",
        "category": "duplicate",
        "trigger": "duplicate service on same date",
        "suggested_code": "DENY",
        "severity": "high",
    },
]


# -----------------------------------------------------------------------------
# Encounter generation
# -----------------------------------------------------------------------------


# Encounter templates. Each template is a tuple (is_flagged, clinical_note,
# list_of_rule_ids_to_attach). The clinical_note embeds the trigger phrase
# for each rule_id verbatim, so the ground truth is recoverable from the
# note content alone.

_TEMPLATES: list[tuple[bool, str, list[str]]] = [
    (
        True,
        "Patient presents for established patient moderate complexity. "
        "ECG performed in office due to palpitations reported. "
        "Documentation supports a separately identifiable E/M; "
        "modifier 25 applied. Lipid panel ordered for cardiovascular "
        "risk stratification.",
        ["rule_em_001", "rule_ecg_001", "rule_icd_001", "rule_modifier_25_001", "rule_lab_001"],
    ),
    (
        True,
        "New patient low complexity visit. Patient reports chest pain on "
        "exertion. ECG performed in office; rhythm strip reviewed. "
        "Echocardiogram ordered for further workup.",
        ["rule_em_002", "rule_icd_002", "rule_ecg_001", "rule_ecg_002", "rule_imaging_002"],
    ),
    (
        True,
        "Established patient high complexity. Type 2 diabetes follow-up "
        "with HbA1c drawn. Essential hypertension re-assessed. "
        "Influenza vaccine administered during visit.",
        [
            "rule_em_003",
            "rule_icd_003",
            "rule_lab_002",
            "rule_icd_004",
            "rule_injection_001",
        ],
    ),
    (
        True,
        "Annual wellness visit completed. Patient with essential hypertension. "
        "Documentation lacks diagnosis linkage for the E/M code billed.",
        ["rule_preventive_001", "rule_icd_004", "rule_missing_dx_001"],
    ),
    (
        True,
        "Follow-up for essential hypertension. Lipid panel ordered. "
        "Duplicate service on same date flagged by billing system.",
        ["rule_icd_004", "rule_lab_001", "rule_overlap_001"],
    ),
    (
        True,
        "Acute visit: chest pain on exertion, ECG performed in office. "
        "Rhythm strip reviewed; no acute changes. Chest x-ray performed "
        "to rule out cardiopulmonary cause.",
        ["rule_icd_002", "rule_ecg_001", "rule_ecg_002", "rule_imaging_001"],
    ),
    (
        True,
        "Established patient moderate complexity. Palpitations reported; "
        "ECG performed in office and reviewed. Documentation lacks "
        "diagnosis linkage for the rhythm strip code.",
        ["rule_em_001", "rule_icd_001", "rule_ecg_001", "rule_missing_dx_001"],
    ),
    (
        True,
        "Type 2 diabetes follow-up. HbA1c drawn; result pending. "
        "Influenza vaccine administered. Essential hypertension stable.",
        ["rule_icd_003", "rule_lab_002", "rule_injection_001", "rule_icd_004"],
    ),
    (
        False,
        "Brief medication refill. No acute issues. Patient stable.",
        [],
    ),
    (
        False,
        "Suture removal visit. Wound healing well. No new complaints.",
        [],
    ),
    (
        True,
        "New patient low complexity. Chest pain on exertion; ECG "
        "performed in office. Documentation lacks diagnosis linkage "
        "for the procedure code billed.",
        ["rule_em_002", "rule_icd_002", "rule_ecg_001", "rule_missing_dx_001"],
    ),
    (
        True,
        "Established patient moderate complexity. Echocardiogram ordered "
        "for evaluation of palpitations reported. Essential hypertension "
        "noted. Lipid panel ordered.",
        [
            "rule_em_001",
            "rule_imaging_002",
            "rule_icd_001",
            "rule_icd_004",
            "rule_lab_001",
        ],
    ),
    (
        True,
        "Duplicate service on same date. Patient seen for annual "
        "wellness visit and a separate sick visit billed the same day.",
        ["rule_preventive_001", "rule_overlap_001"],
    ),
    (
        True,
        "Established patient high complexity. Type 2 diabetes follow-up; "
        "HbA1c drawn. Chest x-ray performed for cough workup.",
        ["rule_em_003", "rule_icd_003", "rule_lab_002", "rule_imaging_001"],
    ),
    (
        True,
        "Established patient moderate complexity. Influenza vaccine "
        "administered. Essential hypertension stable.",
        ["rule_em_001", "rule_injection_001", "rule_icd_004"],
    ),
]


# Cached generated data (deterministic via fixed seed)
_train_cache: list[dict] | None = None
_val_cache: list[dict] | None = None


def _build_encounter(idx: int, is_flagged: bool, note: str, rule_ids: list[str]) -> dict:
    rules = []
    for rid in rule_ids:
        rule = next((r for r in RULES if r["rule_id"] == rid), None)
        if rule is None:
            continue
        rules.append(dict(rule))
    return {
        "encounter_id": f"enc_{idx:04d}",
        "is_flagged": is_flagged,
        "clinical_note": note,
        "claim": {
            "cpt_codes": [r["suggested_code"] for r in rules if r["suggested_code"][0].isdigit()],
            "icd10_codes": [r["suggested_code"] for r in rules if r["suggested_code"].startswith(("R", "I", "E"))],
        },
        "rules": rules,
    }


def _split_data(
    train_seed: int = 1729, train_n: int = 100, val_n: int = 50
) -> tuple[list[dict], list[dict]]:
    """Generate ``train_n`` train and ``val_n`` val encounters deterministically.

    The 15 templates above cycle to fill the requested count, with small
    variations to keep the rules attached to each encounter deterministic
    given the seed. Train and val are disjoint by index.
    """
    rng_train = random.Random(train_seed)
    rng_val = random.Random(train_seed + 1)

    def expand(rng: random.Random, n: int, offset: int) -> list[dict]:
        out: list[dict] = []
        for i in range(n):
            tmpl_idx = (offset + i) % len(_TEMPLATES)
            is_flagged, note, rule_ids = _TEMPLATES[tmpl_idx]
            # For train, occasionally drop a random non-last rule to make
            # harder cases. The spec pins the dataset at 100/50; the
            # difficulty variation is what makes the baseline < optimal
            # so the optimizer has real work to do.
            if rng.random() < 0.15 and len(rule_ids) > 1:
                drop = rng.randrange(len(rule_ids) - 1)
                rule_ids = rule_ids[:drop] + rule_ids[drop + 1:]
            out.append(_build_encounter(i + offset, is_flagged, note, rule_ids))
        return out

    train = expand(rng_train, train_n, offset=0)
    val = expand(rng_val, val_n, offset=10000)
    return train, val


def get_train() -> list[dict]:
    global _train_cache
    if _train_cache is None:
        _train_cache, _val_cache = _split_data()
    assert _train_cache is not None
    return _train_cache


def get_val() -> list[dict]:
    global _val_cache
    if _val_cache is None:
        _train_cache, _val_cache = _split_data()
    assert _val_cache is not None
    return _val_cache


# -----------------------------------------------------------------------------
# Ground truth
# -----------------------------------------------------------------------------


def ground_truth_for(encounter: dict) -> list[dict]:
    """Derive ground-truth findings from the encounter's rules.

    For each rule attached to the encounter, emit a finding whose
    clinical_evidence_quote is the rule's trigger phrase. The encounter's
    clinical_note is guaranteed to contain each trigger verbatim.
    """
    out: list[dict] = []
    for i, rule in enumerate(encounter.get("rules", [])):
        out.append(
            {
                "finding_id": f"gt{i}",
                "category": rule["category"],
                "severity": rule["severity"],
                "suggested_code": rule["suggested_code"],
                "rule_id": rule["rule_id"],
                "clinical_evidence_quote": rule["trigger"],
            }
        )
    return out


# -----------------------------------------------------------------------------
# Disk serialization
# -----------------------------------------------------------------------------


def load_split(path: str | Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_split(path: str | Path, encounters: list[dict]) -> None:
    # Inject ground-truth so the optimizer can score end-to-end from disk.
    enriched = []
    for enc in encounters:
        enriched.append({**enc, "ground_truth": ground_truth_for(enc)})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)


def generate_train_split(path: str | Path) -> list[dict]:
    train = get_train()
    write_split(path, train)
    return train


def generate_val_split(path: str | Path) -> list[dict]:
    val = get_val()
    write_split(path, val)
    return val
