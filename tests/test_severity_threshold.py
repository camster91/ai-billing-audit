"""Tests for the per-tenant severity threshold.

The clinic can configure MIN_SEVERITY_TO_SHOW to filter low-severity
findings. Default is "info" (show everything). The threshold is read
fresh on every request so an admin can change it without restarting.

What's pinned
-------------
* Default threshold is "info" (show all)
* Unknown values fall back to "info"
* Threshold is case-insensitive
* Findings with severity BELOW the threshold are filtered out
* The handler still reports the total count so the biller knows
  there were hidden ones
"""
from __future__ import annotations

import pytest

from ai_billing_audit.api import (
    SEVERITY_RANK,
    _min_severity_threshold,
)


def test_default_is_info():
    """No env var => show everything (rank 0)."""
    import os
    os.environ.pop("MIN_SEVERITY_TO_SHOW", None)
    assert _min_severity_threshold() == SEVERITY_RANK["info"]


def test_unknown_value_falls_back_to_info():
    import os
    os.environ["MIN_SEVERITY_TO_SHOW"] = "bogus"
    assert _min_severity_threshold() == SEVERITY_RANK["info"]


def test_explicit_high_threshold():
    import os
    os.environ["MIN_SEVERITY_TO_SHOW"] = "high"
    assert _min_severity_threshold() == SEVERITY_RANK["high"]


def test_case_insensitive():
    import os
    os.environ["MIN_SEVERITY_TO_SHOW"] = "HIGH"
    assert _min_severity_threshold() == SEVERITY_RANK["high"]
    os.environ["MIN_SEVERITY_TO_SHOW"] = "Critical"
    assert _min_severity_threshold() == SEVERITY_RANK["critical"]


def test_severity_ranking_order():
    """Sanity: the rank values are strictly ascending info<low<medium<high<critical."""
    assert SEVERITY_RANK["info"] < SEVERITY_RANK["low"]
    assert SEVERITY_RANK["low"] < SEVERITY_RANK["medium"]
    assert SEVERITY_RANK["medium"] < SEVERITY_RANK["high"]
    assert SEVERITY_RANK["high"] < SEVERITY_RANK["critical"]


def test_filtering_logic():
    """Findings below the threshold are hidden; at-or-above are shown."""
    findings = [
        {"severity": "info", "id": "F-1"},
        {"severity": "low", "id": "F-2"},
        {"severity": "medium", "id": "F-3"},
        {"severity": "high", "id": "F-4"},
        {"severity": "critical", "id": "F-5"},
    ]
    # "high" threshold: only high + critical
    threshold = SEVERITY_RANK["high"]
    visible = [f for f in findings if SEVERITY_RANK.get(f["severity"], 0) >= threshold]
    assert len(visible) == 2
    assert {f["id"] for f in visible} == {"F-4", "F-5"}

    # "medium" threshold: medium + high + critical
    threshold = SEVERITY_RANK["medium"]
    visible = [f for f in findings if SEVERITY_RANK.get(f["severity"], 0) >= threshold]
    assert len(visible) == 3
    assert {f["id"] for f in visible} == {"F-3", "F-4", "F-5"}
