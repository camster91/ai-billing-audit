"""Per-category precision/recall/F1 scorer for task t_471a8e77.

Reads the predictions file produced by ``run_v0_auditor.py`` (task
t_336c0fa2) and scores it against the gold manifest produced by
``generate_test_split.py`` (task t_0_root). Emits per-category and
pooled micro/macro P/R/F1 as JSON and as a human-readable Markdown
table.

Scoring contract
----------------
The "category" of a finding is the field used as the matching key. The
predictions file already contains a ``predicted_categories`` field per
record (sorted unique category list emitted by the auditor) and the
gold manifest contains a ``gold_categories`` field per entry (sorted
unique category list from the encounter's ground-truth findings). We
compare these two as multisets of categories and accumulate
TP / FP / FN counts per category across the whole split.

Why category-level (not finding-level)?
---------------------------------------
The full per-finding grader (``ai_billing_audit.grading.match_findings``)
matches on category + suggested_code + 80% Jaccard quote overlap. That
is the right contract for the per-finding audit task. For this metrics
report we deliberately use the *category* field as the only matching
key because:

  1. The task body asks for "per-category R, P, F1" — i.e. the metrics
     are organized by category, with one number per category.
  2. The category is the only field the optimizer can reliably act on
     (changing which categories a prompt asks the auditor to look for
     is the most direct lever; suggested_code and quote are emergent
     from the encounter text).
  3. A finding-level score would conflate category-coverage errors
     with finding-extraction errors, making it hard to see whether the
     optimizer needs to add/remove categories or just fix extraction.

Multiset semantics
------------------
We use *multiset* (bag) semantics, not set semantics. If a gold
encounter has two findings both in ``evaluation`` and the prediction
also emits two ``evaluation`` findings, that is 2 TP / 0 FP / 0 FN for
``evaluation`` — not 1 TP because the duplicate would be collapsed
under set semantics. This matches the per-finding grader convention
(the grader counts the unmatched_predicted list as FPs and the
unmatched_ground_truth list as FNs, with no set-deduplication).

Outputs (paths configurable via env vars, see main()):

  METRICS_JSON_PATH  default: data/metrics_v0.json
  METRICS_MD_PATH    default: data/metrics_v0.md

Input locations (env-overridable):

  PREDICTIONS_PATH   default: data/predictions_v0.jsonl
  MANIFEST_PATH      default: data/val_manifest.json

Usage:
    cd /Users/biancabienaime/projects/ai-billing-audit
    python scripts/score_predictions.py
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PREDICTIONS_PATH = PROJECT_ROOT / "data" / "predictions_v0.jsonl"
MANIFEST_PATH = PROJECT_ROOT / "data" / "val_manifest.json"
DEFAULT_JSON_PATH = PROJECT_ROOT / "data" / "metrics_v0.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "data" / "metrics_v0.md"

# Acceptance thresholds from the task body. The script always emits a
# clean report; these are reported as ``met`` / ``not met`` so the
# optimizer has a target to chase.
R_TARGET = 0.70
P_TARGET = 0.60


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _load_predictions(path: Path) -> list[dict]:
    """Load predictions JSONL; each line is a record keyed by encounter_id.

    Drops any record that is not ``ok`` (the run_v0_auditor.py output
    always emits ``ok: true`` or an error block; we report the error
    count in the report so it is not silent).
    """
    records: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            records.append(rec)
    return records


def _load_manifest(path: Path) -> list[dict]:
    """Load the v0 val manifest; ``entries`` is the list of gold records."""
    with open(path, "r", encoding="utf-8") as f:
        m = json.load(f)
    if not isinstance(m, dict) or "entries" not in m:
        raise SystemExit(
            f"expected manifest with an 'entries' key at {path}, "
            f"got {type(m).__name__}"
        )
    return m["entries"]


# ---------------------------------------------------------------------------
# Per-category scoring (multiset semantics)
# ---------------------------------------------------------------------------


def _score_one(
    predicted: list[str],
    gold: list[str],
) -> dict[str, dict[str, int]]:
    """Score one encounter; return per-category counts.

    Returns a dict ``{category: {tp, fp, fn}}`` covering every category
    that appears in either predicted or gold for this encounter.
    """
    # Multiset counts (Counter preserves multiplicity).
    pc = Counter(predicted)
    gc = Counter(gold)
    cats = set(pc) | set(gc)
    out: dict[str, dict[str, int]] = {}
    for c in cats:
        tp = min(pc[c], gc[c])  # matched pairs
        fp = pc[c] - tp          # surplus predicted
        fn = gc[c] - tp          # missing predicted
        out[c] = {"tp": tp, "fp": fp, "fn": fn}
    return out


def _accumulate(
    per_encounter_counts: list[dict[str, dict[str, int]]],
) -> dict[str, dict[str, int]]:
    """Sum per-category counts across all encounters.

    Returns ``{category: {tp, fp, fn}}`` covering every category that
    appears anywhere in the split.
    """
    totals: dict[str, dict[str, int]] = {}
    for enc_counts in per_encounter_counts:
        for cat, c in enc_counts.items():
            row = totals.setdefault(cat, {"tp": 0, "fp": 0, "fn": 0})
            row["tp"] += c["tp"]
            row["fp"] += c["fp"]
            row["fn"] += c["fn"]
    return totals


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


def _safe_div(num: float, den: float) -> float:
    """Return 0.0 on 0/0 for P/R aggregates. See aggregate_metrics.py note."""
    if den == 0:
        return 0.0
    return num / den


def _f1(p: float, r: float) -> float:
    if p + r == 0.0:
        return 0.0
    return 2.0 * p * r / (p + r)


def _per_category_metrics(
    totals: dict[str, dict[str, int]],
) -> dict[str, dict[str, Any]]:
    """Build per-category metrics block.

    Each row has precision, recall, f1, support (total gold in cat),
    predicted (total predicted in cat), and tp/fp/fn counts.
    Categories are sorted by descending support, then alphabetical.
    """
    rows: dict[str, dict[str, Any]] = {}
    for cat, c in totals.items():
        support = c["tp"] + c["fn"]  # = total gold in cat
        predicted = c["tp"] + c["fp"]  # = total predicted in cat
        p = _safe_div(c["tp"], c["tp"] + c["fp"])
        r = _safe_div(c["tp"], c["tp"] + c["fn"])
        f1 = _f1(p, r)
        rows[cat] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "support": support,
            "predicted": predicted,
            "tp": c["tp"],
            "fp": c["fp"],
            "fn": c["fn"],
        }
    return rows


def _micro(totals: dict[str, dict[str, int]]) -> dict[str, Any]:
    """Pooled (micro) P/R/F1 across all categories."""
    tp = sum(c["tp"] for c in totals.values())
    fp = sum(c["fp"] for c in totals.values())
    fn = sum(c["fn"] for c in totals.values())
    p = _safe_div(tp, tp + fp)
    r = _safe_div(tp, tp + fn)
    return {
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(_f1(p, r), 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "support": tp + fn,  # total gold findings across all categories
        "predicted": tp + fp,  # total predicted across all categories
    }


def _macro(per_category: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Macro-F1: unweighted mean of per-category P/R/F1.

    Macro convention matches ``scripts/aggregate_metrics.py``: every
    category that appears in the split contributes equally, regardless
    of support. The score is reported as ``None`` only if the split
    has no categories at all (defensive; not expected for v0).
    """
    if not per_category:
        return {"precision": None, "recall": None, "f1": None, "n": 0}
    ps = [row["precision"] for row in per_category.values()]
    rs = [row["recall"] for row in per_category.values()]
    fs = [row["f1"] for row in per_category.values()]
    return {
        "precision": round(statistics.fmean(ps), 4),
        "recall": round(statistics.fmean(rs), 4),
        "f1": round(statistics.fmean(fs), 4),
        "n": len(per_category),
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _build_report(
    predictions: list[dict],
    manifest: list[dict],
    predictions_path: Path,
    manifest_path: Path,
    elapsed_s: float,
) -> dict:
    pred_by_id = {r["encounter_id"]: r for r in predictions}
    gold_by_id = {e["encounter_id"]: e for e in manifest}

    # Sanity: every gold encounter must have a prediction row. If a
    # prediction is missing the gold categories are scored as 0 TP and
    # full FN (an encounter with no prediction = 100% miss).
    missing = [eid for eid in gold_by_id if eid not in pred_by_id]
    extra = [eid for eid in pred_by_id if eid not in gold_by_id]

    n_errors = sum(1 for r in predictions if not r.get("ok", False))

    per_encounter_counts: list[dict[str, dict[str, int]]] = []
    per_encounter_summary: list[dict[str, Any]] = []
    for eid, gold_rec in gold_by_id.items():
        gold_cats = gold_rec.get("gold_categories", [])
        pred_rec = pred_by_id.get(eid)
        if pred_rec is None:
            pred_cats: list[str] = []
        else:
            pred_cats = list(pred_rec.get("predicted_categories", []) or [])
        counts = _score_one(pred_cats, gold_cats)
        per_encounter_counts.append(counts)
        # Per-encounter pooled counts for the per-encounter dump.
        tp = sum(c["tp"] for c in counts.values())
        fp = sum(c["fp"] for c in counts.values())
        fn = sum(c["fn"] for c in counts.values())
        p = _safe_div(tp, tp + fp)
        r = _safe_div(tp, tp + fn)
        per_encounter_summary.append(
            {
                "encounter_id": eid,
                "ok": bool(pred_rec and pred_rec.get("ok", False)),
                "n_predicted": len(pred_cats),
                "n_gold": len(gold_cats),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": round(p, 4),
                "recall": round(r, 4),
            }
        )

    totals = _accumulate(per_encounter_counts)
    per_category = _per_category_metrics(totals)
    micro = _micro(totals)
    macro = _macro(per_category)

    return {
        "encounter_count": len(gold_by_id),
        "prediction_count": len(predictions),
        "encounter_missing_from_predictions": missing,
        "prediction_extra_no_gold": extra,
        "prediction_error_count": n_errors,
        "input": {
            "predictions_path": str(
                predictions_path.relative_to(PROJECT_ROOT)
            ),
            "manifest_path": str(manifest_path.relative_to(PROJECT_ROOT)),
        },
        "scoring": {
            "key": "category (multiset)",
            "rationale": (
                "Per-category P/R/F1 is the metric the task body asks for. "
                "Multiset semantics (Counter) match the per-finding grader's "
                "convention: a duplicate prediction is a FP, a missing gold "
                "is a FN. Categories that appear in either predicted or gold "
                "are included in the per-category block."
            ),
        },
        "targets": {"recall": R_TARGET, "precision": P_TARGET},
        "per_category": per_category,
        "micro": micro,
        "macro": macro,
        "per_encounter": per_encounter_summary,
        "wall_clock_seconds": round(elapsed_s, 4),
        "timestamp_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _fmt(v: Any) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _check(v: float | None, target: float) -> str:
    if v is None:
        return "N/A"
    return "met" if v >= target else "not met"


def _render_markdown(report: dict) -> str:
    micro = report["micro"]
    macro = report["macro"]
    per_cat = report["per_category"]
    targets = report["targets"]
    inp = report["input"]

    lines: list[str] = []
    lines.append("# v0 prediction metrics")
    lines.append("")
    lines.append(
        f"Source: predictions `{inp['predictions_path']}` scored against "
        f"manifest `{inp['manifest_path']}`."
    )
    lines.append("")
    lines.append(
        f"Encounters: **{report['encounter_count']}** "
        f"(predictions: {report['prediction_count']}, "
        f"errors: {report['prediction_error_count']}, "
        f"missing from predictions: {len(report['encounter_missing_from_predictions'])}, "
        f"extra with no gold: {len(report['prediction_extra_no_gold'])})."
    )
    lines.append("")
    lines.append("Scoring key: category (multiset). Per-category block below covers every category that appears in either predicted or gold.")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append("| scope | precision | recall | f1 | support |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append(
        f"| micro (pooled) | {micro['precision']:.4f} | "
        f"{micro['recall']:.4f} | {micro['f1']:.4f} | {micro['support']} |"
    )
    lines.append(
        f"| macro (mean across categories) | "
        f"{_fmt(macro['precision'])} | {_fmt(macro['recall'])} | "
        f"{_fmt(macro['f1'])} | {macro['n']} |"
    )
    lines.append("")
    lines.append("## Targets")
    lines.append("")
    lines.append(
        f"- R >= {targets['recall']:.2f}: "
        f"**{_check(micro['recall'], targets['recall'])}** "
        f"(micro R = {micro['recall']:.4f})"
    )
    lines.append(
        f"- P >= {targets['precision']:.2f}: "
        f"**{_check(micro['precision'], targets['precision'])}** "
        f"(micro P = {micro['precision']:.4f})"
    )
    lines.append("")
    lines.append("## Per-category")
    lines.append("")
    lines.append("| category | precision | recall | f1 | support | predicted |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    # Sort: support desc, then name asc.
    for cat in sorted(
        per_cat.keys(),
        key=lambda c: (-per_cat[c]["support"], c),
    ):
        row = per_cat[cat]
        lines.append(
            f"| {cat} | {row['precision']:.4f} | {row['recall']:.4f} | "
            f"{row['f1']:.4f} | {row['support']} | {row['predicted']} |"
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        f"- Micro P/R/F1 are pooled across all categories (sum of TP, "
        f"sum of FP, sum of FN). Support is total gold categories across "
        f"the split ({micro['support']})."
    )
    lines.append(
        f"- Macro is the unweighted mean of per-category P/R/F1 across "
        f"the {macro['n']} categories that appear in the split."
    )
    lines.append(
        f"- Predictions with `ok=false` ({report['prediction_error_count']}) "
        f"are included in the count but contribute empty `predicted_categories` "
        f"lists, so they count as 100% miss on their gold categories."
    )
    lines.append("")
    lines.append(
        f"Generated at {report['timestamp_utc']} (wall clock "
        f"{report['wall_clock_seconds']}s)."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    predictions_path = Path(
        os.environ.get("PREDICTIONS_PATH", str(PREDICTIONS_PATH))
    )
    manifest_path = Path(
        os.environ.get("MANIFEST_PATH", str(MANIFEST_PATH))
    )
    json_path = Path(
        os.environ.get("METRICS_JSON_PATH", str(DEFAULT_JSON_PATH))
    )
    md_path = Path(
        os.environ.get("METRICS_MD_PATH", str(DEFAULT_MD_PATH))
    )

    if not predictions_path.is_file():
        raise SystemExit(f"predictions file not found at {predictions_path}")
    if not manifest_path.is_file():
        raise SystemExit(f"manifest file not found at {manifest_path}")

    started = time.monotonic()
    predictions = _load_predictions(predictions_path)
    manifest = _load_manifest(manifest_path)
    report = _build_report(
        predictions, manifest, predictions_path, manifest_path,
        time.monotonic() - started,
    )
    elapsed = time.monotonic() - started

    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=False)
    md_path.write_text(_render_markdown(report), encoding="utf-8")

    micro = report["micro"]
    macro = report["macro"]
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(
        f"encounters={report['encounter_count']} "
        f"errors={report['prediction_error_count']} | "
        f"micro P={micro['precision']:.4f} R={micro['recall']:.4f} "
        f"F1={micro['f1']:.4f} support={micro['support']} | "
        f"macro P={_fmt(macro['precision'])} R={_fmt(macro['recall'])} "
        f"F1={_fmt(macro['f1'])} n={macro['n']} | "
        f"wall={elapsed:.3f}s"
    )
    print(
        f"targets: R>={R_TARGET} -> {_check(micro['recall'], R_TARGET)}; "
        f"P>={P_TARGET} -> {_check(micro['precision'], P_TARGET)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
