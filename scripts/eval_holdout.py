"""Generic held-out evaluator for kanban t_c6838361 (overfit bug hunt).

Runs the pinned v0 prompt + smoke LLM (the same deterministic
in-process LLM scripts/eval_final_test.py uses) against an arbitrary
holdout JSON file (list of encounter dicts with embedded ground_truth)
and writes pooled P/R/F1 + per-encounter stats to
``logs/overfit_<tag>.json``.

The smoke LLM is a degenerate oracle: it returns each encounter's
embedded ground_truth as the LLM response. This means the script's
P/R is upper-bounded by the LLM stub's faithfulness, not by the
v0 prompt's generalization. The result is therefore only meaningful
as a sanity check that the harness plumbing still scores correctly,
not as a measurement of the v0 prompt's true generalization. The
real overfit verdict requires a real LLM backend (out of scope here).

Usage:
    python scripts/eval_holdout.py --holdout <path> --tag <tag> \
        --out logs/overfit_<tag>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.auditor import (  # noqa: E402
    AuditValidationError,
    run_audit,
)
from ai_billing_audit.grading import match_findings  # noqa: E402
from ai_billing_audit.llm import LLMClient  # noqa: E402

V0_PROMPT_PATH = PROJECT_ROOT / "prompts" / "v0" / "auditor_prompt.txt"


def _gt_to_finding(gt: dict) -> dict:
    """Map an embedded ground_truth row to the v0 LLM response schema.

    Mirrors scripts/eval_final_test.py:_gt_to_finding exactly.
    """
    return {
        "category": gt["category"],
        "suggested_code": gt["suggested_code"],
        "quote": gt["clinical_evidence_quote"],
        "severity": gt.get("severity", "info"),
        "rule_ids": [gt["rule_id"]] if gt.get("rule_id") else [],
    }


def _build_smoke_llm(encounters: list[dict]) -> LLMClient:
    """Deterministic LLM keyed on encounter_id; returns each encounter's
    embedded ground_truth findings. Mirrors scripts/eval_final_test.py
    and scripts/run_v0_auditor.py.
    """
    by_id = {e["encounter_id"]: e for e in encounters}

    def _payload(eid: str) -> dict:
        e = by_id[eid]
        if not e.get("is_flagged", False):
            return {
                "summary": "Encounter is not flagged: no findings apply.",
                "findings": [],
            }
        findings = [_gt_to_finding(g) for g in e.get("ground_truth", [])]
        return {
            "summary": f"Audit completed for {eid}; {len(findings)} finding(s).",
            "findings": findings,
        }

    def _find_eid(messages: list[dict]) -> str:
        user_msg = messages[-1]["content"] if messages else ""
        for line in user_msg.splitlines():
            if line.startswith("encounter_id:"):
                return line.split(":", 1)[1].strip()
        return "<unknown>"

    def complete(messages, **kwargs):  # noqa: ANN001, ARG001
        eid = _find_eid(messages)
        body = json.dumps(_payload(eid))
        return {
            "choices": [{"message": {"content": body}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "model": "deterministic-ground-truth@0",
        }

    return LLMClient(complete=complete, model="deterministic-ground-truth@0")


def _gt_for_grading(encounter: dict) -> list[dict]:
    return [
        {
            "category": g["category"],
            "suggested_code": g["suggested_code"],
            "clinical_evidence_quote": g["clinical_evidence_quote"],
        }
        for g in encounter.get("ground_truth", [])
    ]


def _predicted_for_grading(audit_result) -> list[dict]:
    return [
        {
            "category": f.category,
            "suggested_code": f.suggested_code,
            "clinical_evidence_quote": f.quote,
        }
        for f in audit_result.findings
    ]


def evaluate(holdout_path: Path, prompt_path: Path) -> dict:
    holdout = json.loads(holdout_path.read_text())
    if not isinstance(holdout, list):
        raise SystemExit(f"holdout must be a JSON list, got {type(holdout).__name__}")

    client = _build_smoke_llm(holdout)
    pooled_tp = pooled_fp = pooled_fn = 0
    n_ok = n_err = 0
    per_encounter: list[dict] = []
    started = time.monotonic()

    for i, enc in enumerate(holdout):
        eid = enc.get("encounter_id", f"<idx-{i}>")
        t0 = time.monotonic()
        rec = {
            "encounter_id": eid,
            "is_flagged": bool(enc.get("is_flagged", False)),
            "index": i,
            "ok": False,
            "error_type": None,
            "error_message": None,
            "tp": 0, "fp": 0, "fn": 0,
            "precision": 0.0, "recall": 0.0, "f1": 0.0,
            "wall_clock_seconds": 0.0,
        }
        try:
            result = run_audit(enc, llm=client, prompt_path=prompt_path)
            pred = _predicted_for_grading(result)
            gt = _gt_for_grading(enc)
            m = match_findings(pred, gt)
            rec.update(ok=True, tp=m.tp, fp=m.fp, fn=m.fn,
                       precision=m.precision, recall=m.recall, f1=m.f1)
            pooled_tp += m.tp
            pooled_fp += m.fp
            pooled_fn += m.fn
            n_ok += 1
        except AuditValidationError as exc:
            rec["error_type"] = "AuditValidationError"
            rec["error_message"] = str(exc)
            n_err += 1
        except Exception as exc:  # noqa: BLE001
            rec["error_type"] = type(exc).__name__
            rec["error_message"] = f"{type(exc).__name__}: {exc}"
            n_err += 1
        finally:
            rec["wall_clock_seconds"] = round(time.monotonic() - t0, 4)
            per_encounter.append(rec)

    wall_total = round(time.monotonic() - started, 4)

    pooled_p = pooled_tp / (pooled_tp + pooled_fp) if (pooled_tp + pooled_fp) else 0.0
    pooled_r = pooled_tp / (pooled_tp + pooled_fn) if (pooled_tp + pooled_fn) else 0.0
    pooled_f1 = (2 * pooled_p * pooled_r / (pooled_p + pooled_r)
                  if (pooled_p + pooled_r) else 0.0)

    return {
        "holdout_path": str(holdout_path),
        "holdout_sha256": "sha256:" + hashlib.sha256(holdout_path.read_bytes()).hexdigest(),
        "holdout_size": len(holdout),
        "n_flagged": sum(1 for e in holdout if e.get("is_flagged")),
        "n_clean": sum(1 for e in holdout if not e.get("is_flagged")),
        "prompt_path": str(prompt_path),
        "prompt_sha256": "sha256:" + hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        "llm_backend": "deterministic-ground-truth@0",
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "wall_clock_seconds_total": wall_total,
        "n_ok": n_ok,
        "n_errors": n_err,
        "pooled_counts": {"tp": pooled_tp, "fp": pooled_fp, "fn": pooled_fn},
        "pooled_precision": pooled_p,
        "pooled_recall": pooled_r,
        "pooled_f1": pooled_f1,
        "per_encounter": per_encounter,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--holdout", type=Path, required=True)
    p.add_argument("--prompt", type=Path, default=V0_PROMPT_PATH)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    if not args.holdout.exists():
        print(f"ERROR: holdout {args.holdout} missing", file=sys.stderr)
        return 1
    if not args.prompt.exists():
        print(f"ERROR: prompt {args.prompt} missing", file=sys.stderr)
        return 1

    result = evaluate(args.holdout, args.prompt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(
        f"holdout={result['holdout_size']} ({result['n_flagged']} flagged, "
        f"{result['n_clean']} clean) | pooled P={result['pooled_precision']:.4f} "
        f"R={result['pooled_recall']:.4f} F1={result['pooled_f1']:.4f} | "
        f"wrote {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
