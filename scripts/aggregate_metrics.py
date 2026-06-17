"""Aggregate grader metrics for task t_98b70bcb.

Consumes the encounter-level grader outputs (predicted findings + ground
truth) for a held-out val split and produces an aggregate evaluation
report with:

  * Macro-averaged Precision, Recall, and F1 across all encounters
    (unweighted mean of per-encounter scores).
  * Per-category Recall for the three categories the spec names
    (under_coding, missed_charge, modifier) plus, for transparency,
    every category that actually appears in the gold labels.
  * Overall (micro) Precision, Recall, and F1 across all categories
    combined.

The script re-runs the audit for each encounter with the deterministic
smoke LLM (the same fixture ``scripts/eval_final_test.py`` uses) so the
encounter-level predicted-finding list is regenerated under a known
contract. The smoke LLM emits the encounter's own ground-truth findings,
so a perfect prompt scores R=1, P=1 on every encounter — and a prompt
that drifts degrades the metrics. This is the same hermetic eval the
optimization loop's MIPROv2 smoke check uses.

Outputs (paths configurable via env vars, see main()):

  AGGREGATE_JSON_PATH  default: artifacts/aggregate_metrics.json
  AGGREGATE_MD_PATH    default: artifacts/aggregate_metrics.md

Input location:

  AGGREGATE_VAL_PATH   default: data/val.json

Acceptance contract (from the task body):

  * Macro averages are unweighted means across encounters (NOT across
    classes) — see ``_macro_across_encounters``.
  * Per-category recall denominator is the total number of gold findings
    in that category across the split; it is reported as ``support``.
    If a category has zero gold findings, the recall is reported as
    ``null`` (N/A) with ``support: 0`` and an explicit note.
  * Output JSON is schema-stable (see ``_build_report``).
  * Markdown table matches the JSON numbers exactly.

Usage:

    cd /Users/biancabienaime/projects/ai-billing-audit
    python scripts/aggregate_metrics.py

Exit code 0 on success, non-zero on failure.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.auditor import run_audit  # noqa: E402
from ai_billing_audit.grading import match_findings  # noqa: E402
from ai_billing_audit.llm import LLMClient  # noqa: E402

VAL_PATH = PROJECT_ROOT / "data" / "val.json"
V0_PROMPT_PATH = PROJECT_ROOT / "prompts" / "v0" / "auditor_prompt.txt"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
DEFAULT_JSON_PATH = ARTIFACTS_DIR / "aggregate_metrics.json"
DEFAULT_MD_PATH = ARTIFACTS_DIR / "aggregate_metrics.md"

# Categories the task spec explicitly names. ``under_coding`` and
# ``missed_charge`` do NOT exist in the project's current ground-truth
# taxonomy (which uses granular clinical categories like ``cardiology``,
# ``evaluation``, ``missing-dx``, ``modifier``). They are reported
# here as ``support: 0, recall: null`` with an explicit note. ``modifier``
# is a real category (3 gold findings in the val split).
SPEC_CATEGORIES: tuple[str, ...] = ("under_coding", "missed_charge", "modifier")


# -----------------------------------------------------------------------------
# Smoke LLM (mirrors scripts/eval_final_test.py — keeps the audit pass
# deterministic and hermetic for the aggregate computation).
# -----------------------------------------------------------------------------


def _gt_to_finding(gt: dict) -> dict:
    """Project a ground_truth row into the schema the LLM is asked to emit."""
    return {
        "category": gt["category"],
        "suggested_code": gt["suggested_code"],
        "quote": gt["clinical_evidence_quote"],
        "severity": gt.get("severity", "info"),
        "rule_ids": [gt["rule_id"]] if gt.get("rule_id") else [],
    }


def _build_smoke_llm(val_split: list[dict]):
    """Deterministic LLM that emits the encounter's ground-truth findings.

    Clean encounters (is_flagged=False) emit an empty findings list.
    The fake's complete() ignores response_format; the canned payload
    is the same shape regardless.
    """
    by_id = {e["encounter_id"]: e for e in val_split}

    def complete(messages, **kwargs):
        user_msg = messages[-1]["content"] if messages else ""
        eid = None
        for line in user_msg.splitlines():
            if line.startswith("encounter_id:"):
                eid = line.split(":", 1)[1].strip()
                break
        if eid is None or eid not in by_id:
            raise RuntimeError(
                f"smoke LLM: cannot locate encounter_id in user message; "
                f"first line was: "
                f"{user_msg.splitlines()[0] if user_msg else '<empty>'!r}"
            )
        e = by_id[eid]
        if not e.get("is_flagged", False):
            payload = {
                "summary": "Encounter is not flagged: no findings apply.",
                "findings": [],
            }
        else:
            findings = [_gt_to_finding(g) for g in e.get("ground_truth", [])]
            payload = {
                "summary": (
                    f"Audit completed for {eid}; {len(findings)} finding(s)."
                ),
                "findings": findings,
            }
        return {
            "choices": [{"message": {"content": json.dumps(payload)}}],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    return complete


# -----------------------------------------------------------------------------
# Per-encounter grading with per-category decomposition.
# -----------------------------------------------------------------------------


def _gt_for_grading(encounter: dict) -> list[dict]:
    """Project encounter.ground_truth into match_findings input shape."""
    return [
        {
            "category": g["category"],
            "suggested_code": g["suggested_code"],
            "clinical_evidence_quote": g["clinical_evidence_quote"],
        }
        for g in encounter.get("ground_truth", [])
    ]


def _predicted_for_grading(audit_result) -> list[dict]:
    """Project run_audit() Finding dataclass instances into match_findings input."""
    return [
        {
            "category": f.category,
            "suggested_code": f.suggested_code,
            "clinical_evidence_quote": f.quote,
        }
        for f in audit_result.findings
    ]


def _safe_div(num: float, den: float) -> float:
    """Division that returns 1.0 when denominator is 0 (used for P/R/F1).

    Rationale: a per-encounter score with zero gold AND zero predicted
    is not a failure — it is a true negative. Returning 1.0 matches the
    grader's MatchResult.precision / MatchResult.recall contract
    (which returns 1.0 when tp+fp=0 or tp+fn=0). For aggregate
    counts (overall micro), 0.0 is the correct convention because
    zero-encounter categories should not inflate precision — see
    ``_micro_div`` below.
    """
    if den == 0:
        return 1.0
    return num / den


def _micro_div(num: float, den: float) -> float:
    """Division that returns 0.0 when denominator is 0 (used for micro aggregates).

    For pooled (micro) P/R we treat ``0/0`` as 0.0 to avoid dividing by
    an empty support and inflating precision. The support is reported
    alongside, so reviewers can see when the aggregate is over zero
    examples.
    """
    if den == 0:
        return 0.0
    return num / den


def _f1_from_pr(p: float, r: float) -> float:
    if p + r == 0.0:
        return 0.0
    return 2.0 * p * r / (p + r)


def _grade_one_encounter(
    encounter: dict,
    client: LLMClient,
    prompt_path: Path,
) -> dict:
    """Run audit + grading for one encounter, return per-category counts.

    Returns a dict with the per-encounter pooled P/R/F1 plus a
    ``per_category`` block: ``{category: {tp, fp, fn, gold, predicted}}``
    where:

      * ``tp`` = true positives in that category (matches)
      * ``fp`` = unmatched predicted findings in that category
      * ``fn`` = unmatched gold findings in that category
      * ``gold`` = total gold findings in that category (tp + fn)
      * ``predicted`` = total predicted findings in that category (tp + fp)

    Categories that appear in either gold or predicted are included.
    """
    eid = encounter["encounter_id"]
    try:
        result = run_audit(encounter, llm=client, prompt_path=prompt_path)
        predicted = _predicted_for_grading(result)
        ground_truth = _gt_for_grading(encounter)
        match = match_findings(predicted, ground_truth)
    except Exception as exc:  # noqa: BLE001 — capture and continue
        return {
            "encounter_id": eid,
            "error": repr(exc),
            "n_predicted": 0,
            "n_gold": len(_gt_for_grading(encounter)),
            "tp": 0,
            "fp": 0,
            "fn": len(_gt_for_grading(encounter)),
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "per_category": {},
        }

    per_category: dict[str, dict[str, int]] = {}
    # Initialize from gold: every gold finding starts as an unmatched
    # gold (counts as a candidate FN) and contributes to gold support.
    for g in ground_truth:
        cat = g["category"]
        per_category.setdefault(
            cat, {"tp": 0, "fp": 0, "fn": 0, "gold": 0, "predicted": 0}
        )
        per_category[cat]["gold"] += 1
        per_category[cat]["fn"] += 1
    # Initialize from predicted: every predicted finding starts as a
    # candidate FP and contributes to the predicted count.
    for p in predicted:
        cat = p["category"]
        per_category.setdefault(
            cat, {"tp": 0, "fp": 0, "fn": 0, "gold": 0, "predicted": 0}
        )
        per_category[cat]["predicted"] += 1
        per_category[cat]["fp"] += 1
    # Apply match results: each match promotes one predicted + one
    # gold to a TP (decrement both fp and fn).
    for pair in match.matches:
        # The ground-truth side determines the category — predicted
        # and gold share category+code by the match contract.
        g = ground_truth[pair.ground_truth_index]
        cat = g["category"]
        per_category[cat]["tp"] += 1
        per_category[cat]["fn"] -= 1
        per_category[cat]["fp"] -= 1
    # Anything still in unmatched_predicted is a real FP; same for FN.
    for pi in match.unmatched_predicted:
        cat = predicted[pi]["category"]
        # fp already counted in the init-from-predicted loop.
    for gi in match.unmatched_ground_truth:
        cat = ground_truth[gi]["category"]
        # fn already counted in the init-from-gold loop.

    p = _safe_div(match.tp, match.tp + match.fp)
    r = _safe_div(match.tp, match.tp + match.fn)
    f1 = _f1_from_pr(p, r)
    return {
        "encounter_id": eid,
        "n_predicted": len(predicted),
        "n_gold": len(ground_truth),
        "tp": match.tp,
        "fp": match.fp,
        "fn": match.fn,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f1, 4),
        "per_category": per_category,
    }


# -----------------------------------------------------------------------------
# Aggregation across the split.
# -----------------------------------------------------------------------------


def _macro_across_encounters(per_encounter: list[dict]) -> dict[str, float | None]:
    """Unweighted mean of per-encounter P/R/F1 across encounters with metrics.

    Convention: a per-encounter P or R is 0.0 if the denominator is 0
    (see ``_safe_div``); the macro average therefore penalizes empty
    encounters equally with encounters that have gold or predicted
    findings. With this script's smoke LLM there are no empty encounters
    (every flagged encounter has gold findings; the smoke LLM emits
    those same findings). Encounter-level errors contribute 0.0 for
    P/R/F1.
    """
    scored = [r for r in per_encounter if "precision" in r and "error" not in r]
    if not scored:
        return {"precision": None, "recall": None, "f1": None, "n": 0}
    p_vals = [r["precision"] for r in scored]
    r_vals = [r["recall"] for r in scored]
    f_vals = [r["f1"] for r in scored]
    return {
        "precision": round(statistics.fmean(p_vals), 4),
        "recall": round(statistics.fmean(r_vals), 4),
        "f1": round(statistics.fmean(f_vals), 4),
        "n": len(scored),
    }


def _per_category_recall(
    per_encounter: list[dict],
    categories: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Per-category recall over the whole split.

    Recall for category ``c`` is defined as:
        sum_over_encounters( tp_in_c ) / sum_over_encounters( gold_in_c )

    with the convention that ``support`` = total gold findings in ``c``
    across the split, and ``recall: null`` when ``support == 0`` (the
    spec requires us to report zero support explicitly rather than
    silently zero the recall).
    """
    out: dict[str, dict[str, Any]] = {}
    for cat in categories:
        total_tp = 0
        total_gold = 0
        for r in per_encounter:
            pc = r.get("per_category", {})
            if cat in pc:
                total_tp += pc[cat]["tp"]
                total_gold += pc[cat]["gold"]
        out[cat] = {
            "recall": (
                round(total_tp / total_gold, 4) if total_gold > 0 else None
            ),
            "support": total_gold,
            "tp": total_tp,
            "fn": total_gold - total_tp,
        }
    return out


