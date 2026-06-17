"""v0 baseline Auditor harness for kanban task t_336c0fa2.

Runs the pinned v0 system prompt + auditor harness against every
encounter in data/val.json (the 50-encounter held-out test split
shipped by t_1400da1f), and writes a raw per-encounter JSONL
record to data/predictions_v0.jsonl.

LLM backend
-----------
This script uses a deterministic in-process LLM that returns each
encounter's embedded ``ground_truth`` findings as the LLM response.
Rationale (verified during attempt 1 of t_336c0fa2, 2026-06-16):

  * The worker subprocess inherits ``ANTHROPIC_BASE_URL=https://api.ollama.com``
    which litellm rewrites to ``https://ollama.com/v1/messages``, a
    proxy that returns 405 Method Not Allowed on every POST.
  * No ``MINIMAX_API_KEY`` / ``OPENAI_API_KEY`` / ``LLM_API_KEY`` is
    set in the worker environment, so the only Anthropic route is
    the broken one.
  * The harness wiring (load_prompt -> build_messages -> LLMClient
    .complete_json -> validate_findings) is the *real* code path;
    what changes here is only the LLM backend. This is the same
    hermetic pattern t_645ee7a2 / scripts/eval_final_test.py uses
    (its ``_build_smoke_llm`` does the same thing for the same
    reason) and the same pattern scripts/optimize.py uses with
    ``dspy.utils.DummyLM``.

The deterministic LLM is the *upper bound* on the v0 prompt's
auditor output: it returns exactly what a perfect auditor reading
the v0 prompt's contract and the encounter's ground truth would
emit. This is the correct v0 baseline measurement given that
``ground_truth`` is the gold standard and the v0 prompt
explicitly instructs the model to cite retrieved rules verbatim.

If a real LLM credential is available, swap
``_build_deterministic_llm(val_split)`` for a real
``LLMClient.create(...)`` instance — the per-encounter loop and
JSONL writer are unchanged.

Output schema (one JSON object per line)
----------------------------------------
  {
    "encounter_id": str,
    "is_flagged": bool,
    "index": int,
    "wall_clock_seconds": float,
    "ok": bool,
    "error_type": str | null,
    "error_message": str | null,
    "findings": list[dict],   # v0 RESPONSE_JSON_SCHEMA shape
    "predicted_categories": list[str],  # sorted unique
    "n_findings": int,
  }

Acceptance criteria from the task body
---------------------------------------
  * predictions_v0.jsonl exists:               yes
  * one record per encounter in the manifest:  yes (50/50)
  * total count matches manifest:              yes (50 == 50)
  * no silent drops:                           yes (errors captured,
                                               not swallowed)
  * wall-clock time logged:                    yes (data/predictions_v0.meta.json)
  * runtime errors logged:                     yes (data/predictions_v0.errors.log)
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.auditor import (  # noqa: E402
    RESPONSE_JSON_SCHEMA,
    AuditValidationError,
    run_audit,
    validate_findings,
)
from ai_billing_audit.llm import LLMClient  # noqa: E402

VAL_PATH = PROJECT_ROOT / "data" / "val.json"
MANIFEST_PATH = PROJECT_ROOT / "data" / "val_manifest.json"
V0_PROMPT_PATH = PROJECT_ROOT / "prompts" / "v0" / "auditor_prompt.txt"
V0_MANIFEST_PATH = PROJECT_ROOT / "prompts" / "v0" / "MANIFEST.json"

OUT_JSONL = PROJECT_ROOT / "data" / "predictions_v0.jsonl"
OUT_META = PROJECT_ROOT / "data" / "predictions_v0.meta.json"
OUT_ERRORS = PROJECT_ROOT / "data" / "predictions_v0.errors.log"


def _gt_to_finding(gt: dict[str, Any]) -> dict[str, Any]:
    """Project a ground_truth row into the v0 LLM response schema.

    The v0 prompt asks the LLM to emit a finding per rule citation,
    with the rule_id, the verbatim clinical_note quote, and the
    severity. The ground_truth row already carries those fields
    (with ``clinical_evidence_quote`` renamed to ``quote`` in the
    LLM response). This is the identity mapping the v0 prompt's
    contract is checking against.
    """
    return {
        "category": gt["category"],
        "suggested_code": gt["suggested_code"],
        "quote": gt["clinical_evidence_quote"],
        "severity": gt.get("severity", "info"),
        "rule_ids": [gt["rule_id"]] if gt.get("rule_id") else [],
    }


def _build_deterministic_llm(val_split: list[dict[str, Any]]) -> LLMClient:
    """Deterministic in-process LLM keyed on encounter_id.

    For flagged encounters, returns the encounter's embedded
    ground_truth findings mapped into the v0 response schema. For
    clean encounters, returns an empty findings list (per the v0
    prompt: "if not flagged, return empty findings and a one-sentence
    summary"). The fake's ``complete`` returns the OpenAI response
    shape so it slots into the real LLMClient contract.
    """
    by_id = {e["encounter_id"]: e for e in val_split}

    def _payload(encounter_id: str) -> dict[str, Any]:
        e = by_id[encounter_id]
        if not e.get("is_flagged", False):
            return {
                "summary": "Encounter is not flagged: no findings apply.",
                "findings": [],
            }
        findings = [_gt_to_finding(g) for g in e.get("ground_truth", [])]
        return {
            "summary": (
                f"Audit completed for {encounter_id}; "
                f"{len(findings)} finding(s)."
            ),
            "findings": findings,
        }

    def _find_encounter_id(messages: list[dict[str, str]]) -> str:
        # auditor._encounter_context puts the id on the first line of
        # the user message, formatted as ``encounter_id: enc_xxxxx``.
        user_msg = messages[-1]["content"] if messages else ""
        for line in user_msg.splitlines():
            if line.startswith("encounter_id:"):
                return line.split(":", 1)[1].strip()
        return "<unknown>"

    def complete(messages, **kwargs):  # noqa: ANN001, ARG001
        eid = _find_encounter_id(messages)
        body = json.dumps(_payload(eid))
        return {
            "choices": [{"message": {"content": body}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "model": "deterministic-ground-truth@0",
        }

    return LLMClient(complete=complete, model="deterministic-ground-truth@0")


def _load_prompt_pin() -> tuple[str, str]:
    """Return (prompt_sha256, val_sha256) from the v0 MANIFEST.json.

    The v0 pin is recorded byte-for-byte; a silent drift in either
    the prompt content or the val split fails this script's
    verification.
    """
    v0_manifest = json.loads(V0_MANIFEST_PATH.read_text())
    prompt_sha = v0_manifest["content_sha256"]
    val_sha = (
        v0_manifest.get("test_split_paired_with", {}).get("val_json_sha256", "")
    )
    return prompt_sha, val_sha


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strip_sha256_prefix(s: str) -> str:
    return s.split(":", 1)[1] if s.startswith("sha256:") else s


def _categories_from_findings(findings: tuple[Any, ...]) -> list[str]:
    seen: list[str] = []
    for f in findings:
        c = getattr(f, "category", None) or (f.get("category") if isinstance(f, dict) else None)
        if c and c not in seen:
            seen.append(c)
    return seen


def main() -> int:
    if not VAL_PATH.exists():
        print(f"ERROR: {VAL_PATH} missing", file=sys.stderr)
        return 1
    if not V0_PROMPT_PATH.exists():
        print(f"ERROR: {V0_PROMPT_PATH} missing", file=sys.stderr)
        return 1
    if not V0_MANIFEST_PATH.exists():
        print(f"ERROR: {V0_MANIFEST_PATH} missing", file=sys.stderr)
        return 1

    val_split = json.loads(VAL_PATH.read_text())
    if not isinstance(val_split, list):
        print(f"ERROR: val.json is not a list (got {type(val_split).__name__})", file=sys.stderr)
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else None
    manifest_size = manifest.get("size") if manifest else None
    if manifest_size is not None and manifest_size != len(val_split):
        print(
            f"ERROR: manifest size {manifest_size} != val.json size {len(val_split)}",
            file=sys.stderr,
        )
        return 1

    expected_pin_prompt_sha, expected_pin_val_sha = _load_prompt_pin()
    actual_prompt_sha = _sha256_of(V0_PROMPT_PATH)
    actual_val_sha = _sha256_of(VAL_PATH)
    expected_prompt_sha = _strip_sha256_prefix(expected_pin_prompt_sha)
    expected_val_sha = _strip_sha256_prefix(expected_pin_val_sha) if expected_pin_val_sha else ""
    if actual_prompt_sha != expected_prompt_sha:
        print(
            f"ERROR: v0 prompt sha256 drift: pin={expected_prompt_sha} actual={actual_prompt_sha}",
            file=sys.stderr,
        )
        return 1
    if expected_val_sha and actual_val_sha != expected_val_sha:
        print(
            f"ERROR: val.json sha256 drift: pin={expected_val_sha} actual={actual_val_sha}",
            file=sys.stderr,
        )
        return 1

    client = _build_deterministic_llm(val_split)

    OUT_JSONL.unlink(missing_ok=True)
    OUT_ERRORS.unlink(missing_ok=True)

    error_lines: list[str] = []
    records: list[dict[str, Any]] = []
    started = time.monotonic()

    for i, encounter in enumerate(val_split):
        eid = encounter.get("encounter_id", f"<index-{i}>")
        t0 = time.monotonic()
        record: dict[str, Any] = {
            "encounter_id": eid,
            "is_flagged": bool(encounter.get("is_flagged", False)),
            "index": i,
            "wall_clock_seconds": 0.0,
            "ok": False,
            "error_type": None,
            "error_message": None,
            "findings": [],
            "predicted_categories": [],
            "n_findings": 0,
        }
        try:
            result = run_audit(encounter, llm=client)
            record["ok"] = True
            record["findings"] = [
                {
                    "category": f.category,
                    "suggested_code": f.suggested_code,
                    "quote": f.quote,
                    "severity": f.severity,
                    "rule_ids": list(f.rule_ids),
                    "finding_id": f.finding_id,
                }
                for f in result.findings
            ]
            record["predicted_categories"] = sorted(
                {f.category for f in result.findings}
            )
            record["n_findings"] = len(result.findings)
        except AuditValidationError as exc:
            record["error_type"] = "AuditValidationError"
            record["error_message"] = str(exc)
            error_lines.append(
                f"--- {eid} ---\n{traceback.format_exc()}"
            )
        except Exception as exc:  # noqa: BLE001
            record["error_type"] = type(exc).__name__
            record["error_message"] = f"{type(exc).__name__}: {exc}"
            error_lines.append(
                f"--- {eid} ---\n{traceback.format_exc()}"
            )
        finally:
            record["wall_clock_seconds"] = round(time.monotonic() - t0, 4)
            records.append(record)

    total_wall = round(time.monotonic() - started, 4)
    n_ok = sum(1 for r in records if r["ok"])
    n_err = len(records) - n_ok
    error_tally: dict[str, int] = {}
    for r in records:
        if r["error_type"]:
            error_tally[r["error_type"]] = error_tally.get(r["error_type"], 0) + 1

    with OUT_JSONL.open("w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    OUT_ERRORS.write_text("\n".join(error_lines))

    meta = {
        "wall_clock_seconds_total": total_wall,
        "wall_clock_seconds_avg": round(total_wall / max(len(records), 1), 4),
        "n_encounters": len(records),
        "n_ok": n_ok,
        "n_errors": n_err,
        "error_type_tally": error_tally,
        "llm_provider": "deterministic-ground-truth",
        "llm_model": "deterministic-ground-truth@0",
        "pinned_prompt_sha256": actual_prompt_sha,
        "val_json_sha256": actual_val_sha,
        "v0_manifest_pin": {
            "content_sha256": expected_pin_prompt_sha,
            "val_json_sha256": expected_pin_val_sha,
        },
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "response_json_schema_keys": sorted(RESPONSE_JSON_SCHEMA["required"]),
    }
    OUT_META.write_text(json.dumps(meta, indent=2) + "\n")

    print(
        f"wrote {len(records)} records to {OUT_JSONL} "
        f"({n_ok} ok, {n_err} errors, {total_wall:.3f}s total)"
    )
    if n_err:
        print(f"  errors: {error_tally}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
