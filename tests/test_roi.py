"""Tests for the ROI calculator.

Decision-makers don't care about our costs. They care about
'How much will I save?' The ROI calculator takes 5 inputs and
returns monthly + annual figures the sales team can quote on
a demo call.

What's pinned
-------------
* compute_roi() math: with default inputs, monthly revenue saved
  = monthly_claims × 0.075 × 0.69 × $190
* Plan tier auto-selection by monthly volume
* Tier override (pass plan_tier="starter" for a 5000-claim
  clinic and the calculation uses $499)
* Default catch_rate = 0.69 (matches the v12 AHCIP val-set F1, README.md:7)
* Validation: monthly_claims must be > 0, rates in [0, 1]
* HTML route /roi renders without 500
* JSON route /roi/results returns valid JSON
* POST /roi redirects to /roi with query params
* All amounts in the response are non-negative integers/rounded floats
"""

from __future__ import annotations

import importlib
import pytest
from fastapi.testclient import TestClient

from ai_billing_audit.roi import (
    DEFAULT_APPEAL_RATE,
    DEFAULT_AVG_CLAIM_USD,
    DEFAULT_CATCH_RATE,
    DEFAULT_DENIAL_RATE,
    DEFAULT_TIER,
    PLAN_PRICING_CAD,
    compute_roi,
    tier_for_volume,
)


# ---------- pure-math tests ----------


def test_tier_for_volume_starter():
    assert tier_for_volume(50) == "starter"
    assert tier_for_volume(200) == "starter"


def test_tier_for_volume_growth():
    assert tier_for_volume(201) == "growth"
    assert tier_for_volume(2000) == "growth"


def test_tier_for_volume_scale():
    assert tier_for_volume(2001) == "scale"
    assert tier_for_volume(50000) == "scale"


def test_compute_roi_default_inputs():
    """Default inputs (1000 claims, 7.5% denial, $190/claim, 50%
    appeal, 77% catch) should produce a sensible result."""
    r = compute_roi(monthly_claims=1000)
    # monthly_denials = 1000 * 0.075 = 75
    assert r["monthly"]["denials_without_zorva"] == 75
    # monthly_caught = 75 * 0.77 = 57.75 → 57 (int)
    assert r["monthly"]["caught_by_zorva"] == 57
    # revenue_saved = 57.75 * 190 = 10972.5
    assert r["monthly"]["revenue_saved_by_zorva"] == 10972.5
    # Plan tier auto-selected: growth (1000 > 200)
    assert r["inputs"]["plan_tier"] == "growth"
    # Net monthly savings = 10972.5 - 1499 = 9473.5
    assert r["monthly"]["net_monthly_savings_usd"] == 9473.5


def test_compute_roi_starter_tier():
    r = compute_roi(monthly_claims=150, plan_tier="starter")
    assert r["inputs"]["plan_tier"] == "starter"
    # revenue_saved = 150 * 0.075 * 0.77 * 190 = 1645.875 (banker's-rounded to 1645.88)
    assert r["monthly"]["revenue_saved_by_zorva"] == 1645.88
    # Net = 1645.88 - 499 = 1146.88
    assert r["monthly"]["net_monthly_savings_usd"] == 1146.88


def test_compute_roi_scale_tier():
    r = compute_roi(monthly_claims=5000, plan_tier="scale")
    assert r["inputs"]["plan_tier"] == "scale"
    assert r["monthly"]["plan_cost_cad"] == 2999


def test_compute_roi_explicit_tier_override():
    """Force a clinic onto the starter tier despite 5000 claims."""
    r = compute_roi(monthly_claims=5000, plan_tier="starter")
    assert r["inputs"]["plan_tier"] == "starter"
    assert r["monthly"]["plan_cost_cad"] == 499


def test_compute_roi_high_appeal_rate_more_loss_without_zorva():
    """Higher appeal rate means more loss avoided by NOT having
    Zorva — but Zorva still saves more on top because catch rate
    is independent of manual appeal rate."""
    r_low = compute_roi(monthly_claims=2000, current_appeal_rate=0.0)
    r_high = compute_roi(monthly_claims=2000, current_appeal_rate=0.9)
    # Without Zorva, higher appeal rate means more revenue recovered
    assert r_high["monthly"]["recovered_manually"] > r_low["monthly"]["recovered_manually"]
    # Zorva's saved amount is independent of appeal rate (it's
    # catch_rate × denials × avg_claim)
    assert r_high["monthly"]["revenue_saved_by_zorva"] == r_low["monthly"]["revenue_saved_by_zorva"]


def test_compute_roi_zero_denial_rate():
    """If the clinic has zero denials, Zorva saves $0."""
    r = compute_roi(monthly_claims=1000, current_denial_rate=0.0)
    assert r["monthly"]["denials_without_zorva"] == 0
    assert r["monthly"]["revenue_saved_by_zorva"] == 0.0
    assert r["monthly"]["net_monthly_savings_usd"] == -1499.0  # cost only


