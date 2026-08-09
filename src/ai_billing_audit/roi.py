"""ROI calculator for the sales one-pager.

Decision-makers don't care about our costs. They care about:
'How much will I save?' This module answers that with simple
inputs and conservative math.

Math
----

Inputs (with sensible defaults):
  monthly_claims: number of claims submitted per month.
  current_denial_rate: fraction of claims denied on first submission.
    Industry average is 5-10% (CMS commercial). Default 7.5%.
  avg_claim_value_usd: average revenue per claim. Industry average
    for US office visits is $190 (CMS). Specialty-dependent:
    $80 (primary care) to $300 (specialty).
  current_appeal_rate: fraction of denials that get appealed and
    recovered. Industry average is 30-60%. Default 50%.
  plan_tier: which Zorva plan matches the clinic's volume.
    Tiers: starter (up to 200 claims), growth (200-2000),
    scale (2000+). Default: derived from monthly_claims.
  catch_rate: fraction of pre-submission errors Zorva catches.
    This is the v12 AHCIP val-set RECALL score (micro over cleaned
    gold), not F1. F1 conflates precision and recall; for
    "fraction of would-be denials the auditor catches" the right
    metric is recall alone. Recall is what the clinic cares about:
    precision only affects how much time the biller spends dismissing
    false positives (a 5-second cost per flag, not revenue lost).
    Default: 0.77 (v12 AHCIP recall, README.md:7,
    2026-06-23 post-leakage-fix).

Outputs:
  monthly_denials: claims denied on first submission, without Zorva.
  monthly_recovered_no_zorva: claims the clinic currently
    recovers through manual appeal.
  monthly_revenue_lost_no_zorva: monthly denials not recovered.
  monthly_caught_with_zorva: monthly claims that Zorva catches
    and the biller fixes pre-submission.
  monthly_revenue_saved: dollar value of caught claims (×avg_claim).
  net_monthly_savings: revenue saved - plan_tier_price.
  annual_roi_pct: net_annual_savings / annual_plan_cost × 100.

Plan pricing (CAD, monthly, encounter-audit volume):
  solo:     $499    (up to 1,000 encounter audits / month)
  practice: $1,499  (1,000 - 3,000 encounter audits / month)
  network:  $2,999+ (3,000+ encounter audits / month, custom volume)

The calculator is intentionally conservative. catch_rate defaults
to 0.77 (v12 AHCIP val-set RECALL, README.md:7, 2026-06-23
post-leakage-fix) but callers can pass a custom value based
on their own smartness-test runs.

Tier names match templates/pricing.html (Solo / Practice / Network).
"""

from __future__ import annotations

from typing import Any


PLAN_PRICING_CAD: dict[str, dict[str, Any]] = {
    "solo": {"monthly_price_cad": 499, "max_claims_per_month": 1000},
    "practice": {"monthly_price_cad": 1499, "max_claims_per_month": 3000},
    "network": {"monthly_price_cad": 2999, "max_claims_per_month": None},
}

# Conservative defaults pulled from CMS / industry sources.
DEFAULT_DENIAL_RATE = 0.075  # 7.5% of claims denied on first submission
DEFAULT_APPEAL_RATE = 0.50  # 50% of denials get appealed and recovered
DEFAULT_AVG_CLAIM_USD = 190.0  # CMS commercial office-visit average
DEFAULT_CATCH_RATE = 0.77  # v12 AHCIP val-set RECALL (README.md:7, 2026-06-23 post-leakage-fix); was 0.69 from F1, was 0.42 from v10
DEFAULT_TIER = "practice"  # conservative middle tier


def tier_for_volume(monthly_claims: int) -> str:
    """Pick the smallest plan that covers the volume."""
    if monthly_claims <= PLAN_PRICING_CAD["solo"]["max_claims_per_month"]:
        return "solo"
    if monthly_claims <= PLAN_PRICING_CAD["practice"]["max_claims_per_month"]:
        return "practice"
    return "network"


