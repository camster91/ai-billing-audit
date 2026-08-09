"""Tests for the per-rule-family recall scorer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_billing_audit.eval.per_rule_scorer import (
    _aggregate,
    _bucket_metrics,
    _code_level,
    _finding_key,
    _rule_family,
    _safe_pr,
    score,
)


def _write(tmp_path: Path, name: str, obj) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _write_jsonl(tmp_path: Path, name: str, rows) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


# ---- keying + bucketing helpers ------------------------------------------


def test_finding_key_uses_rule_id_only():
    assert _finding_key({"rule_id": "MOD-25", "severity": "high"}) == "MOD-25"
    assert _finding_key({"rule_id": "  ", "severity": "high"}) == ""
    assert _finding_key({}) == ""


@pytest.mark.parametrize(
    "rule_id,family",
    [
        ("MOD-25", "modifier:MOD-25"),
        ("MOD-59", "modifier:MOD-59"),
        ("MOD-77", "modifier"),  # unknown modifier subrule → family only
        ("E/M-99213", "code_level"),
        ("EM-99214", "code_level"),
        ("CPT-20610", "code_level"),
        ("DX-Z00.00", "dx_procedure"),
        ("DXC-M25.50", "dx_procedure"),
        ("NCCI-12345", "ncci_mue_time"),
        ("MUE-99214", "ncci_mue_time"),
        ("TIME-30min", "ncci_mue_time"),
        ("DOC-INCOMPLETE", "doc_adequacy"),
        ("FOO-1", "other"),
    ],
)
def test_rule_family_bucketing(rule_id, family):
    assert _rule_family(rule_id) == family


@pytest.mark.parametrize(
    "rule_id,level",
    [
        ("E/M-99213", "E/M"),
        ("EM-99214", "E/M"),
        ("RAD-71045", "imaging"),
        ("IMG-CT-001", "imaging"),
        ("LAB-CBC", "lab"),
        ("PATH-88305", "lab"),
        ("CPT-20610", "procedural"),
        ("FOO-1", "other"),
    ],
)
def test_code_level_bucketing(rule_id, level):
    assert _code_level(rule_id) == level


def test_safe_pr_zero_denom():
    assert _safe_pr(0, 0, 0) == {"precision": 0.0, "recall": 0.0, "f1": 0.0}


def test_safe_pr_perfect():
    # All GT positives recalled, no false alarms, no missed GT positives.
    out = _safe_pr(tp=10, fp=0, fn=0)
    assert out["precision"] == 1.0
    assert out["recall"] == 1.0
    assert out["f1"] == 1.0


def test_safe_pr_zero_gt_recall_undefined():
    # No ground-truth positives → recall is undefined; we report 0.0 by convention.
    out = _safe_pr(tp=0, fp=3, fn=0)
    assert out["precision"] == 0.0
    assert out["recall"] == 0.0
    assert out["f1"] == 0.0


def test_aggregate_sums_rows():
    rows = [(1, 0, 1), (0, 1, 0), (1, 1, 1)]
    out = _aggregate(rows)
    assert out["tp"] == 2 and out["fp"] == 2 and out["fn"] == 2
    assert out["n"] == 3
    assert out["precision"] == 0.5
    assert out["recall"] == 0.5
    assert out["f1"] == 0.5


# ---- end-to-end scoring on a tiny synthetic val+preds --------------------


def _val_with(*encounters):
    return {
        "encounters": [
            {"encounter_id": eid, "ground_truth": gt} for eid, gt in encounters
        ]
    }


def test_score_end_to_end_two_encounters(tmp_path: Path):
    val = _val_with(
        ("e1", [{"rule_id": "MOD-25"}, {"rule_id": "E/M-99213"}]),
        ("e2", [{"rule_id": "NCCI-12345"}]),
    )
    val_path = _write(tmp_path, "val.json", val)
    preds_path = _write_jsonl(
        tmp_path,
        "preds.jsonl",
        [
            {
                "encounter_id": "e1",
                "ok": True,
                "is_flagged": True,
                "findings": [{"rule_id": "MOD-25"}],  # missing E/M rule
            },
            {
                "encounter_id": "e2",
                "ok": True,
                "is_flagged": False,
                "findings": [{"rule_id": "NCCI-12345"}],  # match
            },
        ],
    )
    report = score(val_path, preds_path)

    assert report["n_encounters"] == 2
    assert report["n_ok"] == 2
    assert report["overall"]["tp"] == 2
    assert report["overall"]["fp"] == 0
    assert report["overall"]["fn"] == 1

    # MOD-25 should appear as a modifier sub-rule bucket with its own row.
    assert "modifier:MOD-25" in report["by_rule_family"]
    # E/M should appear under code_level via _code_level bucket.
    assert "E/M" in report["by_code_level"]
    # NCCI is in ncci_mue_time family.
    assert "ncci_mue_time" in report["by_rule_family"]


def test_score_handles_errors(tmp_path: Path):
    val = _val_with(("e1", [{"rule_id": "MOD-25"}]))
    val_path = _write(tmp_path, "val.json", val)
    preds_path = _write_jsonl(
        tmp_path,
        "preds.jsonl",
        [{"encounter_id": "e1", "ok": False, "is_flagged": False, "findings": []}],
    )
    report = score(val_path, preds_path)
    assert report["n_errors"] == 1
    assert report["overall"]["tp"] == 0
    assert report["overall"]["fn"] == 1


def test_bucket_metrics_disjoint():
    tp, fp, fn = _bucket_metrics({"a", "b"}, {"b", "c"})
    assert (tp, fp, fn) == (1, 1, 1)
