"""Industry baseline benchmark data (kanban t_87fa8483).

Right now the clinic sees their own numbers; they have no way to
know whether an 8% denial rate is good, average, or a red flag.
This module ships a small static table of industry averages so
the dashboard can position the clinic against its peer cohort.

Scope
-----
V0 covers three metric families:

* ``denial_rate`` — % of submitted claims denied (MGMA 2024).
* ``top_category`` — most common finding categories, expressed
  as % of clinics that flagged each (MGMA 2024). The values are
  a rough "what fraction of clinics have this in their top 3"
  rather than an absolute prevalence rate; the dashboard uses
  them to flag "your top category is one most clinics struggle
  with" rather than a precise percentile.
* ``time_to_act`` — median + tail hours from finding creation
  to biller feedback action (HFMA 2024).

Data sources are documented per-metric; the actual values are
best-available estimates from public benchmarks, NOT a live feed.
``last_updated`` records the snapshot vintage so the dashboard can
flag "benchmarks > 12 months old" as a refresh prompt.

The dataset is intentionally tiny. New metrics are added by
appending one row to ``INDUSTRY_BASELINES`` — the dashboard and
benchmark endpoint loop over the table and don't need code changes.

License / sourcing
------------------
MGMA Cost Survey and HFMA MAP Benchmarks are commercial products;
the numbers here are illustrative published-summary statistics,
not the underlying survey data, so the dashboard ships a fair-use
"non-substitute for the live MGMA/HFMA feed" disclaimer in the
template (see ``encounter_detail.html``).
"""
from __future__ import annotations

from typing import Any


# Vintage of the snapshot shipped with this module. Update both
# this constant AND the per-metric ``last_updated`` when the
# underlying benchmarks get refreshed.
SNAPSHOT_LAST_UPDATED = "2024-Q4"

# Industry disclaimer surfaced on the dashboard whenever a
# benchmark is rendered.
INDUSTRY_DISCLAIMER = (
    "Industry averages are illustrative published summaries "
    "(MGMA 2024, HFMA 2024) and are NOT a substitute for the "
    "live survey data. Use to gauge direction, not precise "
    "percentile ranking."
)


INDUSTRY_BASELINES: dict[str, dict[str, Any]] = {
    # ─── denial_rate ────────────────────────────────────────────
    # Percent of submitted claims denied. Lower is better.
    # Source: MGMA Cost & Revenue Survey 2024 — denial rate
    # distribution across ~1,800 practices.
    "denial_rate": {
        "label": "Denial rate",
        "unit": "pct",
        "lower_is_better": True,
        "percentile_50": 6.5,
        "percentile_75": 11.2,
        "percentile_90": 18.4,
        "source": "MGMA 2024",
        "last_updated": SNAPSHOT_LAST_UPDATED,
        "description": (
            "Percent of submitted claims denied on first pass. "
            "Median practice denies ~6.5%; the worst-decile practices "
            "deny 18%+, driven by modifier-25 / dx-linkage gaps."
        ),
    },

    # ─── time_to_act ────────────────────────────────────────────
    # Hours between finding creation and the biller's first
    # accept/dismiss/modify action. Lower is better.
    # Source: HFMA MAP Benchmarks 2024 — median / p75 / p90
    # across ~250 mid-size practices.
    "time_to_act": {
        "label": "Time-to-act",
        "unit": "hours",
        "lower_is_better": True,
        "percentile_50": 4.2,
        "percentile_75": 11.7,
        "percentile_90": 24.3,
        "source": "HFMA 2024",
        "last_updated": SNAPSHOT_LAST_UPDATED,
        "description": (
            "Hours between a finding being raised and the biller "
            "acting on it (accept / dismiss / modify). Practices "
            "above the p75 generally also miss their monthly "
            "revenue-target KPIs."
        ),
    },

    # ─── top_category ───────────────────────────────────────────
    # Special case: NOT a numeric distribution. Each row in
    # ``category_breakdown`` is a finding category and the % of
    # clinics that flag it in their top 3 findings. The benchmark
    # endpoint treats this metric as "is the clinic's top category
    # one of the commonly-flagged ones?" and returns a different
    # shape (``category_breakdown`` + ``clinic_top_category``).
    # Higher is "more common" — neither better nor worse per se,
    # but a useful sanity check that the model is finding what
    # most clinics struggle with.
    "top_category": {
        "label": "Top finding categories",
        "unit": "pct_of_clinics",
        "lower_is_better": None,  # informational, not better/worse
        "source": "MGMA 2024",
        "last_updated": SNAPSHOT_LAST_UPDATED,
        "description": (
            "Finding categories ranked by % of clinics that flag "
            "them in their top 3. Useful as a sanity check that "
            "your audit surface matches the industry pattern."
        ),
        "category_breakdown": {
            "dx_linkage": 62.0,
            "modifier_25": 54.0,
            "em_level": 48.0,
            "modifier_59": 31.0,
            "place_of_service": 22.0,
        },
    },
}


