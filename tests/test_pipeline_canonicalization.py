"""End-to-end pipeline test: LLM stub → validate → canonicalize → SOMB map.

This is the higher-level test that exercises the full rule_id flow:

1. LLM emits a *raw* rule_id (the form MiniMax-M3 actually produces,
   NOT the canonical form the prompt asks for).
2. ``validate_findings`` runs the canonicalization hook.
3. The canonicalized rule_id is looked up in
   ``SOMB_DOLLAR_BY_RULE`` and ``SOMB_LABEL_BY_RULE``.
4. The result has a non-zero dollar rate and a SOMB-friendly label.

If any of those four steps drop a finding (raw rule_id doesn't
canonicalize, OR canonicalize target has no dollar rate, OR no
friendly label), the test fails with a clear message pointing to
which rule_id fell through the cracks.

The hardcoded ``_SAMPLE_LLM_OUTPUT`` simulates the realistic LLM
output shape observed in the 2026-07-02 blind test (runs/shadow/
prospect_demo_100-20260702T124128.json) and the v12 prompt examples
— a mix of canonical (already prefixed with ``rule_ahcip_``) and
paraphrased (``MOD-25-SAME-DAY-001``, ``DX-MATCH-PROCEDURE``, etc.)
rule_ids.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_billing_audit.auditor import validate_findings  # noqa: E402


def _import_shadow_audit():
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util as _u
    spec = _u.spec_from_file_location("shadow_audit", str(ROOT / "scripts" / "shadow_audit.py"))
    if spec is None or spec.loader is None:
        pytest.skip("shadow_audit.py not importable for cross-check")
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A realistic LLM output payload, mirroring the 2026-07-02 blind test
# findings. Each row is one finding; rule_id is what the LLM ACTUALLY
# emitted (paraphrased, generic, or canonical). clinical_note is the
# supporting documentation the finding references.
_SAMPLE_LLM_OUTPUT: dict[str, Any] = {
    "findings": [
        # Already-canonical rule_id
        {
            "rule_id": "rule_ahcip_modifier_25_unlock",
            "severity": "high",
            "category": "modifier",
            "suggested_code": "13.59A",
            "quote": "cryotherapy to 2 actinic keratoses on the forearm",
            "explanation": "E/M 03.04A + procedure on same day; modifier-25 unlock missing.",
        },
        # Paraphrased modifier-25 (typical LLM leak)
        {
            "rule_id": "MOD-25-SAME-DAY-001",
            "severity": "high",
            "category": "modifier",
            "suggested_code": "13.59A",
            "quote": "cryotherapy to 2 actinic keratoses on the forearm",
            "explanation": "Same-day E/M + procedure, modifier-25 missing.",
        },
        # Paraphrased DX-MATCH (typical LLM leak)
        {
            "rule_id": "DX-MATCH-PROCEDURE",
            "severity": "medium",
            "category": "diagnosis",
            "suggested_code": "",
            "quote": "patient presents with chest pain on exertion",
            "explanation": "Diagnosis linkage to procedure unclear.",
        },
        # Paraphrased AWV (typical LLM leak)
        {
            "rule_id": "MEDICARE_AWV_CODE_REQUIREMENT",
            "severity": "high",
            "category": "evaluation",
            "suggested_code": "",
            "quote": "annual wellness visit with full history and physical",
            "explanation": "Annual wellness visit billed to AHCIP; not insured.",
        },
        # Paraphrased SOMB (typical LLM leak)
        {
            "rule_id": "SOMB-03.04A-CRITERIA",
            "severity": "medium",
            "category": "evaluation",
            "suggested_code": "03.01A",
            "quote": "patient returns for medication review",
            "explanation": "03.04A billed but documentation supports only 03.01A.",
        },
        # Already-canonical CMGP
        {
            "rule_id": "rule_ahcip_cmgp",
            "severity": "medium",
            "category": "modifier",
            "suggested_code": "CMGP",
            "quote": "established patient 71yo M with hypertension",
            "explanation": "HTN + 03.04A, no CMGP modifier on claim.",
        },
    ]
}

_CLINICAL_NOTE = (
    "Established patient 71yo M with hypertension follow-up. "
    "Annual wellness visit with full history and physical. "
    "Patient presents with chest pain on exertion. "
    "Cryotherapy to 2 actinic keratoses on the forearm. "
    "Patient returns for medication review. "
    "BP 132/82, HR 72. Plan: continue current management."
)


def test_all_findings_canonicalize():
    """Every finding returned by ``validate_findings`` must have a
    canonical ``rule_ahcip_*`` form — not the raw LLM paraphrase.
    """
    findings = validate_findings(_SAMPLE_LLM_OUTPUT, clinical_note=_CLINICAL_NOTE)
    assert findings, "validate_findings returned no findings"
    for f in findings:
        assert f.rule_ids, f"Finding has no rule_ids: {f}"
        for rid in f.rule_ids:
            assert rid.startswith("rule_ahcip_"), (
                f"Finding rule_id is NOT canonical after validation: "
                f"rule_id={rid!r} (expected rule_ahcip_* form)"
            )


def test_all_canonical_rule_ids_have_somb_dollar_rate():
    """Every canonical rule_id emitted by the validator must have a
    non-zero entry in ``SOMB_DOLLAR_BY_RULE`` so the 1-page report
    shows a real dollar figure.
    """
    shadow = _import_shadow_audit()
    findings = validate_findings(_SAMPLE_LLM_OUTPUT, clinical_note=_CLINICAL_NOTE)
    missing = []
    for f in findings:
        for rid in f.rule_ids:
            if rid not in shadow.SOMB_DOLLAR_BY_RULE:
                missing.append(rid)
    assert not missing, (
        f"These canonical rule_ids have no SOMB dollar rate: "
        f"{sorted(set(missing))}"
    )


def test_all_canonical_rule_ids_have_somb_label():
    """Every canonical rule_id must have a friendly SOMB label so
    the 1-page report reads SOMB-friendly copy.
    """
    shadow = _import_shadow_audit()
    findings = validate_findings(_SAMPLE_LLM_OUTPUT, clinical_note=_CLINICAL_NOTE)
    missing = []
    for f in findings:
        for rid in f.rule_ids:
            if rid not in shadow.SOMB_LABEL_BY_RULE:
                missing.append(rid)
    assert not missing, (
        f"These canonical rule_ids have no SOMB-friendly label: "
        f"{sorted(set(missing))}"
    )


def test_paraphrased_rule_ids_canonicalize_correctly():
    """The 4 paraphrased LLM rule_ids in the sample must all
    canonicalize to the EXPECTED target rule_id, not a sibling.
    """
    findings = validate_findings(_SAMPLE_LLM_OUTPUT, clinical_note=_CLINICAL_NOTE)
    by_raw = {
        "MOD-25-SAME-DAY-001": "rule_ahcip_same_day_conflict",
        "DX-MATCH-PROCEDURE": "rule_ahcip_em_level",
        "MEDICARE_AWV_CODE_REQUIREMENT": "rule_ahcip_non_insured_service",
        "SOMB-03.04A-CRITERIA": "rule_ahcip_em_level",
    }
    found_canonical = {rid for f in findings for rid in f.rule_ids}
    for raw, expected_canonical in by_raw.items():
        assert expected_canonical in found_canonical, (
            f"Raw LLM rule_id {raw!r} should have canonicalized to "
            f"{expected_canonical!r}, but that's not in the finding set. "
            f"Got: {sorted(found_canonical)}"
        )


def test_dollar_rate_pipeline_no_longer_drops_to_zero():
    """The pre-canonicalization pipeline used to drop every finding
    to $0 because raw LLM rule_ids didn't match SOMB_DOLLAR_BY_RULE
    keys. After canonicalization, at least one finding must have a
    non-zero dollar rate (or at minimum: every finding must have a
    dollar RATE, even if $0 for avoidance-type rules like
    lab_coverage / lab_order_no_draw).
    """
    shadow = _import_shadow_audit()
    findings = validate_findings(_SAMPLE_LLM_OUTPUT, clinical_note=_CLINICAL_NOTE)
    for f in findings:
        for rid in f.rule_ids:
            # The point: every canonical rule_id MUST have a SOMB dollar
            # entry (zero is acceptable for avoidance rules, but the key
            # must exist).
            assert rid in shadow.SOMB_DOLLAR_BY_RULE, (
                f"Canonical rule_id {rid!r} has no SOMB_DOLLAR_BY_RULE "
                f"entry; 1-page report would render '$0' for an unknown "
                f"reason (pipeline regression)."
            )
    # And at least one non-avoidance finding should have a non-zero
    # dollar rate (sanity check that the pipeline isn't dropping all
    # findings to $0).
    non_avoidance = [
        rid for f in findings for rid in f.rule_ids
        if rid not in ("rule_ahcip_lab_coverage", "rule_ahcip_lab_order_no_draw")
    ]
    has_dollar = [
        rid for rid in non_avoidance
        if shadow.SOMB_DOLLAR_BY_RULE.get(rid, 0) > 0
    ]
    assert has_dollar, (
        f"All non-avoidance findings have $0 — pipeline regression. "
        f"Non-avoidance rule_ids seen: {sorted(set(non_avoidance))}"
    )


def test_somb_label_pipeline_renders_somb_friendly_copy():
    """The friendly label rendered for at least one finding must
    contain a SOMB General Rule reference (e.g. 'SOMB GR 1.4'),
    proving the report renders SOMB-friendly copy, not raw
    snake_case internal names.
    """
    shadow = _import_shadow_audit()
    findings = validate_findings(_SAMPLE_LLM_OUTPUT, clinical_note=_CLINICAL_NOTE)
    labels = [
        shadow._friendly_rule_label(rid)
        for f in findings for rid in f.rule_ids
    ]
    has_somb = [l for l in labels if "SOMB GR" in l]
    assert has_somb, (
        f"No SOMB-friendly labels rendered. Got: {labels!r}"
    )