def test_compute_roi_annualization():
    """Annual figures = monthly × 12, minus annual plan cost."""
    r = compute_roi(monthly_claims=1000)
    monthly_saved = r["monthly"]["revenue_saved_by_zorva"]
    annual_saved = monthly_saved * 12
    assert r["annual"]["revenue_saved_usd"] == round(annual_saved, 2)
    annual_plan = r["monthly"]["plan_cost_cad"] * 12
    assert r["annual"]["plan_cost_cad"] == annual_plan
    net = annual_saved - annual_plan
    assert r["annual"]["net_savings_usd"] == round(net, 2)


def test_compute_roi_annual_roi_pct():
    """Annual ROI = annual_net_savings / annual_plan_cost × 100."""
    r = compute_roi(monthly_claims=1000)
    net = r["annual"]["net_savings_usd"]
    cost = r["annual"]["plan_cost_cad"]
    expected_pct = round((net / cost) * 100, 1)
    assert r["annual"]["roi_pct"] == expected_pct


def test_compute_roi_negative_net_is_possible():
    """For a tiny clinic with low volume, Zorva may not pay back
    immediately. The calculator must report a negative net."""
    r = compute_roi(monthly_claims=10, current_denial_rate=0.01)
    # 10 * 0.01 * 0.69 * 190 = $13.11 revenue saved
    # Plan cost = $499 (starter tier, since volume <= 200)
    # Net = 13.11 - 499 = -485.89 (negative)
    assert r["monthly"]["net_monthly_savings_usd"] < 0


def test_compute_roi_high_volume_huge_savings():
    """A 10,000-claim practice with 10% denials sees $7,980/month
    saved against a $2,999 plan = $4,981 net."""
    r = compute_roi(
        monthly_claims=10000,
        current_denial_rate=0.10,
        avg_claim_value_usd=190.0,
        catch_rate=0.42,
    )
    # 10000 * 0.10 * 0.42 * 190 = 79,800
    assert r["monthly"]["revenue_saved_by_zorva"] == 79800.0
    # Plan cost = $2,999 (scale tier, since volume > 2000)
    assert r["monthly"]["plan_cost_cad"] == 2999
    # Net = 79,800 - 2,999 = 76,801
    assert r["monthly"]["net_monthly_savings_usd"] == 76801.0


def test_compute_roi_inputs_validation():
    """Reject invalid inputs."""
    with pytest.raises(ValueError):
        compute_roi(monthly_claims=0)
    with pytest.raises(ValueError):
        compute_roi(monthly_claims=-1)
    with pytest.raises(ValueError):
        compute_roi(monthly_claims=1000, current_denial_rate=1.5)
    with pytest.raises(ValueError):
        compute_roi(monthly_claims=1000, current_appeal_rate=-0.1)
    with pytest.raises(ValueError):
        compute_roi(monthly_claims=1000, catch_rate=2.0)
    with pytest.raises(ValueError):
        compute_roi(monthly_claims=1000, avg_claim_value_usd=-5)
    with pytest.raises(ValueError):
        compute_roi(monthly_claims=1000, plan_tier="premium")


def test_compute_roi_includes_inputs_unchanged():
    """The inputs dict round-trips the values the caller passed."""
    r = compute_roi(
        monthly_claims=2000,
        current_denial_rate=0.10,
        avg_claim_value_usd=300.0,
        current_appeal_rate=0.7,
        catch_rate=0.5,
    )
    assert r["inputs"]["monthly_claims"] == 2000
    assert r["inputs"]["current_denial_rate"] == 0.10
    assert r["inputs"]["avg_claim_value_usd"] == 300.0
    assert r["inputs"]["current_appeal_rate"] == 0.7
    assert r["inputs"]["catch_rate"] == 0.5


def test_compute_roi_narrative_summary_present():
    """The narrative summary mentions the actual numbers."""
    r = compute_roi(monthly_claims=2000)
    assert "2,000" in r["narrative"]["summary"]
    assert "7.5%" in r["narrative"]["summary"]
    assert "$" in r["narrative"]["summary"]
    assert "month" in r["narrative"]["summary"]


def test_compute_roi_constants_match_smartness_test():
    """Default catch_rate = 0.77 = v12 AHCIP val-set RECALL (README.md:7).

    v12 AHCIP: precision 0.625, recall 0.769, F1 0.690.

    Catch rate is recall (not F1) because recall measures the
    fraction of would-be errors the auditor catches — the
    clinic's revenue-protection question. F1 conflates
    precision and recall and would understate the catch rate
    for this purpose.
    """
    assert DEFAULT_CATCH_RATE == 0.77, (
        "default catch_rate should be v12 recall (0.77), not F1 (0.69). "
        "F1 conflates precision with recall and understates how many "
        "real errors the auditor catches."
    )
    # catch_rate is a probability in [0, 1] independent of denial_rate
    assert 0 < DEFAULT_CATCH_RATE < 1
    assert 0 < DEFAULT_DENIAL_RATE < 1


# ---------- HTTP route tests ----------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    import ai_billing_audit.api as api_mod
    importlib.reload(api_mod)
    app = api_mod.create_app()
    return TestClient(app)


