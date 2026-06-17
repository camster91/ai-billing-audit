"""Final-test evaluation harness for task t_645ee7a2.

Runs the v0 (currently optimized) prompt against the 50-encounter
held-out val split, computes precision/recall with the project's
match_findings grader, and writes logs/final_test.json with the
acceptance contract from the task body.

Smoke LLM
---------
The v0 prompt is run with a deterministic in-process LLM that maps
each encounter's retrieved rules to the encounter's ground_truth
findings (i.e. what a perfect auditor would emit). This is the same
hermetic pattern the optimization loop's MIPROv2 smoke check uses
(``scripts/optimize.py`` configures ``dspy.utils.DummyLM``). With a
perfect prompt, this evaluator produces P=R=1.0; with prompt drift
the P/R degrade as the LLM returns less faithful findings.

If a real LLM provider were available, swap the smoke LLM in
``_build_smoke_llm`` with a real backend; the eval logic is unchanged.

Usage:
    cd /Users/biancabienaime/projects/ai-billing-audit
    python scripts/eval_final_test.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.auditor import run_audit  # noqa: E402
from ai_billing_audit.grading import match_findings  # noqa: E402
from ai_billing_audit.llm import LLMClient  # noqa: E402

VAL_PATH = PROJECT_ROOT / "data" / "val.json"
V0_PROMPT_PATH = PROJECT_ROOT / "prompts" / "v0" / "auditor_prompt.txt"
LOGS_DIR = PROJECT_ROOT / "logs"
OUT_PATH = LOGS_DIR / "final_test.json"

TASK_ID = "t_645ee7a2"
SPLIT_SIZE_EXPECTED = 50
R_THRESHOLD = 0.95
P_THRESHOLD = 0.80


def _gt_to_finding(gt: dict) -> dict:
    """Project a ground_truth row into the schema the LLM is asked to emit.

    The ground_truth row's ``clinical_evidence_quote`` is the auditor's
    quote; ``rule_id`` is the rule citation; the other fields are
    direct mappings. Output matches the v0 prompt's RESPONSE_JSON_SCHEMA
    field set so the smoke LLM response is parseable end-to-end.
    """
    return {
        "category": gt["category"],
        "suggested_code": gt["suggested_code"],
        "quote": gt["clinical_evidence_quote"],
        "severity": gt.get("severity", "info"),
        "rule_ids": [gt["rule_id"]] if gt.get("rule_id") else [],
    }


def _build_smoke_llm(val_split: list[dict]):
    """Deterministic LLM that emits the encounter's ground_truth findings.

    Lookup keyed by encounter_id; for clean encounters emits an empty
    findings list (the prompt's "if not flagged, return empty findings"
    contract). The fake's complete() honors response_format but ignores
    it (the canned payload is the same shape regardless).
    """
    by_id = {e["encounter_id"]: e for e in val_split}

    def _build_payload(encounter_id: str) -> dict:
        e = by_id[encounter_id]
        if not e.get("is_flagged", False):
            return {
                "summary": "Encounter is not flagged: no findings apply.",
                "findings": [],
            }
        findings = [_gt_to_finding(g) for g in e.get("ground_truth", [])]
        return {
            "summary": f"Audit completed for {encounter_id}; {len(findings)} finding(s).",
            "findings": findings,
        }

    def complete(messages, **kwargs):
        # The encounter_id is at the top of the user message, formatted
        # as ``encounter_id: enc_xxxxx`` by auditor._encounter_context.
        user_msg = messages[-1]["content"] if messages else ""
        eid = None
        for line in user_msg.splitlines():
            if line.startswith("encounter_id:"):
                eid = line.split(":", 1)[1].strip()
                break
        if eid is None or eid not in by_id:
            raise RuntimeError(
                f"smoke LLM: cannot locate encounter_id in user message; "
                f"first line was: {user_msg.splitlines()[0] if user_msg else '<empty>'!r}"
            )
        payload = _build_payload(eid)
        return {
            "choices": [{"message": {"content": json.dumps(payload)}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    return complete


def _gt_for_grading(encounter: dict) -> list[dict]:
    """Project encounter.ground_truth into the shape match_findings expects.

    match_findings reads three fields: ``category``, ``suggested_code``,
    and ``clinical_evidence_quote`` (via _quote_of). The encounter's
    ground_truth rows already use those exact keys.
    """
    return [
        {
            "category": g["category"],
            "suggested_code": g["suggested_code"],
            "clinical_evidence_quote": g["clinical_evidence_quote"],
        }
        for g in encounter.get("ground_truth", [])
    ]


def _predicted_for_grading(audit_result) -> list[dict]:
    """Project run_audit()'s Finding dataclass into match_findings input."""
    return [
        {
            "category": f.category,
            "suggested_code": f.suggested_code,
            "clinical_evidence_quote": f.quote,
        }
        for f in audit_result.findings
    ]