def compute_roi(
    *,
    monthly_claims: int,
    current_denial_rate: float = DEFAULT_DENIAL_RATE,
    avg_claim_value_usd: float = DEFAULT_AVG_CLAIM_USD,
    current_appeal_rate: float = DEFAULT_APPEAL_RATE,
    catch_rate: float = DEFAULT_CATCH_RATE,
    plan_tier: str | None = None,
) -> dict[str, Any]:
    """Compute monthly ROI from a clinic's inputs.

    Returns a dict with monthly + annual figures plus the inputs
    used. Caller is responsible for currency conversion (CAD vs
    USD) — defaults to USD inputs and CAD plan pricing; the
    caller can post-multiply by a fx rate if needed.
    """
    if monthly_claims <= 0:
        raise ValueError("monthly_claims must be positive")
    if not (0 <= current_denial_rate <= 1):
        raise ValueError("current_denial_rate must be in [0, 1]")
    if not (0 <= current_appeal_rate <= 1):
        raise ValueError("current_appeal_rate must be in [0, 1]")
    if not (0 <= catch_rate <= 1):
        raise ValueError("catch_rate must be in [0, 1]")
    if avg_claim_value_usd <= 0:
        raise ValueError("avg_claim_value_usd must be positive")
    if plan_tier is None:
        plan_tier = tier_for_volume(monthly_claims)
    if plan_tier not in PLAN_PRICING_CAD:
        raise ValueError(
            f"plan_tier must be one of {list(PLAN_PRICING_CAD)}; got {plan_tier!r}"
        )

    monthly_denials = monthly_claims * current_denial_rate
    monthly_recovered_no_zorva = monthly_denials * current_appeal_rate
    monthly_revenue_lost_no_zorva = monthly_denials - monthly_recovered_no_zorva

    # Zorva catches (catch_rate) of the would-be denials and the
    # biller fixes them pre-submission. The catch_rate is
    # conservative: not every caught error was going to be denied,
    # and not every denial is fixable. The default 0.77 reflects
    # the v12 AHCIP val-set RECALL score (README.md:7,
    # 2026-06-23 post-leakage-fix). Recall is the right metric
    # here: F1 conflates precision (biller time cost) with recall
    # (revenue protection); for the "how many errors caught"
    # question, only recall matters.
    monthly_caught_with_zorva = monthly_denials * catch_rate
    monthly_revenue_saved = monthly_caught_with_zorva * avg_claim_value_usd

    plan_price = PLAN_PRICING_CAD[plan_tier]["monthly_price_cad"]
    net_monthly_savings_usd = monthly_revenue_saved - plan_price
    annual_plan_cost_cad = plan_price * 12
    annual_revenue_saved_usd = monthly_revenue_saved * 12
    annual_net_savings_usd = annual_revenue_saved_usd - annual_plan_cost_cad
    annual_roi_pct = (
        (annual_net_savings_usd / annual_plan_cost_cad) * 100
        if annual_plan_cost_cad > 0
        else 0.0
    )

    return {
        "inputs": {
            "monthly_claims": monthly_claims,
            "current_denial_rate": current_denial_rate,
            "avg_claim_value_usd": avg_claim_value_usd,
            "current_appeal_rate": current_appeal_rate,
            "catch_rate": catch_rate,
            "plan_tier": plan_tier,
        },
        "monthly": {
            "claims_submitted": monthly_claims,
            "denials_without_zorva": int(monthly_denials),
            "recovered_manually": int(monthly_recovered_no_zorva),
            "revenue_lost_without_zorva": round(
                monthly_revenue_lost_no_zorva * avg_claim_value_usd, 2
            ),
            "caught_by_zorva": int(monthly_caught_with_zorva),
            "revenue_saved_by_zorva": round(monthly_revenue_saved, 2),
            "plan_cost_cad": plan_price,
            "net_monthly_savings_usd": round(net_monthly_savings_usd, 2),
        },
        "annual": {
            "revenue_saved_usd": round(annual_revenue_saved_usd, 2),
            "plan_cost_cad": annual_plan_cost_cad,
            "net_savings_usd": round(annual_net_savings_usd, 2),
            "roi_pct": round(annual_roi_pct, 1),
        },
        "narrative": {
            "summary": (
                f"For a clinic submitting {monthly_claims:,} claims/month "
                f"with a {current_denial_rate * 100:.1f}% denial rate, "
                f"Zorva catches ~{int(monthly_caught_with_zorva)} claims/month "
                f"that would otherwise be denied, saving "
                f"${monthly_revenue_saved:,.0f}/month in recovered "
                f"revenue."
            ),
            "after_subs": (
                f"After the ${plan_price}/month Zorva subscription, "
                f"net monthly savings is ${net_monthly_savings_usd:,.0f}. "
                f"Annual ROI: {annual_roi_pct:.0f}%."
            ),
        },
    }