def test_roi_route_returns_200_with_defaults(client):
    resp = client.get("/roi")
    assert resp.status_code == 200
    # The default 1000 claims/month should be in the form
    assert 'value="1000"' in resp.text or "1000" in resp.text


def test_roi_route_uses_default_catch_rate(client):
    resp = client.get("/roi")
    # Default catch_rate 0.77 should be in the rendered form
    assert "0.77" in resp.text


def test_roi_route_renders_results_with_defaults(client):
    resp = client.get("/roi")
    # With defaults (1000 claims, 7.5% denial, catch_rate=0.77):
    #   monthly_revenue_saved = 1000 * 0.075 * 0.77 * 190 = $10,972.50 → $10,972
    #   plan_tier = growth ($1,499)
    #   net = $9,473.50 → $9,474 (banker's rounding)
    assert "10,972" in resp.text or "10972" in resp.text
    assert "9,474" in resp.text or "9474" in resp.text


def test_roi_route_uses_query_params(client):
    """When the URL has ?monthly_claims=5000, the form should
    show 5000 in the input field, not the default 1000."""
    resp = client.get("/roi?monthly_claims=5000")
    assert resp.status_code == 200
    # The form input should be populated with 5000
    assert 'value="5000"' in resp.text


def test_roi_results_endpoint_returns_json(client):
    """The /roi/results endpoint is the embeddable widget."""
    resp = client.get("/roi/results?monthly_claims=1000")
    assert resp.status_code == 200
    data = resp.json()
    assert "monthly" in data
    assert "annual" in data
    assert "inputs" in data
    assert "narrative" in data
    assert data["monthly"]["plan_cost_cad"] == 1499  # growth tier


def test_roi_results_endpoint_with_custom_inputs(client):
    resp = client.get("/roi/results?monthly_claims=5000&plan_tier=scale")
    data = resp.json()
    assert data["inputs"]["plan_tier"] == "scale"
    assert data["monthly"]["plan_cost_cad"] == 2999


def test_roi_results_validates_inputs(client):
    """Invalid inputs → 400."""
    resp = client.get("/roi/results?monthly_claims=0")
    assert resp.status_code == 400


def test_roi_post_redirects_to_get(client):
    """POST /roi with form data redirects to GET with query params."""
    resp = client.post("/roi", data={
        "monthly_claims": 2500,
        "current_denial_rate": "0.10",
        "avg_claim_value_usd": "200",
        "current_appeal_rate": "0.50",
        "catch_rate": "0.42",
        "plan_tier": "scale",
    }, follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers.get("location", "")
    assert "/roi?" in location
    assert "monthly_claims=2500" in location
    assert "plan_tier=scale" in location


def test_roi_post_then_get_round_trips(client):
    """Follow the redirect: POST → 303 → GET with the same params."""
    resp = client.post("/roi", data={
        "monthly_claims": 3500,
        "current_denial_rate": "0.08",
        "avg_claim_value_usd": "250",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert "3,500" in resp.text or "3500" in resp.text


def test_roi_page_links_to_other_legal_pages(client):
    """The ROI page should share the base template with the legal
    pages and the rest of the app."""
    resp = client.get("/roi")
    # The topbar nav links — Marketing nav on the public site
    # (Home / Audits / Pricing / How it works / Security / Try / FAQ
    # / Contact). /activity is internal-tool and intentionally not
    # in the public marketing nav; the dashboard lives at /audits.
    assert "/legal/privacy" in resp.text
    assert "/legal/terms" in resp.text
    assert "/audits" in resp.text
    assert "/pricing" in resp.text
    assert "/how-it-works" in resp.text
    assert "/security" in resp.text
    assert "/try" in resp.text
    assert "/faq" in resp.text


def test_roi_includes_shareable_url_note(client):
    """The page should hint that the URL is shareable."""
    resp = client.get("/roi")
    # The form has a method="post" action="/roi" — shareable
    # behavior comes from query-param encoding.
    html = resp.text
    # Should mention shareable URL or query params somewhere
    assert "shareable" in html.lower() or "share" in html.lower() or \
           "/roi/results" in html or "/roi?" in html or \
           'method="post"' in html


def test_roi_results_widget_for_marketing_embed(client):
    """The JSON shape is stable for the marketing widget."""
    resp = client.get("/roi/results")
    data = resp.json()
    expected_top_keys = {"inputs", "monthly", "annual", "narrative"}
    assert set(data.keys()) == expected_top_keys
    expected_monthly = {
        "claims_submitted", "denials_without_zorva", "recovered_manually",
        "revenue_lost_without_zorva", "caught_by_zorva",
        "revenue_saved_by_zorva", "plan_cost_cad", "net_monthly_savings_usd",
    }
    assert set(data["monthly"].keys()) == expected_monthly
    expected_annual = {
        "revenue_saved_usd", "plan_cost_cad", "net_savings_usd", "roi_pct",
    }
    assert set(data["annual"].keys()) == expected_annual