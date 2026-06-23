"""Unit tests for the per-encounter grading decomposition in
``scripts/aggregate_metrics.py``.

The aggregate metrics script decomposes the encounter-level
``MatchResult`` (tp/fp/fn + matches/unmatched indices) into per-category
counts. The decomposition is the load-bearing piece of the script —
if the bookkeeping is wrong, the per-category recall numbers in the
JSON output are wrong even when the totals reconcile.

These tests cover the four interesting decomposition shapes:

  1. Perfect match (every predicted == every gold)
  2. All FPs (predicted findings with no gold)
  3. All FNs (gold findings with no predictions)
  4. Mixed (some TPs, some FPs, some FNs across multiple categories)
  5. A category that appears in gold only (FN-only)
  6. A category that appears in predicted only (FP-only)

The test feeds hand-crafted (predicted, ground_truth) pairs through
``_grade_one_encounter``'s grading path, but skips the
``run_audit``/LLM step by stubbing the audit to return a deterministic
list of Finding dataclasses. This isolates the per-category
decomposition from the LLM fixture.

Implementation note: the script lives under ``scripts/`` (not the
``ai_billing_audit`` package), so we import it as a top-level module
named ``aggregate_metrics``. The import is wrapped in a session-scoped
fixture so each test does not re-execute the script's top-level
``from ai_billing_audit.auditor import run_audit`` (which would
otherwise happen on every test and pollute the import cache).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
SRC_DIR = ROOT / "src"
# Make ``ai_billing_audit`` importable for the script's imports.
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(scope="module")
def agg():
    """Import the aggregate_metrics script once per test module."""
    spec = importlib.util.spec_from_file_location(
        "aggregate_metrics", SCRIPTS_DIR / "aggregate_metrics.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["aggregate_metrics"] = module
    spec.loader.exec_module(module)
    return module


from ai_billing_audit.auditor import Finding, AuditResult  # noqa: E402


def _build_audit_result(findings_spec: list[dict]) -> AuditResult:
    """Build an AuditResult from a list of {category, suggested_code, quote} dicts."""
    findings = tuple(
        Finding(
            category=f["category"],
            suggested_code=f["suggested_code"],
            quote=f["quote"],
            severity="info",
            rule_ids=(),
        )
        for f in findings_spec
    )
    return AuditResult(
        encounter_id="enc_test",
        findings=findings,
        summary="stub",
    )


def _patch_run_audit(monkeypatch, agg_module, expected_predicted: list[dict]) -> None:
    """Replace ``run_audit`` on the loaded module with a stub.

    The stub replaces the function on the loaded module's namespace —
    NOT on ``ai_billing_audit.auditor.run_audit`` itself, so other
    tests that import run_audit see the original.
    """
    expected = _build_audit_result(expected_predicted)

    def _fake_run_audit(encounter, llm, prompt_path):  # noqa: ARG001
        return expected

    monkeypatch.setattr(agg_module, "run_audit", _fake_run_audit)


def _encounter(ground_truth: list[dict]) -> dict:
    """Build a minimal encounter record for _grade_one_encounter."""
    return {
        "encounter_id": "enc_test",
        "is_flagged": bool(ground_truth),
        "clinical_note": "stub",
        "claim": {"cpt_codes": [], "icd10_codes": []},
        "rules": [],
        "ground_truth": ground_truth,
    }


def _gt(category: str, code: str, quote: str) -> dict:
    return {
        "category": category,
        "suggested_code": code,
        "clinical_evidence_quote": quote,
    }


def test_perfect_match_each_category(monkeypatch, agg):
    """Every predicted finding matches a gold finding → tp = gold for every category."""
    enc = _encounter(
        [
            _gt("cardiology", "93000", "ECG performed in office"),
            _gt("evaluation", "99214", "established patient moderate complexity"),
        ]
    )
    _patch_run_audit(monkeypatch, agg,
        [
            {
                "category": "cardiology",
                "suggested_code": "93000",
                "quote": "ECG performed in office",
            },
            {
                "category": "evaluation",
                "suggested_code": "99214",
                "quote": "established patient moderate complexity",
            },
        ],
    )

    r = agg._grade_one_encounter(enc, None, Path("/tmp/prompt.txt"))
    assert r["tp"] == 2 and r["fp"] == 0 and r["fn"] == 0
    assert r["precision"] == 1.0 and r["recall"] == 1.0
    assert r["per_category"]["cardiology"] == {
        "tp": 1, "fp": 0, "fn": 0, "gold": 1, "predicted": 1,
    }
    assert r["per_category"]["evaluation"] == {
        "tp": 1, "fp": 0, "fn": 0, "gold": 1, "predicted": 1,
    }


def test_all_unmatched_predicted(monkeypatch, agg):
    """Predicted findings with no matching gold → all FPs, all categories show 0 fn."""
    enc = _encounter([])  # no gold
    _patch_run_audit(monkeypatch, agg,
        [
            {
                "category": "modifier",
                "suggested_code": "modifier 25",
                "quote": "modifier 25 applied",
            },
        ],
    )
    r = agg._grade_one_encounter(enc, None, Path("/tmp/prompt.txt"))
    assert r["tp"] == 0 and r["fp"] == 1 and r["fn"] == 0
    assert r["per_category"]["modifier"] == {
        "tp": 0, "fp": 1, "fn": 0, "gold": 0, "predicted": 1,
    }


def test_all_unmatched_ground_truth(monkeypatch, agg):
    """Gold findings with no predicted findings → all FNs, predicted count = 0."""
    enc = _encounter(
        [_gt("laboratory", "80053", "lipid panel ordered")]
    )
    _patch_run_audit(monkeypatch, agg, [])  # no predicted
    r = agg._grade_one_encounter(enc, None, Path("/tmp/prompt.txt"))
    assert r["tp"] == 0 and r["fp"] == 0 and r["fn"] == 1
    assert r["per_category"]["laboratory"] == {
        "tp": 0, "fp": 0, "fn": 1, "gold": 1, "predicted": 0,
    }


def test_mixed_three_categories(monkeypatch, agg):
    """Mixed TPs/FPs/FNs across three categories with correct bookkeeping."""
    enc = _encounter(
        [
            _gt("cardiology", "93000", "ECG performed in office"),
            _gt("cardiology", "93040", "rhythm strip reviewed"),
            _gt("laboratory", "80053", "lipid panel ordered"),
        ]
    )
    # 2 TPs (cardiology 93000, cardiology 93040) + 1 FP (modifier) +
    # 1 FN (laboratory).
    _patch_run_audit(monkeypatch, agg,
        [
            {
                "category": "cardiology",
                "suggested_code": "93000",
                "quote": "ECG performed in office",
            },
            {
                "category": "cardiology",
                "suggested_code": "93040",
                "quote": "rhythm strip reviewed",
            },
            {
                "category": "modifier",
                "suggested_code": "modifier 25",
                "quote": "modifier 25 applied",
            },
        ],
    )
    r = agg._grade_one_encounter(enc, None, Path("/tmp/prompt.txt"))
    assert r["tp"] == 2 and r["fp"] == 1 and r["fn"] == 1
    assert r["per_category"]["cardiology"] == {
        "tp": 2, "fp": 0, "fn": 0, "gold": 2, "predicted": 2,
    }
    assert r["per_category"]["laboratory"] == {
        "tp": 0, "fp": 0, "fn": 1, "gold": 1, "predicted": 0,
    }
    assert r["per_category"]["modifier"] == {
        "tp": 0, "fp": 1, "fn": 0, "gold": 0, "predicted": 1,
    }


def test_per_category_recall_handles_zero_support(agg):
    """Categories with zero gold report recall=None, support=0."""
    per_encounter = [
        # Encounter 1: has cardiology + evaluation
        {
            "per_category": {
                "cardiology": {"tp": 1, "fp": 0, "fn": 0, "gold": 1, "predicted": 1},
                "evaluation": {"tp": 1, "fp": 0, "fn": 0, "gold": 1, "predicted": 1},
            }
        },
        # Encounter 2: only cardiology
        {
            "per_category": {
                "cardiology": {"tp": 2, "fp": 0, "fn": 0, "gold": 2, "predicted": 2},
            }
        },
    ]
    out = agg._per_category_recall(
        per_encounter, ("cardiology", "modifier", "under_coding")
    )
    assert out["cardiology"] == {"recall": 1.0, "support": 3, "tp": 3, "fn": 0}
    # modifier: 0 gold across the split
    assert out["modifier"] == {"recall": None, "support": 0, "tp": 0, "fn": 0}
    # under_coding: also zero
    assert out["under_coding"] == {"recall": None, "support": 0, "tp": 0, "fn": 0}


def test_macro_average_across_encounters(agg):
    """Macro P/R/F1 is the unweighted mean across encounters."""
    per_encounter = [
        {"precision": 1.0, "recall": 1.0, "f1": 1.0},
        {"precision": 0.5, "recall": 1.0, "f1": 2 * 0.5 / 1.5},
        {"precision": 0.0, "recall": 0.0, "f1": 0.0},
    ]
    out = agg._macro_across_encounters(per_encounter)
    assert out["n"] == 3
    # Mean precision = (1.0 + 0.5 + 0.0) / 3 = 0.5
    assert out["precision"] == 0.5
    # Mean recall = (1.0 + 1.0 + 0.0) / 3 = 0.6667
    assert out["recall"] == 0.6667


def test_overall_micro_aggregates_counts(agg):
    """Overall (micro) is the pooled tp/fp/fn across encounters."""
    per_encounter = [
        {"tp": 3, "fp": 1, "fn": 0},
        {"tp": 2, "fp": 0, "fn": 1},
        {"tp": 0, "fp": 0, "fn": 0},  # empty encounter
    ]
    out = agg._overall_micro(per_encounter)
    assert out["tp"] == 5
    assert out["fp"] == 1
    assert out["fn"] == 1
    assert out["support"] == 6  # tp + fn
    # Round to 4dp the way the script does; raw value is 5/6.
    assert out["precision"] == round(5 / 6, 4)
    assert out["recall"] == round(5 / 6, 4)
    # f1 = 2 * (5/6) * (5/6) / (5/6 + 5/6) = 5/6 (when P == R).
    assert out["f1"] == round(5 / 6, 4)


def test_render_markdown_matches_json(agg, tmp_path):
    """The markdown table's floats equal the JSON's floats exactly."""
    report = {
        "encounter_count": 50,
        "encounter_error_count": 0,
        "input": {
            "val_path": "data/synth/val.json",
            "prompt_path": "prompts/v0/auditor_prompt.txt",
            "llm_provider": "smoke",
            "llm_model": "stub",
        },
        "convention": {
            "macro": "stub",
            "per_category_recall": "stub",
            "overall": "stub",
        },
        "spec_categories": ["under_coding", "missed_charge", "modifier"],
        "spec_category_note": "stub note",
        "overall": {
            "precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 164,
            "tp": 164, "fp": 0, "fn": 0,
        },
        "macro": {
            "precision": 1.0, "recall": 1.0, "f1": 1.0, "n": 50,
        },
        "per_category": {
            "under_coding": {"recall": None, "support": 0, "tp": 0, "fn": 0},
            "missed_charge": {"recall": None, "support": 0, "tp": 0, "fn": 0},
            "modifier": {"recall": 1.0, "support": 3, "tp": 3, "fn": 0},
        },
        "wall_clock_seconds": 0.0,
        "timestamp_utc": "2026-06-17T00:00:00Z",
        "per_encounter": [],
    }
    md = agg._render_markdown(report)
    # The headline row should contain 1.0000 three times for the
    # overall (micro) row.
    assert "| overall (micro) | 1.0000 | 1.0000 | 1.0000 | 164 |" in md
    # The macro row.
    assert "| macro (mean across encounters) | 1.0000 | 1.0000 | 1.0000 | 50 |" in md
    # The per-category rows.
    assert "| under_coding | N/A | N/A | N/A | 0 |" in md
    assert "| missed_charge | N/A | N/A | N/A | 0 |" in md
    assert "| modifier | N/A | 1.0000 | N/A | 3 |" in md
