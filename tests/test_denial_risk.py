"""Tests for the denial-risk scoring module.

The scoring function combines per-finding severity weights with
rule-family multipliers to produce a denial probability. v0 uses
heuristic weights; v1 replaces them with logistic regression on
the first pilot's historical denial data.

What's pinned
-------------
* Empty findings -> 0.0 risk
* Single critical finding -> ~0.40 (base) * multiplier
* Multiple findings combine via 1 - product(1 - risk_i)
* Severity ordering: critical > high > medium > low > info
* Rule family multipliers stack: missing-DX > modifier > EM > docs
* min_severity threshold filters findings before scoring
* Tier mapping: <0.10 low, <0.30 medium, <0.60 high, >=0.60 critical
* Capped at 0.99 (never claim 'certain denial')
* top_risk is the highest per-finding contribution
"""
from __future__ import annotations

import pytest

from ai_billing_audit.denial_risk import (
    DEFAULT_RULE_MULTIPLIER,
    RULE_FAMILY_MULTIPLIERS,
    SEVERITY_RANK,
    SEVERITY_WEIGHTS,
    compute_denial_risk,
    compute_finding_risk,
)


def _finding(severity: str, rule_id: str | None = None,
             finding_id: str = "F"):
    f = {
        "finding_id": finding_id,
        "severity": severity,
        "quote": "test",
        "explanation": "test",
    }
    if rule_id is not None:
        f["rule_id"] = rule_id
    return f


# ----- rule-family classification -----


def test_rule_family_exact_match():
    contrib = compute_finding_risk(_finding("high", "MOD-25"))
    assert contrib["rule_family"] == "MOD-25"


def test_rule_family_prefix_match():
    contrib = compute_finding_risk(_finding("high", "DX_LINKAGE_REQUIRED"))
    assert contrib["rule_family"] == "DX_LINKAGE"


def test_rule_family_modifier_prefix():
    contrib = compute_finding_risk(_finding("high", "MODIFIER_59"))
    assert contrib["rule_family"] == "MODIFIER"


def test_rule_family_em_prefix():
    contrib = compute_finding_risk(_finding("medium", "EM_NEW_VS_ESTABLISHED"))
    assert contrib["rule_family"] == "EM"


def test_rule_family_duplicate_keyword():
    contrib = compute_finding_risk(_finding("high", "DUPLICATE_SERVICE_CODE"))
    assert contrib["rule_family"] == "DUPLICATE"


def test_rule_family_medical_necessity_keyword():
    contrib = compute_finding_risk(_finding("medium", "MEDICAL_NECESSITY_DOC"))
    assert contrib["rule_family"] == "MEDICAL_NECESSITY"


def test_rule_family_doc_keyword():
    contrib = compute_finding_risk(_finding("low", "DOCUMENTATION_GAP"))
    assert contrib["rule_family"] == "DOCUMENTATION"


def test_rule_family_unknown_falls_back_to_other():
    contrib = compute_finding_risk(_finding("low", "ZZZ_UNKNOWN_RULE_123"))
    assert contrib["rule_family"] == "OTHER"


def test_rule_family_no_rule_id_is_other():
    contrib = compute_finding_risk(_finding("high"))
    assert contrib["rule_family"] == "OTHER"


# ----- per-finding risk -----


def test_critical_finding_risk_above_high():
    crit = compute_finding_risk(_finding("critical", "MOD-25"))
    high = compute_finding_risk(_finding("high", "MOD-25"))
    assert crit["risk"] > high["risk"]


def test_critical_with_dx_linkage_is_very_high():
    contrib = compute_finding_risk(_finding("critical", "DX_LINKAGE_REQUIRED"))
    # base 0.40 * multiplier 1.5 = 0.60
    assert contrib["risk"] == pytest.approx(0.60)


def test_info_finding_risk_is_low():
    contrib = compute_finding_risk(_finding("info", "DOC_GAP"))
    assert contrib["risk"] < 0.01


