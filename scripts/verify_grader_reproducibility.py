"""Verify that the LLM-based grader is byte-identical reproducible.

Runs the grader twice on a fixed sample (predicted, ground_truth, context)
input and asserts that the two results are byte-identical. Uses a fake
LLM client so no API key or network access is required.

Exits 0 on a pass, 1 on a mismatch.

Usage
-----
    python scripts/verify_grader_reproducibility.py

The script is also self-checking: if anything is wrong (a non-deterministic
fake, a config that fails to load, a verdict that varies between calls),
it prints a clear error and exits with a non-zero status.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Make the package importable when run as a script from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.grader import Grader, GraderConfigError, GraderVerdict, load_grader_config


# ---------------------------------------------------------------------------
# Fake LLM client
# ---------------------------------------------------------------------------
#
# The fake implements the LLMClient interface (one method: ``complete``)
# with a *fixed* canned response. The fake MUST be deterministic — if the
# canned response varies between calls, the test cannot detect a real
# grader regression. We also wrap the fake in a counter so the test can
# assert that the grader actually called the LLM (i.e. it didn't short-
# circuit on a cached or hard-coded value).
class FakeLLM:
    """Deterministic fake LLM client that records call count and messages.

    The same ``messages`` and kwargs always produce the same canned
    response. We intentionally do NOT vary the response on call number
    or any other input — that would defeat the whole point of this
    test (we want to verify the grader's plumbing, not its model).
    """

    def __init__(self, canned_response: str) -> None:
        self._canned_response = canned_response
        self.call_count = 0
        self.last_messages = None
        self.last_kwargs = None

    def complete(self, messages, **kwargs):
        self.call_count += 1
        self.last_messages = messages
        self.last_kwargs = kwargs
        return {
            "choices": [{"message": {"content": self._canned_response}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


def _fixed_sample() -> dict:
    """A single, fixed (predicted, ground_truth, context) sample for reproducibility checks."""
    return {
        "predicted": {
            "category": "missing_dx",
            "suggested_code": "R00.2",
            "clinical_evidence_quote": (
                "Palpitations reported. ECG performed in office shows "
                "normal sinus rhythm with isolated PACs."
            ),
            "severity": "medium",
            "rule_ids": ["rule_ecg_palpitations_missing_r002"],
        },
        "ground_truth": {
            "category": "missing_dx",
            "suggested_code": "R00.2",
            "clinical_evidence_quote": (
                "Palpitations reported. ECG performed in office shows "
                "normal sinus rhythm with isolated PACs."
            ),
            "severity": "medium",
            "rule_ids": ["rule_ecg_palpitations_missing_r002"],
        },
        "context": "encounter_id: enc-001\nis_flagged: True",
    }


def _canned_response() -> str:
    """A realistic canned response that conforms to the verdict schema."""
    return json.dumps(
        {
            "verdict": "match",
            "score": 1.0,
            "rationale": (
                "Category, suggested_code, and clinical_evidence_quote all match "
                "the ground-truth finding. Verdict: match."
            ),
        }
    )


def _bytes_of(v: GraderVerdict) -> bytes:
    """Canonical byte representation of a verdict for strict comparison.

    ``as_dict()`` already returns keys in a fixed order, and we round the
    score to 6 decimal places to avoid floating-point representation
    drift. ``json.dumps`` with ``sort_keys=False`` (default) preserves
    the order from ``as_dict()`` and uses no whitespace.
    """
    return json.dumps(v.as_dict(), ensure_ascii=False).encode("utf-8")


def main() -> int:
    sample = _fixed_sample()
    canned = _canned_response()

    # 1. Load the config (this is the artifact the task is shipping).
    try:
        config = load_grader_config()
    except GraderConfigError as e:
        print(f"FAIL: could not load grader config: {e}", file=sys.stderr)
        return 1
    judge = config["judge"]
    if float(judge["temperature"]) != 0.0:
        print(
            f"FAIL: judge.temperature is {judge['temperature']!r}, expected 0.0",
            file=sys.stderr,
        )
        return 1
    if int(judge["seed"]) != 42:
        print(
            f"FAIL: judge.seed is {judge['seed']!r}, expected 42", file=sys.stderr
        )
        return 1
    print(
        "OK: grader config loaded — "
        f"model={judge['model']!r}, temperature={judge['temperature']!r}, "
        f"seed={judge['seed']!r}"
    )

    # 2. Build a fresh grader with a fake LLM, run the grade twice.
    fake1 = FakeLLM(canned)
    grader1 = Grader(llm=fake1)
    verdict1 = grader1.grade(
        sample["predicted"],
        sample["ground_truth"],
        context=sample["context"],
    )

    fake2 = FakeLLM(canned)
    grader2 = Grader(llm=fake2)
    verdict2 = grader2.grade(
        sample["predicted"],
        sample["ground_truth"],
        context=sample["context"],
    )

    # 3. Byte-identical comparison.
    bytes1 = _bytes_of(verdict1)
    bytes2 = _bytes_of(verdict2)
    if bytes1 != bytes2:
        print("FAIL: grader produced different output on the same input", file=sys.stderr)
        print(f"  run 1: {bytes1!r}", file=sys.stderr)
        print(f"  run 2: {bytes2!r}", file=sys.stderr)
        return 1
    print(f"OK: two runs produced byte-identical output ({bytes1.decode('utf-8')})")

    # 4. Sanity: the grader actually called the LLM (no short-circuit).
    if fake1.call_count != 1 or fake2.call_count != 1:
        print(
            f"FAIL: grader did not call the LLM exactly once per run "
            f"(fake1.call_count={fake1.call_count}, fake2.call_count={fake2.call_count})",
            file=sys.stderr,
        )
        return 1
    print("OK: grader called the LLM exactly once per run")

    # 5. Sanity: the messages sent to the LLM are byte-identical.
    msgs1 = json.dumps(fake1.last_messages, sort_keys=True, ensure_ascii=False)
    msgs2 = json.dumps(fake2.last_messages, sort_keys=True, ensure_ascii=False)
    if msgs1 != msgs2:
        print("FAIL: messages sent to the LLM differ between runs", file=sys.stderr)
        return 1
    print("OK: messages sent to the LLM are byte-identical")

    # 6. Sanity: the kwargs (model/temperature/seed) are byte-identical.
    kw1 = json.dumps(fake1.last_kwargs, sort_keys=True, ensure_ascii=False)
    kw2 = json.dumps(fake2.last_kwargs, sort_keys=True, ensure_ascii=False)
    if kw1 != kw2:
        print("FAIL: LLM kwargs differ between runs", file=sys.stderr)
        return 1
    if float(fake1.last_kwargs.get("temperature", -1)) != 0.0:
        print(
            f"FAIL: LLM kwargs temperature is {fake1.last_kwargs.get('temperature')!r}, "
            f"expected 0.0",
            file=sys.stderr,
        )
        return 1
    if int(fake1.last_kwargs.get("seed", -1)) != 42:
        print(
            f"FAIL: LLM kwargs seed is {fake1.last_kwargs.get('seed')!r}, expected 42",
            file=sys.stderr,
        )
        return 1
    print(
        f"OK: LLM kwargs are byte-identical and include "
        f"temperature={fake1.last_kwargs['temperature']!r}, "
        f"seed={fake1.last_kwargs['seed']!r}"
    )

    print("\nAll reproducibility checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