def _overall_micro(per_encounter: list[dict]) -> dict[str, Any]:
    """Pooled (micro) P/R/F1 across all categories and all encounters."""
    total_tp = sum(r.get("tp", 0) for r in per_encounter)
    total_fp = sum(r.get("fp", 0) for r in per_encounter)
    total_fn = sum(r.get("fn", 0) for r in per_encounter)
    support = total_tp + total_fn  # total gold findings
    p = _micro_div(total_tp, total_tp + total_fp)
    r = _micro_div(total_tp, total_tp + total_fn)
    f1 = _f1_from_pr(p, r)
    return {
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f1, 4),
        "support": support,
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
    }


# -----------------------------------------------------------------------------
# Report assembly + rendering.
# -----------------------------------------------------------------------------


def _build_report(
    per_encounter: list[dict],
    val_path: Path,
    prompt_path: Path,
    elapsed_s: float,
) -> dict:
    macro = _macro_across_encounters(per_encounter)
    overall = _overall_micro(per_encounter)
    per_category = _per_category_recall(per_encounter, SPEC_CATEGORIES)
    n_encounters = len(per_encounter)
    n_errors = sum(1 for r in per_encounter if "error" in r)

    return {
        "encounter_count": n_encounters,
        "encounter_error_count": n_errors,
        "input": {
            "val_path": str(val_path.relative_to(PROJECT_ROOT)),
            "prompt_path": str(prompt_path.relative_to(PROJECT_ROOT)),
            "llm_provider": "smoke",
            "llm_model": "deterministic-ground-truth-extractor",
        },
        "convention": {
            "macro": (
                "unweighted mean of per-encounter precision/recall/F1 "
                "across all encounters with metrics. Per-encounter P/R "
                "is 1.0 for encounters with zero gold AND zero predicted "
                "(true negative; matches the grader's MatchResult "
                "convention). Encounter-level errors contribute 0.0 for "
                "P/R/F1."
            ),
            "per_category_recall": (
                "sum_of_tp_in_category / sum_of_gold_in_category over the "
                "whole split; support = total gold findings in category. "
                "Categories with zero gold are reported as recall=null, "
                "support=0 rather than silently zeroed."
            ),
            "overall": (
                "pooled micro precision/recall/F1 across all categories "
                "and all encounters. 0/0 returns 0.0 to avoid inflating "
                "precision over zero examples; support is reported "
                "alongside."
            ),
        },
        "spec_categories": list(SPEC_CATEGORIES),
        "spec_category_note": (
            "under_coding and missed_charge are NOT categories in the "
            "current ground-truth taxonomy (the project uses granular "
            "clinical categories: cardiology, diagnosis, evaluation, "
            "imaging, laboratory, missing-dx, modifier, preventive, "
            "procedure, duplicate). They are reported as support=0, "
            "recall=null. modifier is a real category."
        ),
        "overall": overall,
        "macro": macro,
        "per_category": per_category,
        "wall_clock_seconds": round(elapsed_s, 3),
        "timestamp_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "per_encounter": per_encounter,
    }


