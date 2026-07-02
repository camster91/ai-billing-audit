"""Tests for the rule_id alias canonicalizer in ``ai_billing_audit.auditor``.

The v12 prompt instructs the LLM to emit rule_ids in the
``rule_ahcip_*`` namespace. In practice the model emits generic labels
like ``MOD-25-SAME-DAY-001`` or ``DX-MATCH-PROCEDURE`` because the JSON
schema allows any string. The post-validation canonicalizer
(``_canonicalize_rule_id``) maps those back to the canonical namespace
so the 1-page report, the SOMB dollar map, and the LLM-side alias
table all agree.

What's pinned
-------------
* Lower-case, upper-case, mixed-case inputs all canonicalize to the
  same canonical rule_id (case-insensitive matching).
* Unknown rule_ids pass through unchanged (the validator still
  accepts any string for ``rule_id``).
* Empty / whitespace inputs return empty / original unchanged.
* Pattern ordering matters: ``MOD-25-SAME-DAY-001`` maps to
  ``rule_ahcip_same_day_conflict``, not ``rule_ahcip_modifier_25_unlock``
  (more specific pattern wins).
* Every alias resolves to a key that exists in
  ``SOMB_DOLLAR_BY_RULE`` (no orphans in the canonical namespace).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure src/ is on the path so ``import ai_billing_audit.auditor``
# resolves to the package under development.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_billing_audit.auditor import (  # noqa: E402
    _RULE_ID_ALIASES,
    _canonicalize_rule_id,
)


# --- helpers --------------------------------------------------------------


def _import_shadow_audit():
    """Import the shadow runner so we can cross-check SOMB dollar map coverage."""
    sys.path.insert(0, str(ROOT / "scripts"))
    spec_mod = __import__("importlib.util", fromlist=["spec_from_file_location"])
    spec = spec_mod.spec_from_file_location(
        "shadow_audit", str(ROOT / "scripts" / "shadow_audit.py")
    )
    if spec is None or spec.loader is None:
        pytest.skip("shadow_audit.py not importable for cross-check")
    mod = spec_mod.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- canonicalizer core ---------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # --- Modifier-25 family ---
        ("MOD-25-SAME-DAY-001", "rule_ahcip_same_day_conflict"),
        ("MOD-25-E&M-WITH-PROCEDURE", "rule_ahcip_modifier_25_unlock"),
        ("E_M_PROCEDURE_MODIFIER", "rule_ahcip_modifier_25_unlock"),
        ("MOD-STD-001", "rule_ahcip_modifier_25_unlock"),
        # --- CMGP / chronic-disease ---
        ("CMGP-rule-001", "rule_ahcip_cmgp"),
        ("chronic-disease-management", "rule_ahcip_cmgp"),
        # --- Annual physical / preventive / non-insured ---
        ("MEDICARE_AWV_CODE_REQUIREMENT", "rule_ahcip_non_insured_service"),
        ("AWV-DOC-002", "rule_ahcip_non_insured_service"),
        ("Z00_00_NO_ABNORMAL_FINDINGS", "rule_ahcip_non_insured_service"),
        ("ZCODE-PREVENTIVE-VISIT", "rule_ahcip_non_insured_service"),
        ("annual_physical_check", "rule_ahcip_non_insured_service"),
        # --- Missing procedure ---
        ("missing_procedure_v2", "rule_ahcip_missing_procedure"),
        # --- Global window ---
        ("SCOPE-OF-PRACTICE-004", "rule_ahcip_global_window"),
        ("global_window_post_op", "rule_ahcip_global_window"),
        # --- Lab coverage ---
        ("lab_coverage_avoidance", "rule_ahcip_lab_coverage"),
        ("lab.order.no.draw", "rule_ahcip_lab_order_no_draw"),
        # --- Telehealth ---
        ("telehealth_premium_005", "rule_ahcip_telehealth_premium"),
        ("TELEHEALTH-CHECK-001", "rule_ahcip_telehealth"),
        # --- Psychotherapy time ---
        ("psychotherapy_time_undercode", "rule_ahcip_psychotherapy_time"),
        ("08.19-time-rule", "rule_ahcip_psychotherapy_time"),
        # --- Consultation / referring NPI ---
        ("REFERRING-NPI-REQUIRED-002", "rule_ahcip_referring_npi"),
        ("referring_provider_missing", "rule_ahcip_referring_npi"),
        ("consultation_missed_006", "rule_ahcip_consultation_missed"),
        # --- E/M level ---
        ("som_b_03_04A_scope", "rule_ahcip_em_level"),
        ("em_level_upcode_risk", "rule_ahcip_em_level_upcode"),
        ("undercoded-rule", "rule_ahcip_em_level_upcode"),
        # --- DX linkage (separate from em_level) ---
        ("DX_DOCUMENTATION_SUPPORT", "rule_ahcip_dx_linkage"),
        ("dx-linkage-rule", "rule_ahcip_dx_linkage"),
        ("E78.5-REQUIRE-EXPLICIT-DX-005", "rule_ahcip_dx_linkage"),
        ("DIAGNOSIS_CODE_DOCUMENTATION_SUPPORT", "rule_ahcip_dx_linkage"),
        # --- DX routed to em_level (generic DX / gender / age) ---
        ("DX-MATCH-PROCEDURE", "rule_ahcip_em_level"),
        ("DX_GENDER_CONSISTENCY", "rule_ahcip_em_level"),
        ("RULE-DX-MATCH-005", "rule_ahcip_em_level"),
        ("PRIMARY-DX-002", "rule_ahcip_em_level"),
        ("diagnosis-encounter-alignment", "rule_ahcip_em_level"),
        # --- 03.05A alternative-payment ---
        ("03.05A.alternative-payment", "rule_ahcip_03_05A_alternative"),
        # --- Already canonical: pass-through ---
        ("rule_ahcip_cmgp", "rule_ahcip_cmgp"),
        ("rule_ahcip_em_level", "rule_ahcip_em_level"),
        # --- Unknown: pass-through unchanged ---
        ("unknown-rule-123", "unknown-rule-123"),
        ("FUTURE-RULE-2027-001", "FUTURE-RULE-2027-001"),
    ],
)
def test_canonicalize_rule_id(raw, expected):
    assert _canonicalize_rule_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\n", "\t"])
def test_canonicalize_rule_id_empty_or_whitespace(raw):
    # Empty / whitespace inputs return unchanged (no alias matches).
    assert _canonicalize_rule_id(raw) == raw


def test_canonicalize_rule_id_case_insensitive():
    # The alias regex is anchored to re.IGNORECASE-equivalent matching
    # via lowercasing the input first; upper / mixed-case should
    # canonicalize the same way as lower.
    a = _canonicalize_rule_id("MOD-25-SAME-DAY-001")
    b = _canonicalize_rule_id("mod-25-same-day-001")
    c = _canonicalize_rule_id("Mod-25-Same-Day-001")
    assert a == b == c == "rule_ahcip_same_day_conflict"


def test_pattern_order_mod25_sameday_before_mod25():
    """``MOD-25-SAME-DAY-001`` must map to ``same_day_conflict``,
    NOT ``modifier_25_unlock`` — verifies the order in
    ``_RULE_ID_ALIASES`` is correct.
    """
    got = _canonicalize_rule_id("MOD-25-SAME-DAY-001")
    assert got == "rule_ahcip_same_day_conflict"


def test_pattern_order_dx_documentation_before_em_level():
    """``DX_DOCUMENTATION_SUPPORT`` must map to ``dx_linkage``,
    NOT the generic ``em_level`` — DX-documentation is a dx_linkage
    bucket, not an E/M level bucket.
    """
    got = _canonicalize_rule_id("DX_DOCUMENTATION_SUPPORT")
    assert got == "rule_ahcip_dx_linkage"


# --- cross-check with shadow runner's SOMB map ----------------------------


def test_every_alias_target_has_somb_dollar_map_entry():
    """Every canonical rule_id emitted by the alias map must have a
    SOMB-DOLLAR entry in the shadow runner so the 1-page report
    can render a real dollar rate (not "$0").
    """
    shadow = _import_shadow_audit()
    aliases_targets = {target for _, target in _RULE_ID_ALIASES}
    orphans = aliases_targets - set(shadow.SOMB_DOLLAR_BY_RULE.keys())
    assert not orphans, (
        f"Alias map emits these canonical rule_ids that have no SOMB "
        f"dollar rate in shadow_audit.py: {sorted(orphans)}"
    )


def test_every_alias_target_has_somb_label_entry():
    """Every canonical rule_id must also have a SOMB-friendly label
    in the shadow runner so the 1-page report shows SOMB copy, not
    snake_case internal names.
    """
    shadow = _import_shadow_audit()
    aliases_targets = {target for _, target in _RULE_ID_ALIASES}
    orphans = aliases_targets - set(shadow.SOMB_LABEL_BY_RULE.keys())
    assert not orphans, (
        f"Alias map emits these canonical rule_ids that have no "
        f"friendly label in shadow_audit.py: {sorted(orphans)}"
    )


def test_dollar_map_and_label_map_in_sync():
    """Dollar map and label map must cover the SAME set of canonical
    rule_ids — adding one without the other is a silent UX bug.
    """
    shadow = _import_shadow_audit()
    diff = set(shadow.SOMB_DOLLAR_BY_RULE.keys()) ^ set(
        shadow.SOMB_LABEL_BY_RULE.keys()
    )
    assert not diff, f"Dollar/label map mismatch (symmetric): {sorted(diff)}"


def test_friendly_rule_label_handles_empty_and_unknown():
    shadow = _import_shadow_audit()
    assert shadow._friendly_rule_label("") == ""
    # Unknown canonical name falls back to a title-cased version of
    # the snake_case stripped of the rule_ahcip_ prefix.
    got = shadow._friendly_rule_label("rule_ahcip_some_new_future_rule")
    assert "Some New Future Rule" in got
    # Known canonical name resolves to the registered SOMB label.
    got = shadow._friendly_rule_label("rule_ahcip_modifier_25_unlock")
    assert "SOMB GR 1.4" in got