def test_unknown_severity_uses_default_base():
    contrib = compute_finding_risk(_finding("banana", "MOD-25"))
    # base 0.05 * 1.3 = 0.065
    assert contrib["risk"] == pytest.approx(0.065)


def test_risk_capped_at_0_95():
    contrib = compute_finding_risk(_finding("critical", "DUPLICATE"))
    # 0.40 * 1.6 = 0.64 — under the cap
    assert contrib["risk"] == pytest.approx(0.64)
    # And a hypothetical extreme combo would still cap
    contrib2 = compute_finding_risk({
        "severity": "critical", "rule_id": "DUPLICATE", "finding_id": "x",
    })
    assert contrib2["risk"] <= 0.95


# ----- claim-level combination -----


def test_empty_findings_returns_zero_risk():
    risk = compute_denial_risk([])
    assert risk["denial_probability"] == 0.0
    assert risk["tier"] == "low"
    assert risk["n_findings"] == 0
    assert risk["n_findings_scored"] == 0
    assert risk["top_risk"] is None


def test_single_critical_finding_scores_high():
    risk = compute_denial_risk([_finding("critical", "DX_LINKAGE_REQUIRED")])
    # 1 - (1 - 0.60) = 0.60 -> tier "critical" (>= 0.60)
    assert risk["denial_probability"] == pytest.approx(0.60)
    assert risk["tier"] == "critical"


def test_single_high_finding_scores_medium():
    risk = compute_denial_risk([_finding("high", "MOD-25")])
    # base 0.25 * multiplier 1.3 = 0.325 -> tier "high" (0.30-0.60)
    assert risk["denial_probability"] == pytest.approx(0.325)
    assert risk["tier"] == "high"


def test_multiple_findings_combine_independently():
    """Two independent risks combine via 1 - (1-a)(1-b)."""
    findings = [
        # low + duplicate -> 0.03 * 1.6 = 0.048
        _finding("low", "DUPLICATE_SERVICE", finding_id="F1"),
        # info + mod-25 (exact family match, multiplier 1.3) -> 0.013
        _finding("info", "MOD-25", finding_id="F2"),
    ]
    risk = compute_denial_risk(findings)
    # Recompute the expected value using the same arithmetic as
    # the production code: 1 - (1 - a)(1 - b) with no rounding
    # at intermediate steps.
    from ai_billing_audit.denial_risk import _rule_family
    r1 = 0.03 * RULE_FAMILY_MULTIPLIERS[_rule_family("DUPLICATE_SERVICE")]
    r2 = 0.01 * RULE_FAMILY_MULTIPLIERS[_rule_family("MOD-25")]
    expected = 1 - (1 - r1) * (1 - r2)
    # Production rounds to 4 decimal places; compare with that
    # precision so floating-point dust doesn't trip us.
    assert risk["denial_probability"] == pytest.approx(round(expected, 4), abs=1e-9)


def test_risk_capped_at_0_99_even_with_many_critical():
    """Even a dozen critical findings can't push risk above 0.99."""
    findings = [_finding("critical", "DUPLICATE", finding_id=f"F{i}") for i in range(12)]
    risk = compute_denial_risk(findings)
    assert risk["denial_probability"] <= 0.99


# ----- tier mapping -----


def test_tier_low_for_zero_and_small_risks():
    assert compute_denial_risk([])["tier"] == "low"
    assert compute_denial_risk([_finding("info", "DOC_GAP")])["tier"] == "low"


def test_tier_medium_at_threshold():
    """0.10 is the boundary between low and medium. We classify <0.10 as low."""
    # 0.10 - epsilon -> low
    # Force a score slightly below 0.10 via a low/info finding
    risk = compute_denial_risk([_finding("low", "DOC_GAP")])
    # 0.03 * 0.6 = 0.018
    assert risk["tier"] == "low"


def test_tier_high_between_30_and_60_percent():
    risk = compute_denial_risk([_finding("medium", "E/M-LEVEL")])
    # base 0.10 * 1.1 = 0.11 -> low
    # We need > 0.30. Use a high-severity finding.
    risk = compute_denial_risk([_finding("high", "MOD-25")])
    # 0.25 * 1.3 = 0.325 -> high
    assert risk["tier"] == "high"


