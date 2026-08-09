"""Tests for the top-missed-revenue-patterns analyzer.

Covers the four behaviours the task spec calls out:

1. Specialty filter — only records matching the requested
   specialty are aggregated.
2. Score calculation — patterns are ranked by
   count × total_dollars, descending.
3. Insufficient-data gate — the function returns the partial
   result and a flag when the input covers <3 months.
4. The function accepts both a list of records and a path to
   a JSONL file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.analytics import (  # noqa: E402
    _is_missed_revenue,
    _month_key,
    _pattern_key,
    top_missed_revenue_patterns,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def family_medicine_records() -> list[dict]:
    """3 months of family-medicine audit records with two patterns."""
    return [
        # Month 1: 2026-04
        {
            "specialty": "family_medicine",
            "timestamp": "2026-04-05T12:00:00Z",
            "findings": [
                {"rule_id": "rule_ahcip_missing_modifier_25", "estimated_value": 50.0},
                {"rule_id": "rule_ahcip_missing_modifier_25", "estimated_value": 50.0},
                {"rule_id": "em_level_upcode", "estimated_value": 90.0},
            ],
        },
        # Month 2: 2026-05
        {
            "specialty": "family_medicine",
            "timestamp": "2026-05-12T09:00:00Z",
            "findings": [
                {"rule_id": "rule_ahcip_missing_modifier_25", "estimated_value": 50.0},
                {"rule_id": "em_level_upcode", "estimated_value": 90.0},
            ],
        },
        # Month 3: 2026-06
        {
            "specialty": "family_medicine",
            "timestamp": "2026-06-01T10:00:00Z",
            "findings": [
                {"rule_id": "rule_ahcip_missing_modifier_25", "estimated_value": 50.0},
            ],
        },
        # Different specialty — must be filtered out.
        {
            "specialty": "cardiology",
            "timestamp": "2026-06-02T10:00:00Z",
            "findings": [
                {
                    "rule_id": "rule_ahcip_missing_modifier_25",
                    "estimated_value": 9999.0,
                },
            ],
        },
    ]


# ---------------------------------------------------------------------------
# 1. Specialty filtering
# ---------------------------------------------------------------------------


def test_specialty_filter_excludes_other_specialties(
    family_medicine_records: list[dict],
) -> None:
    result = top_missed_revenue_patterns("family_medicine", family_medicine_records)
    # cardiology record's $9999 finding must NOT be in any pattern.
    for p in result["patterns"]:
        assert p["total_dollars"] < 1000.0


def test_specialty_match_is_case_insensitive(
    family_medicine_records: list[dict],
) -> None:
    result = top_missed_revenue_patterns("Family_Medicine", family_medicine_records)
    assert (
        result["records_kept"] == 3
    )  # 3 family-medicine records, 1 cardiology excluded


def test_no_specialty_aggregates_everything() -> None:
    records = [
        {
            "specialty": "family_medicine",
            "timestamp": "2026-04-01T00:00:00Z",
            "findings": [
                {"rule_id": "rule_ahcip_missing_modifier_25", "estimated_value": 50.0}
            ],
        },
        {
            "specialty": "cardiology",
            "timestamp": "2026-05-01T00:00:00Z",
            "findings": [
                {"rule_id": "rule_ahcip_missing_modifier_25", "estimated_value": 50.0}
            ],
        },
        {
            "specialty": "dermatology",
            "timestamp": "2026-06-01T00:00:00Z",
            "findings": [
                {"rule_id": "rule_ahcip_missing_modifier_25", "estimated_value": 50.0}
            ],
        },
    ]
    result = top_missed_revenue_patterns("", records)
    assert result["records_kept"] == 3
    # Aggregated across all three specialties: 3 × $50 = $150
    assert result["patterns"][0]["total_dollars"] == 150.0


# ---------------------------------------------------------------------------
# 2. Score calculation and ranking
# ---------------------------------------------------------------------------


def test_score_is_count_times_total_dollars(
    family_medicine_records: list[dict],
) -> None:
    result = top_missed_revenue_patterns("family_medicine", family_medicine_records)
    patterns = {p["pattern"]: p for p in result["patterns"]}
    # rule_ahcip_missing_modifier_25: 4 findings × $50 = $200, score = 4 × 200 = 800
    assert patterns["rule_ahcip_missing_modifier_25"]["count"] == 4
    assert patterns["rule_ahcip_missing_modifier_25"]["total_dollars"] == 200.0
    assert patterns["rule_ahcip_missing_modifier_25"]["score"] == 800.0
    # em_level_upcode: 2 findings × $90 = $180, score = 2 × 180 = 360
    assert patterns["em_level_upcode"]["count"] == 2
    assert patterns["em_level_upcode"]["total_dollars"] == 180.0
    assert patterns["em_level_upcode"]["score"] == 360.0


def test_ranking_is_descending_by_score(
    family_medicine_records: list[dict],
) -> None:
    result = top_missed_revenue_patterns("family_medicine", family_medicine_records)
    scores = [p["score"] for p in result["patterns"]]
    assert scores == sorted(scores, reverse=True)
    # Highest-score pattern is the modifier-25 one.
    assert result["patterns"][0]["pattern"] == "rule_ahcip_missing_modifier_25"


def test_top_n_caps_results(family_medicine_records: list[dict]) -> None:
    result = top_missed_revenue_patterns(
        "family_medicine", family_medicine_records, top_n=1
    )
    assert len(result["patterns"]) == 1


# ---------------------------------------------------------------------------
# 3. Insufficient-data gate
# ---------------------------------------------------------------------------


def test_insufficient_data_flag_when_under_min_months() -> None:
    records = [
        {
            "specialty": "family_medicine",
            "timestamp": "2026-06-15T10:00:00Z",
            "findings": [
                {"rule_id": "rule_ahcip_missing_modifier_25", "estimated_value": 50.0}
            ],
        },
    ]
    result = top_missed_revenue_patterns("family_medicine", records)
    assert result["months_covered"] == 1
    assert result["insufficient_data"] is True


def test_sufficient_data_flag_when_at_or_above_min_months(
    family_medicine_records: list[dict],
) -> None:
    result = top_missed_revenue_patterns("family_medicine", family_medicine_records)
    assert result["months_covered"] >= 3
    assert result["insufficient_data"] is False


def test_min_months_parameter_overrides_default() -> None:
    records = [
        {
            "specialty": "family_medicine",
            "timestamp": "2026-04-01T00:00:00Z",
            "findings": [
                {"rule_id": "rule_ahcip_missing_modifier_25", "estimated_value": 50.0}
            ],
        },
        {
            "specialty": "family_medicine",
            "timestamp": "2026-05-01T00:00:00Z",
            "findings": [
                {"rule_id": "rule_ahcip_missing_modifier_25", "estimated_value": 50.0}
            ],
        },
    ]
    # 2 months is "insufficient" at the default (3) but "sufficient" at 2.
    assert (
        top_missed_revenue_patterns("family_medicine", records)["insufficient_data"]
        is True
    )
    assert (
        top_missed_revenue_patterns("family_medicine", records, min_months=2)[
            "insufficient_data"
        ]
        is False
    )


# ---------------------------------------------------------------------------
# 4. JSONL path input
# ---------------------------------------------------------------------------


def test_accepts_path_to_jsonl(
    tmp_path: Path, family_medicine_records: list[dict]
) -> None:
    jsonl_path = tmp_path / "audit.jsonl"
    with jsonl_path.open("w") as fh:
        for r in family_medicine_records:
            fh.write(json.dumps(r) + "\n")
    result = top_missed_revenue_patterns("family_medicine", jsonl_path)
    assert result["records_seen"] == 4
    assert result["records_kept"] == 3
    assert result["patterns"][0]["pattern"] == "rule_ahcip_missing_modifier_25"


def test_jsonl_skips_malformed_lines(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "audit.jsonl"
    with jsonl_path.open("w") as fh:
        fh.write("not json\n")
        fh.write(
            json.dumps(
                {
                    "specialty": "family_medicine",
                    "timestamp": "2026-04-01T00:00:00Z",
                    "findings": [
                        {
                            "rule_id": "rule_ahcip_missing_modifier_25",
                            "estimated_value": 50.0,
                        }
                    ],
                }
            )
            + "\n"
        )
        fh.write("\n")  # blank line
    result = top_missed_revenue_patterns("family_medicine", jsonl_path)
    assert result["records_seen"] == 1


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_patterns(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "empty.jsonl"
    jsonl_path.write_text("")
    result = top_missed_revenue_patterns("family_medicine", jsonl_path)
    assert result["patterns"] == []
    assert result["records_kept"] == 0
    assert result["months_covered"] == 0
    assert result["insufficient_data"] is True


def test_findings_with_zero_amount_are_filtered() -> None:
    records = [
        {
            "specialty": "family_medicine",
            "timestamp": "2026-04-01T00:00:00Z",
            "findings": [
                {"rule_id": "rule_ahcip_missing_modifier_25", "estimated_value": 0.0}
            ],
        },
    ]
    result = top_missed_revenue_patterns("family_medicine", records, min_months=1)
    assert result["patterns"] == []


def test_pattern_key_falls_back_to_category() -> None:
    assert _pattern_key({"category": "undercode"}) == "undercode"
    assert _pattern_key({"rule_id": "R-MOD-25", "category": "undercode"}) == "R-MOD-25"
    assert _pattern_key({}) == "(unknown)"


def test_month_key_handles_short_and_long_iso() -> None:
    assert _month_key("2026-06-15T12:34:56Z") == "2026-06"
    assert _month_key("2026-06-15") == "2026-06"
    assert _month_key("not a date") == "unknown"
    assert _month_key("") == "unknown"


def test_is_missed_revenue_known_categories() -> None:
    assert _is_missed_revenue({"category": "missing_modifier_25"}) is True
    assert _is_missed_revenue({"category": "undercode"}) is True
    assert _is_missed_revenue({"rule_id": "rule_ahcip_missing_procedure"}) is True
    assert _is_missed_revenue({"rule_id": "em_level_upcode"}) is True


def test_is_missed_revenue_denial_is_not_missed_revenue() -> None:
    # A denial finding has a positive amount but is NOT missed-revenue.
    finding = {
        "category": "denial_catch",
        "estimated_value": 100.0,
    }
    assert _is_missed_revenue(finding) is False
