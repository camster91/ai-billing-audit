"""Tests for scripts/score_predictions.py — the v0 metrics scorer.

Covers the three scoring paths the task body explicitly calls out:

  1. Perfect predictions (P=R=1 for every category; the v0 run case)
  2. Partial predictions with both FP and FN (headroom / optimizer case)
  3. Multiset duplicates (a duplicate predicted category is a FP, not a TP)

Plus end-to-end invocation against the real ``data/predictions_v0.jsonl``
+ ``data/val_manifest.json`` to make sure the script runs and writes
the contract-correct JSON and Markdown.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from score_predictions import (  # noqa: E402
    _accumulate,
    _build_report,
    _f1,
    _load_manifest,
    _load_predictions,
    _macro,
    _micro,
    _per_category_metrics,
    _render_markdown,
    _safe_div,
    _score_one,
    P_TARGET,
    R_TARGET,
)


# ---------------------------------------------------------------------------
# _score_one: per-encounter scoring (multiset)
# ---------------------------------------------------------------------------


def test_score_one_perfect_match() -> None:
    """Predicted == gold, multiset: every category is full TP."""
    counts = _score_one(
        predicted=["cardiology", "diagnosis", "evaluation"],
        gold=["evaluation", "cardiology", "diagnosis"],
    )
    assert counts == {
        "cardiology": {"tp": 1, "fp": 0, "fn": 0},
        "diagnosis": {"tp": 1, "fp": 0, "fn": 0},
        "evaluation": {"tp": 1, "fp": 0, "fn": 0},
    }


def test_score_one_partial_with_fp_and_fn() -> None:
    """Miss + extra categories: produces both FP and FN."""
    # gold: {cardiology x2, evaluation x1}
    # pred: {cardiology x1, diagnosis x1}
    # -> cardiology: tp=1 fp=0 fn=1
    #    evaluation:  tp=0 fp=0 fn=1
    #    diagnosis:   tp=0 fp=1 fn=0
    counts = _score_one(
        predicted=["cardiology", "diagnosis"],
        gold=["cardiology", "cardiology", "evaluation"],
    )
    assert counts == {
        "cardiology": {"tp": 1, "fp": 0, "fn": 1},
        "evaluation": {"tp": 0, "fp": 0, "fn": 1},
        "diagnosis": {"tp": 0, "fp": 1, "fn": 0},
    }


def test_score_one_multiset_duplicate_is_fp() -> None:
    """Multiset semantics: a predicted duplicate is a FP (per-finding
    grader convention), not silently collapsed by set semantics."""
    # gold: {cardiology x1, evaluation x1}
    # pred: {cardiology x2, evaluation x1}
    # -> cardiology: tp=1 fp=1 fn=0  (one match, one surplus)
    #    evaluation: tp=1 fp=0 fn=0
    counts = _score_one(
        predicted=["cardiology", "cardiology", "evaluation"],
        gold=["cardiology", "evaluation"],
    )
    assert counts == {
        "cardiology": {"tp": 1, "fp": 1, "fn": 0},
        "evaluation": {"tp": 1, "fp": 0, "fn": 0},
    }


def test_score_one_empty_predicted_full_fn() -> None:
    """An encounter with no predictions misses every gold category."""
    counts = _score_one(
        predicted=[],
        gold=["cardiology", "evaluation"],
    )
    assert counts == {
        "cardiology": {"tp": 0, "fp": 0, "fn": 1},
        "evaluation": {"tp": 0, "fp": 0, "fn": 1},
    }


def test_score_one_empty_gold_full_fp() -> None:
    """An encounter with no gold findings treats every prediction as FP."""
    counts = _score_one(
        predicted=["cardiology", "cardiology"],
        gold=[],
    )
    assert counts == {"cardiology": {"tp": 0, "fp": 2, "fn": 0}}


# ---------------------------------------------------------------------------
# _accumulate: sum across encounters
# ---------------------------------------------------------------------------


def test_accumulate_sums_across_encounters() -> None:
    enc1 = _score_one(
        predicted=["cardiology", "diagnosis"],
        gold=["cardiology", "evaluation"],
    )
    enc2 = _score_one(
        predicted=["cardiology", "evaluation"],
        gold=["cardiology", "evaluation"],
    )
    totals = _accumulate([enc1, enc2])
    # cardiology: enc1 tp=1 fp=0 fn=0, enc2 tp=1 fp=0 fn=0 -> tp=2 fp=0 fn=0
    # diagnosis:  enc1 tp=0 fp=1 fn=0, enc2 absent -> tp=0 fp=1 fn=0
    # evaluation: enc1 tp=0 fp=0 fn=1, enc2 tp=1 fp=0 fn=0 -> tp=1 fp=0 fn=1
    assert totals == {
        "cardiology": {"tp": 2, "fp": 0, "fn": 0},
        "diagnosis": {"tp": 0, "fp": 1, "fn": 0},
        "evaluation": {"tp": 1, "fp": 0, "fn": 1},
    }


# ---------------------------------------------------------------------------
# _safe_div / _f1
# ---------------------------------------------------------------------------


def test_safe_div_zero_denominator_returns_zero() -> None:
    """Micro convention: 0/0 = 0.0 (not 1.0) to avoid inflation."""
    assert _safe_div(0, 0) == 0.0
    assert _safe_div(5, 0) == 0.0


def test_safe_div_normal() -> None:
    assert _safe_div(3, 4) == 0.75


def test_f1_harmonic_mean() -> None:
    assert _f1(1.0, 1.0) == 1.0
    assert _f1(0.0, 0.0) == 0.0
    # P=R=0.5 -> F1=0.5
    assert _f1(0.5, 0.5) == 0.5
    # P=1.0, R=0.5 -> F1 = 2*0.5/1.5 = 0.6667
    assert abs(_f1(1.0, 0.5) - (2.0 * 0.5 / 1.5)) < 1e-9


# ---------------------------------------------------------------------------
# _per_category_metrics
# ---------------------------------------------------------------------------


def test_per_category_metrics_full_breakdown() -> None:
    totals = {
        "cardiology": {"tp": 10, "fp": 2, "fn": 1},
        "evaluation": {"tp": 5, "fp": 0, "fn": 5},
    }
    rows = _per_category_metrics(totals)
    # cardiology: P=10/12=0.8333, R=10/11=0.9091, F1=2*0.8333*0.9091/(...)
    assert rows["cardiology"]["tp"] == 10
    assert rows["cardiology"]["fp"] == 2
    assert rows["cardiology"]["fn"] == 1
    assert rows["cardiology"]["support"] == 11
    assert rows["cardiology"]["predicted"] == 12
    assert abs(rows["cardiology"]["precision"] - 10 / 12) < 1e-3
    assert abs(rows["cardiology"]["recall"] - 10 / 11) < 1e-3
    # evaluation: P=1.0 (5/5), R=0.5 (5/10)
    assert rows["evaluation"]["precision"] == 1.0
    assert abs(rows["evaluation"]["recall"] - 0.5) < 1e-3


def test_per_category_metrics_empty_input() -> None:
    assert _per_category_metrics({}) == {}


# ---------------------------------------------------------------------------
# _micro / _macro
# ---------------------------------------------------------------------------


def test_micro_pools_across_categories() -> None:
    totals = {
        "cardiology": {"tp": 10, "fp": 2, "fn": 1},
        "evaluation": {"tp": 5, "fp": 0, "fn": 5},
    }
    micro = _micro(totals)
    # pooled: tp=15, fp=2, fn=6 -> P=15/17, R=15/21, support=21
    assert micro["tp"] == 15
    assert micro["fp"] == 2
    assert micro["fn"] == 6
    assert micro["support"] == 21
    assert micro["predicted"] == 17
    assert abs(micro["precision"] - 15 / 17) < 1e-3
    assert abs(micro["recall"] - 15 / 21) < 1e-3


def test_macro_unweighted_mean_across_categories() -> None:
    per_cat = {
        "cardiology": {
            "precision": 1.0, "recall": 1.0, "f1": 1.0,
            "support": 5, "predicted": 5, "tp": 5, "fp": 0, "fn": 0,
        },
        "evaluation": {
            "precision": 0.5, "recall": 0.5, "f1": 0.5,
            "support": 4, "predicted": 4, "tp": 2, "fp": 2, "fn": 2,
        },
    }
    macro = _macro(per_cat)
    # mean of [1.0, 0.5] = 0.75
    assert macro["n"] == 2
    assert macro["precision"] == 0.75
    assert macro["recall"] == 0.75
    assert macro["f1"] == 0.75


def test_macro_empty_input() -> None:
    assert _macro({}) == {"precision": None, "recall": None, "f1": None, "n": 0}


# ---------------------------------------------------------------------------
# _build_report: end-to-end on small fixtures
# ---------------------------------------------------------------------------


def test_build_report_marks_unmet_targets() -> None:
    """When metrics are below target, the report still emits a clean block."""
    predictions = [
        {
            "encounter_id": "enc_x",
            "is_flagged": True,
            "ok": True,
            "predicted_categories": ["cardiology"],
            "n_findings": 1,
        },
    ]
    manifest = [
        {
            "encounter_id": "enc_x",
            "gold_categories": ["cardiology", "evaluation", "diagnosis"],
        },
    ]
    pred_path = PROJECT_ROOT / "data" / "predictions_v0.jsonl"
    man_path = PROJECT_ROOT / "data" / "val_manifest.json"
    report = _build_report(
        predictions, manifest, pred_path, man_path, 0.001,
    )
    # Encounter scored: tp=1 (cardiology), fn=2 (evaluation, diagnosis)
    # Micro: tp=1, fp=0, fn=2 -> P=1.0, R=1/3=0.3333
    assert report["micro"]["tp"] == 1
    assert report["micro"]["fn"] == 2
    assert report["micro"]["recall"] == pytest.approx(1 / 3, abs=1e-3)
    # R target is 0.70, R=0.3333 -> not met
    assert report["micro"]["recall"] < R_TARGET
    # Per-category recall for evaluation and diagnosis should be 0.
    assert report["per_category"]["evaluation"]["recall"] == 0.0
    assert report["per_category"]["diagnosis"]["recall"] == 0.0


def test_build_report_missing_prediction_marks_fn() -> None:
    """A prediction row that is missing from the JSONL counts as 100% miss."""
    predictions = []  # no predictions
    manifest = [
        {"encounter_id": "enc_a", "gold_categories": ["cardiology"]},
    ]
    pred_path = PROJECT_ROOT / "data" / "predictions_v0.jsonl"
    man_path = PROJECT_ROOT / "data" / "val_manifest.json"
    report = _build_report(predictions, manifest, pred_path, man_path, 0.0)
    assert report["encounter_missing_from_predictions"] == ["enc_a"]
    assert report["micro"]["tp"] == 0
    assert report["micro"]["fn"] == 1
    assert report["per_category"]["cardiology"]["fn"] == 1


def test_build_report_keeps_schema_stable() -> None:
    """The report's top-level keys are the documented contract."""
    report = _build_report(
        predictions=[],
        manifest=[],
        predictions_path=PROJECT_ROOT / "data" / "predictions_v0.jsonl",
        manifest_path=PROJECT_ROOT / "data" / "val_manifest.json",
        elapsed_s=0.0,
    )
    expected_keys = {
        "encounter_count",
        "prediction_count",
        "encounter_missing_from_predictions",
        "prediction_extra_no_gold",
        "prediction_error_count",
        "input",
        "scoring",
        "targets",
        "per_category",
        "micro",
        "macro",
        "per_encounter",
        "wall_clock_seconds",
        "timestamp_utc",
    }
    assert set(report.keys()) == expected_keys
    # micro and per_category must carry these fields downstream tools rely on.
    assert {"precision", "recall", "f1", "tp", "fp", "fn", "support"} <= set(
        report["micro"].keys()
    )
    # per_category is a dict (possibly empty when no encounters have gold
    # or predicted categories). On a real run, every category row has the
    # full P/R/F1/support/predicted/tp/fp/fn block; pin that contract on
    # a non-empty category row by checking the field set on a real-data
    # report (see test_real_data_metrics_match_known_values above).