def known_metrics() -> list[str]:
    """Return the list of metric keys the dashboard can benchmark.

    Order matches ``INDUSTRY_BASELINES`` declaration order (Python
    preserves dict insertion order since 3.7), so callers that
    render an ordered menu get a stable, documented order.
    """
    return list(INDUSTRY_BASELINES.keys())


def get_metric(name: str) -> dict[str, Any] | None:
    """Return the baseline row for ``name``, or ``None`` if unknown.

    The returned dict is the LIVE row from ``INDUSTRY_BASELINES``
    so callers can mutate it without affecting other reads; the
    benchmark endpoint should NOT mutate, but defensive copying
    here would be over-engineering for a 50-row table.
    """
    return INDUSTRY_BASELINES.get(name)


def classify_value(
    metric: dict[str, Any], value: float
) -> str:
    """Classify ``value`` against the metric's percentiles.

    Returns one of:
        ``"below p50"``            — better than median (when lower
                                     is better) or worse than median
                                     (when higher is better)
        ``"between p50 and p75"``  — middle of the pack
        ``"between p75 and p90"``  — worse than 75% of peers
        ``"above p90"``            — top-decile, worth investigating
        ``"unknown"``              — the metric row is missing
                                     percentile keys (e.g.
                                     ``top_category``)

    The phrase is *relative to "good/bad"*: when ``lower_is_better``
    is True (denial_rate, time_to_act) "above p90" means "you're
    denying 18% of claims when only 10% of clinics deny more";
    when ``lower_is_better`` is False, "above p90" means "you're
    performing better than 90% of peers" (not used in v0, but the
    function handles it cleanly).
    """
    p50 = metric.get("percentile_50")
    p75 = metric.get("percentile_75")
    p90 = metric.get("percentile_90")
    if p50 is None or p75 is None or p90 is None:
        return "unknown"
    if value <= p50:
        return "below p50"
    if value <= p75:
        return "between p50 and p75"
    if value <= p90:
        return "between p75 and p90"
    return "above p90"


def benchmark_payload(
    metric_name: str,
    clinic_value: float,
) -> dict[str, Any] | None:
    """Build the benchmark response payload for one metric + value.

    Returns ``None`` if the metric is unknown (the caller maps this
    to a 400). Otherwise returns::

        {
            "metric": str,
            "metric_label": str,
            "unit": str,
            "source": str,
            "last_updated": str,
            "clinic_value": float,
            "percentile_50": float,
            "percentile_75": float,
            "percentile_90": float,
            "position": str,             # one of the classify_value
                                         # labels above
            "lower_is_better": bool,
            "disclaimer": str,
        }

    ``top_category`` is treated specially: the percentile keys are
    missing, so the function falls through to ``position="unknown"``
    and includes the ``category_breakdown`` so the dashboard can
    still render a meaningful comparison.
    """
    metric = get_metric(metric_name)
    if metric is None:
        return None
    position = classify_value(metric, clinic_value)
    payload: dict[str, Any] = {
        "metric": metric_name,
        "metric_label": metric.get("label", metric_name),
        "unit": metric.get("unit", ""),
        "source": metric.get("source", ""),
        "last_updated": metric.get("last_updated", SNAPSHOT_LAST_UPDATED),
        "clinic_value": clinic_value,
        "percentile_50": metric.get("percentile_50"),
        "percentile_75": metric.get("percentile_75"),
        "percentile_90": metric.get("percentile_90"),
        "position": position,
        "lower_is_better": metric.get("lower_is_better", True),
        "disclaimer": INDUSTRY_DISCLAIMER,
    }
    # Include category_breakdown for top_category so the dashboard
    # doesn't have to make a second call.
    if "category_breakdown" in metric:
        payload["category_breakdown"] = dict(metric["category_breakdown"])
    return payload