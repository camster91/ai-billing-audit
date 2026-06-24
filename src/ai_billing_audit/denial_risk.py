"""Denial-risk scoring (the second capability in Cam's vision list).

"Scores every claim for denial risk in real time" — this is the
heuristic implementation. v0 doesn't have a real model because we
don't have historical denied-claim labels. The scoring is a
weighted combination of the auditor's findings.

Scoring model
-------------
For each finding:
- severity contributes a base risk:
    critical -> 0.40
    high     -> 0.25
    medium   -> 0.10
    low      -> 0.03
    info     -> 0.01
- rule family contributes a multiplier. Some rules carry higher
  denial risk than their severity suggests (e.g. modifier-25 is
  denied ~50% of the time per published payer data; missing DX
  linkage ~70%). Others are informational and rarely denied
  (e.g. documentation-style rules that the biller can address
  before submission).

Findings are combined via 1 - product(1 - risk_i) so multiple
findings stack but the total stays below 1.0. A clean claim with
zero findings scores 0.0.

Output
------
A single float in [0.0, 1.0] representing the per-claim denial
probability. We also expose the per-finding contribution so the
dashboard can show "this risk comes from rule X (45%)".

v1 path: swap the severity + rule-family tables for a logistic
regression trained on the first pilot clinic's historical
denial data. The module's API (compute_denial_risk) stays the
same; only the scoring weights move.
"""
from __future__ import annotations

from typing import Any


# Base severity weights. These are deliberately conservative — the
# auditor flags high-severity findings because the documentation
# is missing a required element, and payers deny those claims at
# a high rate. The exact percentages are heuristic; v1 replaces
# them with real rates from the first pilot's denial log.
SEVERITY_WEIGHTS: dict[str, float] = {
    "critical": 0.40,
    "high":     0.25,
    "medium":   0.10,
    "low":      0.03,
    "info":     0.01,
}

# Rule-family multipliers. Rules whose absence is almost always
# denied get a multiplier > 1 (e.g. missing DX linkage is denial
# poison). Rules where the biller can fix before submission get a
# multiplier near 1. Documentation-only rules that don't change
# the billed amount get a multiplier < 1.
RULE_FAMILY_MULTIPLIERS: dict[str, float] = {
    # Documentation / narrative gaps — biller can fix before submission
    "DOC":            0.6,
    "DOCUMENTATION":  0.6,
    "NARRATIVE":      0.6,

    # Missing diagnosis linkage — hard denial
    "DX_LINKAGE":     1.5,
    "DX_LINK":        1.5,
    "DX":             1.5,
    "MISSING_DX":     1.5,

    # Modifier issues — often denied then overturned; high rate
    "MOD":            1.2,
    "MODIFIER":       1.2,
    "MOD-25":         1.3,
    "MOD-59":         1.3,

    # E/M level upcoding / undercoding — moderate risk
    "EM":             1.1,
    "E/M":            1.1,
    "E/M-LEVEL":      1.1,

    # Duplicate / NCCI edits — payers auto-deny these
    "DUPLICATE":      1.6,
    "NCCI":           1.4,

    # Time-based codes — moderate
    "TIME":           1.0,

    # Medical necessity — high
    "MED-NEC":        1.3,
    "MEDICAL_NECESSITY": 1.3,

    # General fallback
    "OTHER":          1.0,
}

DEFAULT_RULE_MULTIPLIER = 1.0


# Severity rank for filtering when a tenant has set MIN_SEVERITY_TO_SHOW
# (so the scoring respects the same threshold the dashboard uses).
SEVERITY_RANK: dict[str, int] = {
    "info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4,
}


def _rule_family(rule_id: str | None) -> str:
    """Bucket a rule_id into a rule family for the multiplier table.

    The convention is rule_ids start with a category prefix:
    'DX_LINKAGE_REQUIRED' -> 'DX_LINKAGE'
    'MOD-25' -> 'MOD'
    'EM_NEW_VS_ESTABLISHED' -> 'EM'

    Unknown shapes fall through to 'OTHER'.

    When multiple families could match (e.g. a rule starting with
    'MODIFIER' could match either 'MOD' or 'MODIFIER'), the longer
    family wins — more specific wins over less specific. We sort
    families by length descending before checking.
    """
    if not rule_id:
        return "OTHER"
    rid = rule_id.upper().strip()
    # Direct exact matches first (more specific)
    if rid in RULE_FAMILY_MULTIPLIERS:
        return rid
    # Prefix match — try longer prefixes first
    for family in sorted(RULE_FAMILY_MULTIPLIERS, key=len, reverse=True):
        if rid.startswith(family.upper()):
            return family
    # Common rule prefixes (kept for clarity; the sorted loop above
    # catches most of these already)
    if "DX_LINK" in rid or "MISSING_DX" in rid:
        return "DX_LINKAGE"
    if rid.startswith("MOD") or "MODIFIER" in rid:
        return "MOD"
    if rid.startswith("EM") or "E/M" in rid:
        return "EM"
    if "DUPLICATE" in rid or "NCCI" in rid:
        return "DUPLICATE"
    if "MED" in rid and "NEC" in rid:
        return "MED-NEC"
    if "DOC" in rid:
        return "DOC"
    if "TIME" in rid:
        return "TIME"
    return "OTHER"