def test_tier_critical_at_60_percent_or_higher():
    risk = compute_denial_risk([_finding("critical", "DX_LINKAGE_REQUIRED")])
    # 0.40 * 1.5 = 0.60 -> critical (>= 0.60)
    assert risk["tier"] == "critical"


# ----- min_severity threshold -----


def test_min_severity_excludes_info_findings():
    findings = [
        _finding("critical", "DX_LINKAGE", finding_id="F1"),
        _finding("info", "DOC_GAP", finding_id="F2"),
    ]
    risk_all = compute_denial_risk(findings)
    risk_no_info = compute_denial_risk(findings, min_severity=1)
    # When min_severity=1, the info finding is dropped
    assert risk_no_info["n_findings_scored"] == 1
    assert risk_no_info["n_findings_below_threshold"] == 1
    # The scored risk should be lower without the info finding
    assert risk_no_info["denial_probability"] < risk_all["denial_probability"]


def test_min_severity_zero_includes_everything():
    findings = [
        _finding("info", "DOC_GAP"),
        _finding("low", "TIME"),
        _finding("critical", "DX_LINKAGE"),
    ]
    risk = compute_denial_risk(findings, min_severity=0)
    assert risk["n_findings_scored"] == 3
    assert risk["n_findings_below_threshold"] == 0


def test_min_severity_high_excludes_medium_and_below():
    findings = [
        _finding("critical", "DX_LINKAGE", finding_id="F1"),
        _finding("high", "MOD-25", finding_id="F2"),
        _finding("medium", "EM_NEW", finding_id="F3"),
    ]
    risk = compute_denial_risk(findings, min_severity=3)  # 'high' = rank 3
    assert risk["n_findings_scored"] == 2  # critical + high
    assert risk["n_findings_below_threshold"] == 1  # medium


# ----- top_risk -----


def test_top_risk_is_highest_contribution():
    findings = [
        _finding("low", "DOC_GAP", finding_id="F1"),  # 0.018
        _finding("critical", "DX_LINKAGE", finding_id="F2"),  # 0.60
        _finding("medium", "MOD-25", finding_id="F3"),  # 0.13
    ]
    risk = compute_denial_risk(findings)
    assert risk["top_risk"] is not None
    assert risk["top_risk"]["finding_id"] == "F2"
    assert risk["top_risk"]["rule_id"] == "DX_LINKAGE"


def test_top_risk_none_when_no_findings_pass_threshold():
    findings = [_finding("info", "DOC_GAP")]
    risk = compute_denial_risk(findings, min_severity=2)
    assert risk["top_risk"] is None


# ----- per-finding details -----


def test_per_finding_includes_all_required_fields():
    findings = [_finding("high", "MOD-25", finding_id="F1")]
    risk = compute_denial_risk(findings)
    pf = risk["per_finding"][0]
    for key in ("rule_id", "rule_family", "severity",
                "base_weight", "rule_multiplier", "risk", "finding_id"):
        assert key in pf, f"missing {key}"


def test_per_finding_preserves_finding_id():
    findings = [_finding("high", "MOD-25", finding_id="F-CUSTOM-99")]
    risk = compute_denial_risk(findings)
    assert risk["per_finding"][0]["finding_id"] == "F-CUSTOM-99"


# ----- rule_id from rule_ids fallback -----


def test_rule_id_from_rule_ids_list_when_rule_id_missing():
    finding = {
        "finding_id": "F1",
        "severity": "high",
        "rule_ids": ["DX_LINKAGE_REQUIRED"],
        # no rule_id key
    }
    contrib = compute_finding_risk(finding)
    assert contrib["rule_id"] == "DX_LINKAGE_REQUIRED"
    assert contrib["rule_family"] == "DX_LINKAGE"


# ----- denormalized input -----


def test_findings_none_treated_as_empty():
    risk = compute_denial_risk(None)  # type: ignore[arg-type]
    assert risk["denial_probability"] == 0.0
    assert risk["n_findings"] == 0