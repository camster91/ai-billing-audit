"""Cross-provider auditor runner for the MVP acceptance test.

Runs the v0 auditor prompt + the v0 RESPONSE_JSON_SCHEMA against every
encounter in the 150-encounter test sample (data/test_sample.jsonl) using
a real LLMClient for one of {minimax, claude, openai, gemini}. Writes a
per-encounter JSONL to ``runs/acceptance/<provider>-<timestamp>/predictions.jsonl``
plus a per-provider run log and metadata sidecar.

Two execution modes
-------------------

Real LLM mode (default)
    Builds a real LLMClient backed by ``litellm.completion`` for the
    requested provider. Reads the API key from the provider-specific
    env var (see ``_PROVIDER_KEY_ENV`` below). Costs real money and
    needs network access.

Dry-run mode (``--dry-run``)
    Builds the same code path but plugs in a deterministic in-process
    LLM that returns each encounter's embedded ground_truth findings
    mapped into the v0 response schema. This is the same pattern
    ``scripts/run_v0_auditor.py`` uses and is the right hermetic
    baseline when no API credentials are available. A dry run proves
    the wiring (load_prompt -> build_messages -> LLMClient
    .complete_json -> validate_findings) end-to-end and produces
    a 100%-valid baseline against which real-provider runs can be
    diffed.

Output schema (one JSON object per line)
----------------------------------------
Same shape as ``scripts/run_v0_auditor.py`` so the same scoring
pipeline works on the output:

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
    "token_usage": {         # real-mode only; null in dry-run
      "prompt_tokens": int | null,
      "completion_tokens": int | null,
      "total_tokens": int | null
    }
  }

Per-provider metadata (``predictions.meta.json``)
-------------------------------------------------
  {
    "provider": "minimax",
    "model": "minimax/MiniMax-M3",
    "mode": "real" | "dry-run",
    "n_encounters": 150,
    "n_ok": 148,
    "n_errors": 2,
    "error_type_tally": {"AuditValidationError": 1, "APIConnectionError": 1},
    "wall_clock_seconds_total": 42.31,
    "wall_clock_seconds_avg": 0.282,
    "prompt_sha256": "sha256:...",
    "test_sample_sha256": "sha256:...",
    "ran_at": "2026-06-17T..."
  }

Usage
-----
Real run:
    LLM_PROVIDER=minimax \\
    MINIMAX_API_KEY=... \\
    .venv/bin/python scripts/run_cross_provider.py --provider minimax

Dry-run (no key, no network):
    .venv/bin/python scripts/run_cross_provider.py --provider minimax --dry-run

Cost-controlled smoke (first 5 encounters only):
    .venv/bin/python scripts/run_cross_provider.py --provider claude --n 5

Environment
-----------
LLM_PROVIDER       - which backend to use (overridden by --provider)
MINIMAX_API_KEY    - MiniMax (provider name: minimax)
ANTHROPIC_API_KEY  - Claude  (provider name: claude)
OPENAI_API_KEY     - OpenAI  (provider name: openai)
GEMINI_API_KEY     - Gemini  (provider name: gemini)
GOOGLE_API_KEY     - accepted as a fallback for GEMINI_API_KEY

Only the env var for the chosen provider needs to be set; the others
are not consulted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
RUNS_ROOT = PROJECT_ROOT / "runs" / "acceptance"

# Provider -> env var that holds the API key. Mirrors
# src/llm_client.py:_PROVIDER_CLASS_PATHS and the api_key_env class
# attributes on the four concrete classes.
_PROVIDER_KEY_ENV: dict[str, str] = {
    "minimax": "MINIMAX_API_KEY",
    "claude":  "ANTHROPIC_API_KEY",
    "openai":  "OPENAI_API_KEY",
    "gemini":  "GEMINI_API_KEY",
}
# Gemini accepts both names; this is the secondary fallback for the env
# check below (the concrete GeminiClient class checks both itself).
_GEMINI_KEY_FALLBACK = "GOOGLE_API_KEY"

# Provider -> default model id passed to litellm.completion. Mirrors the
# default in the corresponding concrete class in src/llm_client.py.
_PROVIDER_DEFAULT_MODEL: dict[str, str] = {
    "minimax": "minimax/MiniMax-M3",
    "claude":  "anthropic/claude-3-5-sonnet-20241022",
    "openai":  "gpt-4o-mini",
    "gemini":  "gemini/gemini-1.5-flash",
}


# ---------------------------------------------------------------------------
# Imports (after sys.path tweak so this script can be run from anywhere)
# ---------------------------------------------------------------------------

def _ensure_src_on_path() -> None:
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))


# ---------------------------------------------------------------------------
# Encounters / split loading
# ---------------------------------------------------------------------------

TEST_SAMPLE_PATH = PROJECT_ROOT / "data" / "test_sample.jsonl"
TRAIN_PATH = PROJECT_ROOT / "data" / "train.json"
VAL_PATH = PROJECT_ROOT / "data" / "val.json"


def _load_test_sample() -> list[dict]:
    """Return the test_sample manifest records (one per encounter)."""
    records: list[dict] = []
    with TEST_SAMPLE_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _load_full_split() -> dict[str, dict]:
    """Return ``{encounter_id: encounter_dict}`` for train + val."""
    by_id: dict[str, dict] = {}
    for path in (TRAIN_PATH, VAL_PATH):
        for e in json.loads(path.read_text()):
            by_id[e["encounter_id"]] = e
    return by_id


def _load_ordered_encounters() -> list[dict]:
    """Return the encounter content in the test_sample order."""
    sample = _load_test_sample()
    by_id = _load_full_split()
    out: list[dict] = []
    for rec in sample:
        eid = rec["encounter_id"]
        if eid not in by_id:
            raise SystemExit(
                f"encounter {eid!r} from test_sample.jsonl not found in "
                f"train+val; rerun scripts/build_test_sample_manifest.py"
            )
        out.append(by_id[eid])
    return out


# ---------------------------------------------------------------------------
# LLMClient construction
# ---------------------------------------------------------------------------

def _build_real_litellm_completion(
    provider: str,
) -> Callable[..., Any]:
    """Return a ``complete`` closure that delegates to ``litellm.completion``.

    Mirrors the wiring ``scripts/run_v0_auditor.py`` uses for the
    deterministic stub but pointed at the real litellm transport.
    The closure captures ``model`` and ``api_key`` at construction time
    and returns the OpenAI-shaped dict the real LLMClient expects:

        {"choices": [{"message": {"content": <json str>}}],
         "usage": {"prompt_tokens": ..., "completion_tokens": ..., "total_tokens": ...}}
    """
    import litellm  # local import; litellm is heavy

    model = _PROVIDER_DEFAULT_MODEL[provider]
    key_env = _PROVIDER_KEY_ENV[provider]
    api_key = os.environ.get(key_env, "")
    if not api_key and provider == "gemini":
        api_key = os.environ.get(_GEMINI_KEY_FALLBACK, "")
    if not api_key:
        raise SystemExit(
            f"ERROR: {key_env} is not set (and {_GEMINI_KEY_FALLBACK} "
            f"either for gemini). Export it or pass --dry-run."
        )

    def _complete(*, messages: list, **kwargs: Any) -> Any:
        # The real LLMClient.complete() forwards model + timeout in kwargs;
        # let those override the closure's defaults (so a future caller
        # that passes --model=foo takes effect). temperature falls back to
        # 0.0 for determinism.
        call_model = kwargs.pop("model", model)
        call_timeout = kwargs.pop("timeout", None)
        call_temperature = kwargs.pop("temperature", 0.0)
        # RESPONSE_JSON_SCHEMA arrives as a `response_format={"type": "json_schema", ...}`
        # envelope from complete_json(). The v0 schema is a real JSON Schema, not
        # a legacy {type: json_object}, so we forward the envelope as-is.
        response = litellm.completion(
            model=call_model,
            messages=list(messages),
            api_key=api_key,
            temperature=call_temperature,
            response_format=kwargs.pop("response_format", {"type": "json_object"}),
            timeout=call_timeout,
            **kwargs,
        )
        # Stash the token usage on the closure itself for the runner to
        # harvest after each call. Single-threaded loop, so no race.
        _last_token_usage["prompt_tokens"] = getattr(
            getattr(response, "usage", None), "prompt_tokens", None
        )
        _last_token_usage["completion_tokens"] = getattr(
            getattr(response, "usage", None), "completion_tokens", None
        )
        _last_token_usage["total_tokens"] = getattr(
            getattr(response, "usage", None), "total_tokens", None
        )
        return response

    # Mutable single-element container so the closure can write token usage
    # and the runner can read it. Single-threaded loop — no race.
    _last_token_usage: dict[str, int | None] = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }
    return _complete


def _build_deterministic_complete(
    encounters: list[dict],
) -> Callable[..., Any]:
    """Return a ``complete`` closure that returns each encounter's ground truth.

    Same pattern as ``scripts/run_v0_auditor.py:_build_deterministic_llm``
    — returns the ground_truth findings mapped into the v0 response
    schema. Returns the OpenAI-shaped dict the real LLMClient expects.
    """
    by_id = {e["encounter_id"]: e for e in encounters}

    def _gt_to_finding(gt: dict[str, Any]) -> dict[str, Any]:
        return {
            "category": gt["category"],
            "suggested_code": gt["suggested_code"],
            "quote": gt["clinical_evidence_quote"],
            "severity": gt.get("severity", "info"),
            "rule_ids": [gt["rule_id"]] if gt.get("rule_id") else [],
        }

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

    def _find_encounter_id(messages: list) -> str:
        # auditor._encounter_context puts the id on the first line of the
        # user message as ``encounter_id: enc_xxxxx``.
        user_msg = messages[-1]["content"] if messages else ""
        for line in user_msg.splitlines():
            if line.startswith("encounter_id:"):
                return line.split(":", 1)[1].strip()
        return "<unknown>"

    def _complete(*, messages: list, **kwargs: Any) -> Any:
        eid = _find_encounter_id(messages)
        body = json.dumps(_payload(eid))
        return {
            "choices": [{"message": {"content": body}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "model": "deterministic-ground-truth@0",
        }

    return _complete


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--provider",
        choices=sorted(_PROVIDER_KEY_ENV.keys()),
        required=True,
        help="LLM provider to drive this run with.",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=None,
        help=(
            "Cap the number of encounters (default: all 150). Useful for "
            "cost-controlled smoke runs; pass --n 5 to drive 5 encounters."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Use a deterministic in-process LLM that returns each "
            "encounter's ground truth. No network, no API key. Useful for "
            "verifying the pipeline end-to-end without real credentials."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help=(
            "Override the output directory. Default: "
            "runs/acceptance/<provider>-<UTC-timestamp>/"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-encounter LLM call timeout, in seconds. Default: 60.",
    )
    args = parser.parse_args()

    _ensure_src_on_path()
    from ai_billing_audit.auditor import (  # noqa: E402
        AuditValidationError,
        RESPONSE_JSON_SCHEMA,
        run_audit,
    )
    from ai_billing_audit.llm import LLMClient  # noqa: E402

    # Resolve the encounter list and apply --n cap.
    encounters = _load_ordered_encounters()
    if args.n is not None:
        if args.n <= 0:
            print("ERROR: --n must be positive", file=sys.stderr)
            return 1
        encounters = encounters[: args.n]

    # Build the LLMClient.
    if args.dry_run:
        complete_fn = _build_deterministic_complete(encounters)
        client = LLMClient(complete=complete_fn, model="deterministic-ground-truth@0")
        provider_label = f"{args.provider} (dry-run)"
        model_id = "deterministic-ground-truth@0"
    else:
        complete_fn = _build_real_litellm_completion(args.provider)
        client = LLMClient(complete=complete_fn, model=_PROVIDER_DEFAULT_MODEL[args.provider], timeout=args.timeout)
        provider_label = args.provider
        model_id = _PROVIDER_DEFAULT_MODEL[args.provider]

    # Set the output directory.
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.out_dir is not None:
        out_dir = args.out_dir
    else:
        out_dir = RUNS_ROOT / f"{args.provider}-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = out_dir / "predictions.jsonl"
    out_meta = out_dir / "predictions.meta.json"
    out_errors = out_dir / "predictions.errors.log"

    # Compute the pins once so the metadata block is self-describing.
    test_sample_sha = _sha256_of(TEST_SAMPLE_PATH)
    train_sha = _sha256_of(TRAIN_PATH)
    val_sha = _sha256_of(VAL_PATH)

    out_jsonl.unlink(missing_ok=True)
    out_errors.unlink(missing_ok=True)
    error_lines: list[str] = []
    records: list[dict[str, Any]] = []
    started = time.monotonic()

    for i, encounter in enumerate(encounters):
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
            "token_usage": {
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            },
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
            error_lines.append(f"--- {eid} ---\n{traceback.format_exc()}")
        except Exception as exc:  # noqa: BLE001
            record["error_type"] = type(exc).__name__
            record["error_message"] = f"{type(exc).__name__}: {exc}"
            error_lines.append(f"--- {eid} ---\n{traceback.format_exc()}")
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

    with out_jsonl.open("w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    out_errors.write_text("\n".join(error_lines))

    # Token totals (None for dry-run; 0 also means dry-run, by construction).
    total_prompt = sum((r["token_usage"]["prompt_tokens"] or 0) for r in records)
    total_completion = sum((r["token_usage"]["completion_tokens"] or 0) for r in records)
    total_tokens = sum((r["token_usage"]["total_tokens"] or 0) for r in records)

    meta = {
        "provider": args.provider,
        "provider_label": provider_label,
        "model": model_id,
        "mode": "dry-run" if args.dry_run else "real",
        "n_encounters": len(records),
        "n_ok": n_ok,
        "n_errors": n_err,
        "error_type_tally": error_tally,
        "wall_clock_seconds_total": total_wall,
        "wall_clock_seconds_avg": round(total_wall / max(len(records), 1), 4),
        "token_usage_total": {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_tokens,
        },
        "prompt_sha256": "sha256:" + hashlib.sha256(
            (PROJECT_ROOT / "src" / "ai_billing_audit" / "auditor_prompt.txt").read_bytes()
        ).hexdigest(),
        "test_sample_sha256": test_sample_sha,
        "train_json_sha256": train_sha,
        "val_json_sha256": val_sha,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "response_json_schema_keys": sorted(RESPONSE_JSON_SCHEMA["required"]),
    }
    out_meta.write_text(json.dumps(meta, indent=2) + "\n")

    print(
        f"[{provider_label}] wrote {len(records)} records to {out_jsonl} "
        f"({n_ok} ok, {n_err} errors, {total_wall:.3f}s total)"
    )
    if n_err:
        print(f"  errors: {error_tally}", file=sys.stderr)
    return 0 if n_err == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