def _severity_rank(severity: str) -> int:
    return SEVERITY_RANK.get(str(severity).lower(), 0)


def _combine_independent_risks(risks: list[float]) -> float:
    """Combine per-finding risks via 1 - product(1 - risk_i).

    Independent probabilities combine this way: e.g. if a claim has
    a 30% chance of denial for reason A and a 20% chance for reason
    B (independent), the combined probability is 1 - (0.7 * 0.8) =
    0.44. The function caps the result at 0.99 so we never claim
    'this will definitely be denied' — there's always the biller's
    ability to fix before submission.
    """
    if not risks:
        return 0.0
    product = 1.0
    for r in risks:
        # Clamp each risk to [0, 1] before multiplying
        r = max(0.0, min(1.0, float(r)))
        product *= (1.0 - r)
    return min(0.99, 1.0 - product)


def compute_finding_risk(finding: dict[str, Any]) -> dict[str, Any]:
    """Compute the risk contribution for a single finding.

    Returns a dict with the rule_id, rule_family, severity, base
    weight, multiplier, and the final per-finding risk. The caller
    combines these into a claim-level risk.
    """
    severity = str(finding.get("severity", "")).lower()
    base = SEVERITY_WEIGHTS.get(severity, 0.05)
    rule_id = finding.get("rule_id") or (
        finding.get("rule_ids", [None])[0] if finding.get("rule_ids") else None
    )
    family = _rule_family(rule_id)
    multiplier = RULE_FAMILY_MULTIPLIERS.get(family, DEFAULT_RULE_MULTIPLIER)
    risk = min(0.95, base * multiplier)
    return {
        "rule_id": rule_id,
        "rule_family": family,
        "severity": severity,
        "base_weight": base,
        "rule_multiplier": multiplier,
        "risk": risk,
        "finding_id": finding.get("finding_id", ""),
    }


def compute_denial_risk(
    findings: list[dict[str, Any]],
    *,
    min_severity: int = 0,
) -> dict[str, Any]:
    """Score a claim's denial risk from the auditor's findings.

    Parameters
    ----------
    findings: list of finding dicts (the same shape the auditor
        emits). Each finding needs at minimum `severity` and
        `rule_id`/`rule_ids`. Empty findings list returns 0.0 risk.
    min_severity: the tenant's MIN_SEVERITY_TO_SHOW rank. Findings
        below this rank are not counted toward the risk score.
        Same threshold the dashboard uses to hide findings.

    Returns
    -------
    A dict with shape:
        {
            "denial_probability": float,  # 0.0 to 0.99
            "n_findings": int,
            "n_findings_scored": int,
            "n_findings_below_threshold": int,
            "per_finding": list[dict],  # one entry per scored finding
            "top_risk": dict | None,     # the highest-risk finding
            "tier": str,                 # "low" | "medium" | "high" | "critical"
        }

    Tier mapping (based on denial_probability):
        < 0.10  -> low
        < 0.30  -> medium
        < 0.60  -> high
        >= 0.60 -> critical
    """
    per_finding = []
    risks = []
    n_below_threshold = 0
    for f in findings or []:
        sev_rank = _severity_rank(f.get("severity", "info"))
        if sev_rank < min_severity:
            n_below_threshold += 1
            continue
        contrib = compute_finding_risk(f)
        per_finding.append(contrib)
        risks.append(contrib["risk"])
    denial_probability = _combine_independent_risks(risks)
    # Find the top-risk finding (highest contribution)
    top_risk = max(per_finding, key=lambda x: x["risk"]) if per_finding else None
    if denial_probability < 0.10:
        tier = "low"
    elif denial_probability < 0.30:
        tier = "medium"
    elif denial_probability < 0.60:
        tier = "high"
    else:
        tier = "critical"
    return {
        "denial_probability": round(denial_probability, 4),
        "n_findings": len(findings or []),
        "n_findings_scored": len(per_finding),
        "n_findings_below_threshold": n_below_threshold,
        "per_finding": per_finding,
        "top_risk": top_risk,
        "tier": tier,
    }