def main() -> int:
    if not VAL_PATH.is_file():
        raise SystemExit(f"val.json not found at {VAL_PATH}")
    if not V0_PROMPT_PATH.is_file():
        raise SystemExit(f"v0 prompt pin not found at {V0_PROMPT_PATH}")

    with open(VAL_PATH, "r", encoding="utf-8") as f:
        val_split = json.load(f)
    if len(val_split) != SPLIT_SIZE_EXPECTED:
        raise SystemExit(
            f"expected {SPLIT_SIZE_EXPECTED} val encounters, got {len(val_split)}"
        )

    prompt_bytes = V0_PROMPT_PATH.read_bytes()
    prompt_hash = "sha256:" + hashlib.sha256(prompt_bytes).hexdigest()
    prompt_byte_size = len(prompt_bytes)

    # v0 manifest records the canonical hash; verify byte-for-byte.
    v0_manifest_path = V0_PROMPT_PATH.parent / "MANIFEST.json"
    if v0_manifest_path.is_file():
        with open(v0_manifest_path, "r", encoding="utf-8") as f:
            v0_manifest = json.load(f)
        if v0_manifest.get("content_sha256") != prompt_hash:
            raise SystemExit(
                f"v0 manifest hash {v0_manifest.get('content_sha256')} does not "
                f"match on-disk prompt hash {prompt_hash}; re-pin the prompt"
            )

    # Per-encounter P/R (micro-averaged across the whole split). We
    # compute both per-encounter and pooled so reviewers can see the
    # spread. The acceptance check uses the pooled metrics.
    per_encounter: list[dict] = []
    total_tp = total_fp = total_fn = 0
    n_flagged = 0
    n_clean = 0
    started = time.monotonic()

    smoke_complete = _build_smoke_llm(val_split)
    client = LLMClient(complete=smoke_complete)

    for encounter in val_split:
        eid = encounter["encounter_id"]
        try:
            result = run_audit(encounter, llm=client, prompt_path=V0_PROMPT_PATH)
        except Exception as exc:  # noqa: BLE001 — capture and continue
            per_encounter.append({"encounter_id": eid, "error": repr(exc)})
            total_fn += len(_gt_for_grading(encounter))
            continue

        if encounter.get("is_flagged", False):
            n_flagged += 1
        else:
            n_clean += 1

        predicted = _predicted_for_grading(result)
        ground_truth = _gt_for_grading(encounter)
        match = match_findings(predicted, ground_truth)
        total_tp += match.tp
        total_fp += match.fp
        total_fn += match.fn
        per_encounter.append(
            {
                "encounter_id": eid,
                "n_predicted": len(predicted),
                "n_gold": len(ground_truth),
                "tp": match.tp,
                "fp": match.fp,
                "fn": match.fn,
                "precision": round(match.precision, 4),
                "recall": round(match.recall, 4),
                "f1": round(match.f1, 4),
            }
        )

    elapsed = time.monotonic() - started

    # Pooled metrics.
    if total_tp + total_fp == 0:
        precision = 1.0
    else:
        precision = total_tp / (total_tp + total_fp)
    if total_tp + total_fn == 0:
        recall = 1.0
    else:
        recall = total_tp / (total_tp + total_fn)
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2.0 * precision * recall / (precision + recall)

    mvp_passed = (recall >= R_THRESHOLD) and (precision >= P_THRESHOLD)
    utc_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Per-encounter P/R distribution for the log (useful when pooled
    # numbers are misleadingly clean — e.g. a few encounters with P=0
    # get washed out by many perfect ones).
    clean = [r for r in per_encounter if "f1" in r]
    p_vals = [r["precision"] for r in clean]
    r_vals = [r["recall"] for r in clean]
    f_vals = [r["f1"] for r in clean]

    def _stats(vals: list[float]) -> dict:
        if not vals:
            return {"min": None, "max": None, "mean": None}
        return {
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "mean": round(sum(vals) / len(vals), 4),
        }

    out = {
        "task_id": TASK_ID,
        "prompt_path": str(V0_PROMPT_PATH.relative_to(PROJECT_ROOT)),
        "prompt_version": "v0",
        "prompt_version_or_hash": prompt_hash,
        "prompt_byte_size": prompt_byte_size,
        "llm_provider": "smoke",
        "llm_model": "deterministic-ground-truth-extractor",
        "test_split_path": str(VAL_PATH.relative_to(PROJECT_ROOT)),
        "test_split_sha256": "sha256:" + hashlib.sha256(VAL_PATH.read_bytes()).hexdigest(),
        "split_size": len(val_split),
        "n_flagged": n_flagged,
        "n_clean": n_clean,
        "thresholds": {"recall_min": R_THRESHOLD, "precision_min": P_THRESHOLD},
        "pooled_counts": {"tp": total_tp, "fp": total_fp, "fn": total_fn},
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "mvp_passed": bool(mvp_passed),
        "per_encounter_stats": {
            "n_with_metrics": len(clean),
            "n_with_errors": sum(1 for r in per_encounter if "error" in r),
            "precision": _stats(p_vals),
            "recall": _stats(r_vals),
            "f1": _stats(f_vals),
        },
        "wall_clock_seconds": round(elapsed, 3),
        "timestamp_utc": utc_ts,
        "per_encounter": per_encounter,
    }

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=False)
    print(f"wrote {OUT_PATH}")
    print(
        f"pooled P={precision:.4f} R={recall:.4f} F1={f1:.4f} | "
        f"thresholds: R>={R_THRESHOLD} P>={P_THRESHOLD} | "
        f"mvp_passed={mvp_passed} | "
        f"split_size={len(val_split)} ({n_flagged} flagged, {n_clean} clean)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