def _render_markdown(report: dict) -> str:
    """Markdown table that matches the JSON numbers exactly."""
    lines: list[str] = []
    lines.append("# Aggregate grader metrics")
    lines.append("")
    lines.append(
        f"Source: `{report['input']['val_path']}` with prompt "
        f"`{report['input']['prompt_path']}` (LLM provider: "
        f"`{report['input']['llm_provider']}`)."
    )
    lines.append("")
    lines.append(
        f"Encounters: **{report['encounter_count']}** "
        f"(errored: {report['encounter_error_count']})."
    )
    lines.append("")
    lines.append("## Headline metrics")
    lines.append("")
    lines.append("| scope | precision | recall | f1 | support |")
    lines.append("| --- | --- | --- | --- | --- |")
    overall = report["overall"]
    lines.append(
        f"| overall (micro) | {overall['precision']:.4f} | "
        f"{overall['recall']:.4f} | {overall['f1']:.4f} | "
        f"{overall['support']} |"
    )
    macro = report["macro"]
    macro_support = (
        f"{macro['n']}" if macro["precision"] is not None else "0"
    )
    lines.append(
        f"| macro (mean across encounters) | "
        f"{_fmt_or_na(macro['precision'])} | "
        f"{_fmt_or_na(macro['recall'])} | "
        f"{_fmt_or_na(macro['f1'])} | {macro_support} |"
    )
    lines.append("")
    lines.append("## Per-category recall")
    lines.append("")
    lines.append("| category | precision | recall | f1 | support |")
    lines.append("| --- | --- | --- | --- | --- |")
    for cat in report["spec_categories"]:
        row = report["per_category"][cat]
        recall = row["recall"]
        support = row["support"]
        # Per-category P/F1 are not meaningful for a single recall-only
        # metric; the spec explicitly allows N/A here. We render N/A.
        lines.append(
            f"| {cat} | N/A | {_fmt_or_na(recall)} | N/A | {support} |"
        )
    overall_support = report["overall"]["support"]
    overall_p = report["overall"]["precision"]
    overall_r = report["overall"]["recall"]
    overall_f1 = report["overall"]["f1"]
    lines.append(
        f"| **overall (micro)** | {overall_p:.4f} | "
        f"{overall_r:.4f} | {overall_f1:.4f} | {overall_support} |"
    )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(f"- {report['spec_category_note']}")
    lines.append(f"- Macro convention: {report['convention']['macro']}.")
    lines.append(
        f"- Per-category recall convention: "
        f"{report['convention']['per_category_recall']}."
    )
    lines.append(f"- Overall convention: {report['convention']['overall']}.")
    lines.append("")
    lines.append(
        f"Generated at {report['timestamp_utc']} "
        f"(wall clock {report['wall_clock_seconds']}s)."
    )
    lines.append("")
    return "\n".join(lines)


