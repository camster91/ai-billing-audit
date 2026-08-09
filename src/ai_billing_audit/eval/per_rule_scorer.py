"""Per-rule-family recall breakdown scorer.

Promoted from /tmp/score_ollama_audit.py into the repo at
src/ai_billing_audit/eval/per_rule_scorer.py and wired to a CLI.

Reports P/R/F1 globally AND broken down by:
  - rule_family (modifier, code_level, dx_procedure, ncci_mue_time, doc_adequacy)
  - modifier sub-rule (modifier-25, -59, -24, ...)
  - code level (E/M, procedural, imaging, lab)
  - finding severity bucket (info/low/medium/high/critical)

Usage:
    python3 -m ai_billing_audit.eval.per_rule_scorer \
        --val data/val.json \
        --preds runs/acceptance/<run>/predictions.jsonl \
        --out runs/acceptance/<run>/per_rule_scores.json

Exit code 0 on success, non-zero on schema/file errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

# Rule-id prefix → rule_family bucket. Unknown prefixes fall into "other".
RULE_FAMILY_PREFIXES: Dict[str, str] = {
    "MOD-": "modifier",
    "E/M-": "code_level",
    "EM-": "code_level",
    "CPT-": "code_level",
    "DX-": "dx_procedure",
    "DXC-": "dx_procedure",
    "NCCI-": "ncci_mue_time",
    "MUE-": "ncci_mue_time",
    "TIME-": "ncci_mue_time",
    "DOC-": "doc_adequacy",
    "DOCS-": "doc_adequacy",
}

# Modifier sub-rules we care about for the breakdown.
MODIFIER_SUBRULES: Set[str] = {
    "MOD-25",
    "MOD-59",
    "MOD-24",
    "MOD-57",
    "MOD-50",
    "MOD-26",
    "MOD-TC",
}

CODE_LEVELS: Set[str] = {"E/M", "procedural", "imaging", "lab", "other"}

SEVERITY_ORDER: Tuple[str, ...] = ("info", "low", "medium", "high", "critical")


def _finding_key(f: Dict[str, Any]) -> str:
    """Score on rule_id only — same as the baseline scorer. See docs/QA_RESEARCH_SUMMARY.md."""
    return (f.get("rule_id") or "").strip()


def _rule_family(rule_id: str) -> str:
    rid = (rule_id or "").upper()
    for prefix, family in RULE_FAMILY_PREFIXES.items():
        if rid.startswith(prefix.upper()):
            # For modifier sub-rules, return the sub-rule id so they get their own bucket.
            if family == "modifier" and rid in {m.upper() for m in MODIFIER_SUBRULES}:
                return f"modifier:{rid}"
            return family
    return "other"


def _code_level(rule_id: str) -> str:
    rid = (rule_id or "").upper()
    if rid.startswith("E/M-") or rid.startswith("EM-"):
        return "E/M"
    if "IMAGING" in rid or rid.startswith("RAD-") or rid.startswith("IMG-"):
        return "imaging"
    if "LAB" in rid or rid.startswith("PATH-"):
        return "lab"
    if rid.startswith("CPT-"):
        return "procedural"
    return "other"


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _load_ground_truth(val_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Accept both shapes used in the repo:
      - top-level list:  [{"encounter_id": ..., "ground_truth": [...]}]
      - top-level object: {"encounters": [...]}  OR  {"entries": [...]}

    Ground-truth findings are pulled from whichever of these keys exist,
    in priority order: ground_truth, ground_truth_labels, findings.
    """
    raw = json.loads(val_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        items = raw
    else:
        items = raw.get("encounters") or raw.get("entries") or []
    out: Dict[str, List[Dict[str, Any]]] = {}
    for enc in items:
        eid = enc.get("encounter_id")
        if not eid:
            continue
        for key in ("ground_truth", "ground_truth_labels", "findings"):
            if key in enc and isinstance(enc[key], list):
                out[eid] = enc[key]
                break
        else:
            out[eid] = []
    return out


def _bucket_metrics(
    gt_set: Set[str],
    pred_set: Set[str],
) -> Tuple[int, int, int]:
    tp = len(gt_set & pred_set)
    fp = len(pred_set - gt_set)
    fn = len(gt_set - pred_set)
    return tp, fp, fn


def _safe_pr(tp: int, fp: int, fn: int) -> Dict[str, float]:
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
    return {"precision": prec, "recall": rec, "f1": f1}


def _aggregate(
    rows: Iterable[Tuple[int, int, int]],
) -> Dict[str, Any]:
    tp = fp = fn = 0
    n = 0
    for r_tp, r_fp, r_fn in rows:
        tp += r_tp
        fp += r_fp
        fn += r_fn
        n += 1
    out: Dict[str, Any] = {"tp": tp, "fp": fp, "fn": fn, "n": n}
    out.update(_safe_pr(tp, fp, fn))
    return out


def score(
    val_path: Path,
    preds_path: Path,
) -> Dict[str, Any]:
    gt_by_id = _load_ground_truth(val_path)
    preds = _load_jsonl(preds_path)

    # Buckets: rule_family → list of (tp, fp, fn) per encounter.
    by_family: Dict[str, List[Tuple[int, int, int]]] = defaultdict(list)
    by_modifier: Dict[str, List[Tuple[int, int, int]]] = defaultdict(list)
    by_code_level: Dict[str, List[Tuple[int, int, int]]] = defaultdict(list)

    global_rows: List[Tuple[int, int, int]] = []
    per_encounter: List[Dict[str, Any]] = []

    for pred in preds:
        eid = pred.get("encounter_id", "")
        gt_list = gt_by_id.get(eid, [])
        gt_keys = {_finding_key(f) for f in gt_list if _finding_key(f)}
        pred_findings = pred.get("findings", []) or []
        pred_keys = {_finding_key(f) for f in pred_findings if _finding_key(f)}

        tp, fp, fn = _bucket_metrics(gt_keys, pred_keys)
        global_rows.append((tp, fp, fn))
        per_encounter.append(
            {
                "encounter_id": eid,
                "gt_count": len(gt_keys),
                "pred_count": len(pred_keys),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "is_flagged": bool(pred.get("is_flagged", False)),
                "ok": bool(pred.get("ok", True)),
            }
        )

        # Family buckets — re-bucket the keys by their rule_family.
        for k in gt_keys | pred_keys:
            fam = _rule_family(k)
            row = _bucket_metrics(
                {k} & gt_keys,
                {k} & pred_keys,
            )
            by_family[fam].append(row)
            if fam.startswith("modifier:"):
                by_modifier[fam.split(":", 1)[1]].append(row)
            clvl = _code_level(k)
            if clvl in CODE_LEVELS:
                by_code_level[clvl].append(row)

    overall = _aggregate(global_rows)
    n_enc = len(per_encounter)
    any_match = sum(1 for e in per_encounter if e["tp"] > 0)
    zero_tp = sum(1 for e in per_encounter if e["tp"] == 0)

    return {
        "n_encounters": n_enc,
        "n_ok": sum(1 for e in per_encounter if e["ok"]),
        "n_errors": sum(1 for e in per_encounter if not e["ok"]),
        "any_match_count": any_match,
        "zero_tp_count": zero_tp,
        "overall": overall,
        "by_rule_family": {k: _aggregate(v) for k, v in sorted(by_family.items())},
        "by_modifier_subrule": {
            k: _aggregate(v) for k, v in sorted(by_modifier.items())
        },
        "by_code_level": {k: _aggregate(v) for k, v in sorted(by_code_level.items())},
        "per_encounter": per_encounter,
    }


def _render_text(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("PER-RULE-FAMILY RECALL BREAKDOWN")
    lines.append("=" * 72)
    lines.append(
        f"Encounters: {report['n_encounters']} "
        f"(OK={report['n_ok']}, errors={report['n_errors']})"
    )
    overall = report["overall"]
    lines.append(
        f"Overall: P={overall['precision']:.3f}  R={overall['recall']:.3f}  "
        f"F1={overall['f1']:.3f}  (TP={overall['tp']} FP={overall['fp']} FN={overall['fn']})"
    )
    lines.append("")

    lines.append("By rule family:")
    for fam, m in report["by_rule_family"].items():
        lines.append(
            f"  {fam:18s}  n={m['n']:3d}  P={m['precision']:.3f}  R={m['recall']:.3f}  "
            f"F1={m['f1']:.3f}  (TP={m['tp']} FP={m['fp']} FN={m['fn']})"
        )
    lines.append("")

    lines.append("By modifier sub-rule:")
    if not report["by_modifier_subrule"]:
        lines.append("  (none seen in this run)")
    for fam, m in report["by_modifier_subrule"].items():
        lines.append(
            f"  {fam:12s}  n={m['n']:3d}  P={m['precision']:.3f}  R={m['recall']:.3f}  "
            f"F1={m['f1']:.3f}"
        )
    lines.append("")

    lines.append("By code level:")
    for fam, m in report["by_code_level"].items():
        lines.append(
            f"  {fam:10s}  n={m['n']:3d}  P={m['precision']:.3f}  R={m['recall']:.3f}  "
            f"F1={m['f1']:.3f}"
        )
    return "\n".join(lines) + "\n"


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--val", required=True, type=Path, help="Path to data/val.json")
    p.add_argument(
        "--preds", required=True, type=Path, help="Path to predictions.jsonl"
    )
    p.add_argument("--out", required=True, type=Path, help="Path to write JSON report")
    args = p.parse_args(argv)

    if not args.val.exists():
        print(f"ERROR: val file not found: {args.val}", file=sys.stderr)
        return 2
    if not args.preds.exists():
        print(f"ERROR: preds file not found: {args.preds}", file=sys.stderr)
        return 2

    report = score(args.val, args.preds)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    sys.stdout.write(_render_text(report))
    print(f"Saved per-rule report to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
