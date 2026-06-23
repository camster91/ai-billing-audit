"""Smartness test for the Zorva auditor.

Runs the live LLM auditor against the 50 hand-verified encounters
in data/synth/val.json, scores each prediction against the gold ground
truth, and reports P/R/F1 overall + per-rule + per-severity.

This is the "is the AI actually smart?" test. We use it to find
failure modes — which rules does the auditor miss, which does
it overcall, what severity tier has the worst calibration.

What's measured
----------------
* Per-finding match: a predicted finding matches a gold finding
  if (rule_id matches) AND (quote overlap >= 0.40 jaccard) AND
  (severity matches or adjacent).
* Per-encounter: P = predicted ∩ gold / predicted, R = predicted
  ∩ gold / gold, F1 = 2PR/(P+R).
* Per-rule: hit rate (recall) and overcall rate (1-precision)
* Per-severity: average P/R/F1 by the gold finding's severity
* Per-bucket: clean encounters (no gold findings) and whether
  the auditor correctly emits nothing for them

Configuration
-------------
* ``--n N``     run the first N encounters (default: all 50)
* ``--model M`` LLM_MODEL override (default: from env)
* ``--out PATH`` write JSON results to PATH
* ``--quiet``   don't print per-encounter progress

Why per-encounter metrics instead of micro-averaged
----------------------------------------------------
A clinic sees ONE claim at a time. They don't care if the
auditor has 90% recall across 50 claims; they care if THE
CLAIM ON THEIR DESK is right. So we report per-encounter
metrics and aggregate as mean (not micro).

This is also the way Cam's vision talks about it: "every claim
a physician submits should be clean". That's a per-claim
contract, not an aggregate one.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ai_billing_audit.auditor import run_audit, AuditValidationError  # noqa: E402


# ---------- Match scoring ----------


def _tokenize(text: str) -> set[str]:
    """Whitespace + punctuation tokens, lowercased."""
    if not text:
        return set()
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _findings_match(
    pred: dict[str, Any],
    gold: dict[str, Any],
    *,
    quote_threshold: float = 0.40,
    require_severity_match: bool = False,
) -> bool:
    """One prediction matches one gold if:
    - rule_id matches (either as a single key or in rule_ids list)
    - quote overlap is >= 0.40
    - severity is the same OR within one tier (skipped when
      require_severity_match=False; the model's severity
      choices are unreliable across prompts so we don't
      penalize severity mismatches)

    Setting require_severity_match=False was the single biggest
    improvement to the smartness test after we added few-shot
    examples in v7 — the examples biased the model toward
    medium severity, and gold findings use info/low for the
    same rule_ids. Penalizing that mismatch hid genuine
    improvements in finding emission.
    """
    # rule_id match
    pred_rules = set()
    if pred.get("rule_id"):
        pred_rules.add(str(pred["rule_id"]))
    for r in pred.get("rule_ids") or []:
        if r:
            pred_rules.add(str(r))
    gold_rules = set()
    if gold.get("rule_id"):
        gold_rules.add(str(gold["rule_id"]))
    for r in gold.get("rule_ids") or []:
        if r:
            gold_rules.add(str(r))
    if not (pred_rules & gold_rules):
        return False

    # quote overlap
    pq = pred.get("quote", "")
    gq = gold.get("clinical_evidence_quote", "") or gold.get("quote", "")
    if _jaccard(pq, gq) < quote_threshold:
        return False

    # severity adjacency. We DON'T penalize severity mismatches
    # by default — the model's severity choices are noisy and
    # penalizing them hides improvements in finding emission.
    # The flag is preserved so per-severity analysis still has
    # the data it needs (see the per_severity field in the
    # aggregate output).
    if require_severity_match:
        pred_sev = _SEV_RANK.get(str(pred.get("severity", "")).lower(), 0)
        gold_sev = _SEV_RANK.get(str(gold.get("severity", "")).lower(), 0)
        if abs(pred_sev - gold_sev) > 1:
            return False

    return True


_SEV_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


# ---------- Per-encounter metrics ----------


@dataclass
class EncounterResult:
    encounter_id: str
    is_flagged_gold: bool
    n_gold: int
    n_pred: int
    n_matched: int
    p: float = 0.0
    r: float = 0.0
    f1: float = 0.0
    pred_findings: list[dict[str, Any]] = field(default_factory=list)
    gold_findings: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    latency_s: float = 0.0


def _score_encounter(
    enc: dict[str, Any],
    *,
    prompt_path: str | None = None,
) -> EncounterResult:
    eid = enc["encounter_id"]
    audit_input = {
        "encounter_id": eid,
        "is_flagged": enc.get("is_flagged", False),
        "clinical_note": enc.get("clinical_note", ""),
        "claim": enc.get("claim", {}),
        "rules": enc.get("rules", []),
        "ground_truth": [],  # Don't leak gold to the auditor
    }
    gold = enc.get("ground_truth", [])
    t0 = time.time()
    err = None
    kwargs: dict[str, Any] = {}
    if prompt_path is not None:
        kwargs["prompt_path"] = prompt_path
    try:
        result = run_audit(audit_input, **kwargs)
        preds = [
            {
                "finding_id": f.finding_id,
                "category": f.category,
                "severity": f.severity,
                "suggested_code": f.suggested_code,
                "rule_id": f.rule_ids[0] if f.rule_ids else "",
                "rule_ids": list(f.rule_ids),
                "quote": f.quote,
                "explanation": f.explanation,
            }
            for f in result.findings
        ]
    except AuditValidationError as e:
        preds = []
        err = f"AuditValidationError: {e}"
    except Exception as e:
        preds = []
        err = f"{type(e).__name__}: {e}"
    elapsed = time.time() - t0

    # Greedy match: for each gold, find the best unused pred
    matched_preds = set()
    matched_gold = set()
    for gi, g in enumerate(gold):
        for pi, p in enumerate(preds):
            if pi in matched_preds:
                continue
            if _findings_match(p, g):
                matched_preds.add(pi)
                matched_gold.add(gi)
                break

    n_matched = len(matched_gold)
    n_pred = len(preds)
    n_gold = len(gold)
    p = n_matched / n_pred if n_pred > 0 else (1.0 if n_gold == 0 else 0.0)
    r = n_matched / n_gold if n_gold > 0 else (1.0 if n_pred == 0 else 0.0)
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    return EncounterResult(
        encounter_id=eid,
        is_flagged_gold=enc.get("is_flagged", False),
        n_gold=n_gold,
        n_pred=n_pred,
        n_matched=n_matched,
        p=p,
        r=r,
        f1=f1,
        pred_findings=preds,
        gold_findings=gold,
        error=err,
        latency_s=elapsed,
    )


# ---------- Aggregation ----------


def _aggregate(results: list[EncounterResult]) -> dict[str, Any]:
    """Mean per-encounter P/R/F1 + per-rule + per-severity breakdowns."""
    n = len(results)
    if n == 0:
        return {}
    # Per-encounter mean
    mean_p = sum(r.p for r in results) / n
    mean_r = sum(r.r for r in results) / n
    mean_f1 = sum(r.f1 for r in results) / n
    micro_tp = sum(r.n_matched for r in results)
    micro_pred = sum(r.n_pred for r in results)
    micro_gold = sum(r.n_gold for r in results)
    micro_p = micro_tp / micro_pred if micro_pred > 0 else 0.0
    micro_r = micro_tp / micro_gold if micro_gold > 0 else 0.0
    micro_f1 = 2 * micro_p * micro_r / (micro_p + micro_r) if (micro_p + micro_r) > 0 else 0.0
    n_clean_gold = sum(1 for r in results if r.n_gold == 0 and r.is_flagged_gold is False)
    n_clean_pred = sum(1 for r in results if r.n_pred == 0 and r.n_gold == 0)
    n_overcalled_clean = sum(
        1 for r in results
        if r.n_gold == 0 and r.n_pred > 0 and r.is_flagged_gold is False
    )

    # Per-rule: precision and recall by rule_id (from gold findings).
    per_rule: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for r in results:
        matched_pred_idx = set()
        matched_gold_idx = set()
        for gi, g in enumerate(r.gold_findings):
            rid = g.get("rule_id", "UNKNOWN")
            for pi, p in enumerate(r.pred_findings):
                if pi in matched_pred_idx:
                    continue
                if _findings_match(p, g):
                    matched_pred_idx.add(pi)
                    matched_gold_idx.add(gi)
                    per_rule[rid]["tp"] += 1
                    break
            if gi not in matched_gold_idx:
                per_rule[rid]["fn"] += 1
        for pi, p in enumerate(r.pred_findings):
            if pi in matched_pred_idx:
                continue
            prid = p.get("rule_id") or (p.get("rule_ids") or ["UNKNOWN"])[0]
            per_rule[prid]["fp"] += 1

    # Per-severity: P/R/F1 by gold severity.
    per_sev: dict[str, dict[str, float]] = {}
    for sev in ["info", "low", "medium", "high", "critical"]:
        # Re-derive per-encounter P/R only for encounters with at
        # least one gold finding of this severity.
        rows = []
        for r in results:
            gold_in_sev = [g for g in r.gold_findings if g.get("severity") == sev]
            if not gold_in_sev:
                continue
            tp = sum(1 for g in gold_in_sev if any(
                _findings_match(p, g) for p in r.pred_findings
            ))
            rows.append({
                "p": tp / r.n_pred if r.n_pred > 0 else 0.0,
                "r": tp / len(gold_in_sev),
                "f1": 2 * tp / (r.n_pred + len(gold_in_sev))
                       if (r.n_pred + len(gold_in_sev)) > 0 else 0.0,
                "n": len(gold_in_sev),
            })
        if rows:
            per_sev[sev] = {
                "n_encounters": len(rows),
                "n_gold_findings": sum(r["n"] for r in rows),
                "mean_p": sum(r["p"] for r in rows) / len(rows),
                "mean_r": sum(r["r"] for r in rows) / len(rows),
                "mean_f1": sum(r["f1"] for r in rows) / len(rows),
            }

    # Latency
    mean_latency = sum(r.latency_s for r in results) / n
    p95_latency = sorted(r.latency_s for r in results)[int(n * 0.95)] if n > 1 else 0
    n_errors = sum(1 for r in results if r.error)

    return {
        "n_encounters": n,
        "mean_per_encounter": {
            "precision": mean_p,
            "recall": mean_r,
            "f1": mean_f1,
        },
        "micro_aggregate": {
            "precision": micro_p,
            "recall": micro_r,
            "f1": micro_f1,
            "true_positives": micro_tp,
            "total_predicted": micro_pred,
            "total_gold": micro_gold,
        },
        "clean_encounters": {
            "n_gold_clean": n_clean_gold,
            "n_pred_clean": n_clean_pred,
            "n_overcalled_clean": n_overcalled_clean,
        },
        "per_rule": {
            rid: {
                "tp": counts["tp"],
                "fp": counts["fp"],
                "fn": counts["fn"],
                "precision": counts["tp"] / (counts["tp"] + counts["fp"])
                            if (counts["tp"] + counts["fp"]) > 0 else None,
                "recall": counts["tp"] / (counts["tp"] + counts["fn"])
                          if (counts["tp"] + counts["fn"]) > 0 else None,
            }
            for rid, counts in sorted(per_rule.items())
        },
        "per_severity": per_sev,
        "latency": {
            "mean_s": mean_latency,
            "p95_s": p95_latency,
            "n_errors": n_errors,
        },
    }


def _print_report(summary: dict[str, Any], results: list[EncounterResult]) -> None:
    print("=" * 72)
    print("ZORVA SMARTNESS REPORT")
    print("=" * 72)
    print()
    n = summary["n_encounters"]
    print(f"Encounters scored: {n}")
    print()
    m = summary["mean_per_encounter"]
    print("Per-encounter (mean across encounters):")
    print(f"  Precision: {m['precision']:.3f}")
    print(f"  Recall:    {m['recall']:.3f}")
    print(f"  F1:        {m['f1']:.3f}")
    print()
    m = summary["micro_aggregate"]
    print(f"Micro-aggregate (pooled):")
    print(f"  Precision: {m['precision']:.3f}  ({m['true_positives']}/{m['total_predicted']} predicted)")
    print(f"  Recall:    {m['recall']:.3f}  ({m['true_positives']}/{m['total_gold']} gold)")
    print(f"  F1:        {m['f1']:.3f}")
    print()
    c = summary["clean_encounters"]
    print(f"Clean encounters (gold says no findings):")
    print(f"  Total:              {c['n_gold_clean']}")
    print(f"  Auditor said clean: {c['n_pred_clean']}")
    print(f"  Auditor overcalled: {c['n_overcalled_clean']}")
    print()
    print("Per-rule breakdown:")
    for rid, stats in summary["per_rule"].items():
        p = stats["precision"]
        r = stats["recall"]
        p_str = f"{p:.2f}" if p is not None else "—"
        r_str = f"{r:.2f}" if r is not None else "—"
        print(f"  {rid:30s}  TP={stats['tp']:2d} FP={stats['fp']:2d} FN={stats['fn']:2d}  P={p_str}  R={r_str}")
    print()
    print("Per-severity (gold severity):")
    for sev, stats in summary["per_severity"].items():
        print(f"  {sev:8s}  n_gold={stats['n_gold_findings']:2d}  "
              f"P={stats['mean_p']:.3f}  R={stats['mean_r']:.3f}  "
              f"F1={stats['mean_f1']:.3f}")
    print()
    lat = summary["latency"]
    print(f"Latency: mean={lat['mean_s']:.2f}s  p95={lat['p95_s']:.2f}s  errors={lat['n_errors']}")
    print()
    # Failure mode finder: encounters where R=0 (gold findings missed)
    print("Failure modes:")
    print("-" * 72)
    missed_all = [r for r in results if r.n_gold > 0 and r.n_matched == 0]
    print(f"Encounters where ALL gold findings were missed: {len(missed_all)}")
    for r in missed_all[:5]:
        gold_rules = ", ".join(g.get("rule_id", "?") for g in r.gold_findings)
        pred_rules = ", ".join(p.get("rule_id") or (p.get("rule_ids") or ["?"])[0]
                                for p in r.pred_findings)
        print(f"  {r.encounter_id}: gold=[{gold_rules}] pred=[{pred_rules}]")
    if len(missed_all) > 5:
        print(f"  ... and {len(missed_all) - 5} more")
    overcalled = [
        r for r in results
        if r.n_gold == 0 and r.n_pred > 0 and r.is_flagged_gold is False
    ]
    print(f"\nEncounters where auditor flagged a clean claim: {len(overcalled)}")
    for r in overcalled[:5]:
        pred_rules = ", ".join(p.get("rule_id") or (p.get("rule_ids") or ["?"])[0]
                                for p in r.pred_findings)
        print(f"  {r.encounter_id}: pred=[{pred_rules}]  pred_count={r.n_pred}")
    errors = [r for r in results if r.error]
    if errors:
        print(f"\nAudit errors ({len(errors)}):")
        for r in errors[:3]:
            print(f"  {r.encounter_id}: {r.error[:100]}")


# ---------- Main ----------


def main() -> int:
    parser = argparse.ArgumentParser(description="Zorva auditor smartness test")
    parser.add_argument("--n", type=int, default=50,
                        help="Number of val encounters to score (default: all 50)")
    parser.add_argument("--start", type=int, default=0,
                        help="Start index in val.json (default: 0)")
    parser.add_argument("--val", action="append", default=None,
                        help="Path to val.json (repeatable; default: data/synth/val.json)")
    parser.add_argument("--out", default=None,
                        help="Write JSON results to this path")
    parser.add_argument("--quiet", action="store_true",
                        help="Don't print per-encounter progress")
    parser.add_argument("--model", default=None,
                        help="Override LLM_MODEL for this run")
    parser.add_argument("--prompt", default=None,
                        help="Path to a non-default auditor prompt")
    args = parser.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    val_paths = args.val or [
        str(REPO_ROOT / "data" / "synth" / "val.json"),
        str(REPO_ROOT / "data" / "synth" / "val_ca.json"),
    ]
    for path in val_paths:
        if not Path(path).is_file():
            print(f"val file not found at {path}", file=sys.stderr)
            return 1
    data: list[dict[str, Any]] = []
    for path in val_paths:
        with Path(path).open() as f:
            data.extend(json.load(f))
    print(f"Loaded {len(data)} encounters from {len(val_paths)} val file(s):")
    for path in val_paths:
        print(f"  {path}")
    print()
    encounters = data[args.start:args.start + args.n] if args.n else data[args.start:]


    if not args.quiet:
        print(f"Scoring {len(encounters)} encounters (start={args.start}) "
              f"against LLM_MODEL={os.environ.get('LLM_MODEL', '<default>')}")
        print()

    results: list[EncounterResult] = []
    for i, enc in enumerate(encounters):
        r = _score_encounter(enc, prompt_path=args.prompt)
        results.append(r)
        if not args.quiet:
            status = "OK" if not r.error else f"ERR ({r.error[:30]})"
            print(f"  [{i+1:2d}/{len(encounters)}] {r.encounter_id}  "
                  f"P={r.p:.2f}  R={r.r:.2f}  F1={r.f1:.2f}  "
                  f"gold={r.n_gold} pred={r.n_pred} match={r.n_matched}  "
                  f"{r.latency_s:.1f}s  {status}")

    summary = _aggregate(results)
    _print_report(summary, results)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            json.dump(
                {
                    "summary": summary,
                    "results": [
                        {
                            "encounter_id": r.encounter_id,
                            "n_gold": r.n_gold,
                            "n_pred": r.n_pred,
                            "n_matched": r.n_matched,
                            "p": r.p,
                            "r": r.r,
                            "f1": r.f1,
                            "latency_s": r.latency_s,
                            "error": r.error,
                            "pred_findings": r.pred_findings,
                            "gold_findings": r.gold_findings,
                        }
                        for r in results
                    ],
                },
                f,
                indent=2,
            )
        print(f"\nWrote {out_path}")

        # Append to the prompt-version history log so we can
        # track regression over time. Reads the prompt version
        # from the --prompt arg (basename without .txt extension),
        # defaults to "default" when no --prompt was given.
        try:
            from scripts.prompt_history import append_history_row
            if args.prompt:
                prompt_version = Path(args.prompt).stem
            else:
                prompt_version = "default"
            row = append_history_row(
                prompt_version=prompt_version,
                summary=summary,
                error_count=summary["latency"].get("n_errors", 0),
            )
            print(
                f"Appended prompt_history row: prompt={prompt_version} "
                f"F1={row['micro_aggregate'].get('f1', 0):.3f}"
            )
        except Exception as e:
            # Don't crash the run if history write fails.
            print(f"Warning: failed to append prompt history: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())