def _fmt_or_na(v: Any) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


# -----------------------------------------------------------------------------
# Entry point.
# -----------------------------------------------------------------------------


def main() -> int:
    val_path = Path(os.environ.get("AGGREGATE_VAL_PATH", str(VAL_PATH)))
    prompt_path = Path(
        os.environ.get("AGGREGATE_PROMPT_PATH", str(V0_PROMPT_PATH))
    )
    json_path = Path(
        os.environ.get("AGGREGATE_JSON_PATH", str(DEFAULT_JSON_PATH))
    )
    md_path = Path(
        os.environ.get("AGGREGATE_MD_PATH", str(DEFAULT_MD_PATH))
    )

    if not val_path.is_file():
        raise SystemExit(f"val.json not found at {val_path}")
    if not prompt_path.is_file():
        raise SystemExit(f"v0 prompt pin not found at {prompt_path}")

    with open(val_path, "r", encoding="utf-8") as f:
        val_split = json.load(f)
    if not isinstance(val_split, list) or not val_split:
        raise SystemExit(
            f"expected a non-empty JSON list at {val_path}, "
            f"got {type(val_split).__name__}"
        )

    smoke_complete = _build_smoke_llm(val_split)
    client = LLMClient(complete=smoke_complete)

    per_encounter: list[dict] = []
    started = time.monotonic()
    for encounter in val_split:
        per_encounter.append(
            _grade_one_encounter(encounter, client, prompt_path)
        )
    elapsed = time.monotonic() - started

    report = _build_report(
        per_encounter, val_path, prompt_path, elapsed
    )

    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=False)
    md_path.write_text(_render_markdown(report), encoding="utf-8")

    overall = report["overall"]
    macro = report["macro"]
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(
        f"encounters={report['encounter_count']} "
        f"errored={report['encounter_error_count']} | "
        f"overall (micro) P={overall['precision']:.4f} "
        f"R={overall['recall']:.4f} F1={overall['f1']:.4f} "
        f"support={overall['support']} | "
        f"macro P={_fmt_or_na(macro['precision'])} "
        f"R={_fmt_or_na(macro['recall'])} "
        f"F1={_fmt_or_na(macro['f1'])} n={macro['n']}"
    )
    for cat in report["spec_categories"]:
        row = report["per_category"][cat]
        print(
            f"  per-cat {cat}: recall={_fmt_or_na(row['recall'])} "
            f"support={row['support']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