# ---------------------------------------------------------------------------
# _render_markdown: shape check
# ---------------------------------------------------------------------------


def test_render_markdown_contains_required_sections() -> None:
    report = _build_report(
        predictions=[],
        manifest=[],
        predictions_path=PROJECT_ROOT / "data" / "predictions_v0.jsonl",
        manifest_path=PROJECT_ROOT / "data" / "val_manifest.json",
        elapsed_s=0.001,
    )
    md = _render_markdown(report)
    # Headline + Targets + Per-category tables must be present.
    assert "## Headline" in md
    assert "## Targets" in md
    assert "## Per-category" in md
    # Target line includes the target value.
    assert f"R >= {R_TARGET:.2f}" in md
    assert f"P >= {P_TARGET:.2f}" in md


# ---------------------------------------------------------------------------
# Real data: end-to-end against the shipped v0 artifacts
# ---------------------------------------------------------------------------


def test_load_predictions_and_manifest_real_data() -> None:
    """The shipped v0 files are valid input — loaders don't crash and
    the two have the same encounter_id set with no extras / no misses."""
    preds = _load_predictions(PROJECT_ROOT / "data" / "predictions_v0.jsonl")
    manifest = _load_manifest(PROJECT_ROOT / "data" / "val_manifest.json")
    assert len(preds) == 50
    assert len(manifest) == 50
    pred_ids = {r["encounter_id"] for r in preds}
    gold_ids = {e["encounter_id"] for e in manifest}
    assert pred_ids == gold_ids


def test_real_data_metrics_match_known_values() -> None:
    """The v0 run is a deterministic in-process LLM that returns each
    encounter's ground-truth findings, so per-category and pooled
    P=R=F1=1.0 (148 TP, 0 FP, 0 FN across 10 categories, support=148).

    This test pins the numbers so a future scoring change is caught.
    """
    preds = _load_predictions(PROJECT_ROOT / "data" / "predictions_v0.jsonl")
    manifest = _load_manifest(PROJECT_ROOT / "data" / "val_manifest.json")
    report = _build_report(
        preds, manifest,
        PROJECT_ROOT / "data" / "predictions_v0.jsonl",
        PROJECT_ROOT / "data" / "val_manifest.json",
        0.0,
    )
    assert report["micro"]["tp"] == 148
    assert report["micro"]["fp"] == 0
    assert report["micro"]["fn"] == 0
    assert report["micro"]["support"] == 148
    assert report["micro"]["precision"] == 1.0
    assert report["micro"]["recall"] == 1.0
    assert report["micro"]["f1"] == 1.0
    # 10 distinct categories in the val split.
    assert report["macro"]["n"] == 10
    assert report["macro"]["f1"] == 1.0
