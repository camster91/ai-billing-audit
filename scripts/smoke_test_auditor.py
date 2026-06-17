"""Smoke test: verify the v0 Auditor runs end-to-end on 1 encounter.

This is the v0 baseline acceptance check (task t_1400da1f, step 3):
the auditor's inference interface must accept a single encounter from
the v0 test split, dispatch a chat completion, parse the response
through the findings schema, and return a typed AuditResult.

The test uses a FakeLLM that returns a canned valid response (one
finding matching the encounter's first ground-truth rule). It asserts:

  * ``run_audit`` returns an ``AuditResult`` instance
  * the encounter_id round-trips
  * the findings list is non-empty (the canned response has 1)
  * each finding has all five required fields populated
  * the LLM was called with the v0 system prompt as the system message
  * the user message renders the encounter's clinical_note
  * validate_findings on the raw response succeeds (i.e. the
    RESPONSE_JSON_SCHEMA shape is parseable end-to-end)

Usage:
    python scripts/smoke_test_auditor.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.auditor import (  # noqa: E402
    RESPONSE_JSON_SCHEMA,
    AuditResult,
    Finding,
    build_messages,
    load_prompt,
    run_audit,
    validate_findings,
)
from ai_billing_audit.llm import LLMClient  # noqa: E402


CANNED_FINDING = {
    "category": "cardiology",
    "suggested_code": "93000",
    "quote": "ECG performed in office",
    "severity": "medium",
    "rule_ids": ["rule_ecg_001"],
}


class FakeLLM:
    """Deterministic LLMClient double that returns one canned finding.

    Implements the structural LLMClient Protocol (the two methods the
    rest of the package calls: ``complete`` and ``complete_json``).
    The canned response is valid against RESPONSE_JSON_SCHEMA so
    ``run_audit`` should accept it without raising.
    """

    def __init__(self, canned_payload: dict) -> None:
        self._canned = canned_payload
        self.calls: list[tuple] = []

    def complete(self, messages, **kwargs):  # noqa: ANN001, ANN201
        self.calls.append((messages, kwargs))
        return {
            "choices": [{"message": {"content": json.dumps(self._canned)}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    def complete_json(self, messages, json_schema, **kwargs):  # noqa: ANN001, ANN201
        response = self.complete(messages, response_format=json_schema, **kwargs)
        return json.loads(response["choices"][0]["message"]["content"])


def _build_canned_response(encounter: dict) -> dict:
    """Build a one-finding canned response grounded in the encounter.

    The finding's quote is chosen to be a real substring of the
    encounter's clinical_note (the smoke test asserts that).
    """
    quote = "ECG performed in office"
    assert quote in encounter["clinical_note"], (
        f"smoke test quote not present in clinical_note: {quote!r}"
    )
    return {"summary": "Smoke test encounter.", "findings": [dict(CANNED_FINDING)]}


def _assert_schema_round_trip() -> None:
    """validate_findings must accept the canned response shape.

    Catches drift between RESPONSE_JSON_SCHEMA and Finding.
    """
    findings = validate_findings(_build_canned_response({"clinical_note": quote_holder()}))
    assert len(findings) == 1, f"expected 1 finding, got {len(findings)}"
    f = findings[0]
    assert isinstance(f, Finding), f"expected Finding, got {type(f).__name__}"
    for key in ("category", "suggested_code", "quote", "severity"):
        assert getattr(f, key), f"finding.{key} is empty"
    assert f.rule_ids == ("rule_ecg_001",), f"unexpected rule_ids: {f.rule_ids}"


def quote_holder() -> str:  # local helper to keep the assert above clean
    return "ECG performed in office. New patient low complexity."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--val",
        type=Path,
        default=PROJECT_ROOT / "data" / "val.json",
        help="Path to the val.json test split.",
    )
    parser.add_argument(
        "--pinned-prompt",
        type=Path,
        default=PROJECT_ROOT / "prompts" / "v0" / "auditor_prompt.txt",
        help="Path to the v0 pinned prompt (must match src/ byte-for-byte).",
    )
    args = parser.parse_args()

    # 1) v0 pin matches the bundled copy. Refuse to run otherwise.
    # Both files end in "\n"; load_prompt() does an .rstrip("\n") at
    # load time, so the in-memory comparison below normalises that too.
    bundled = (PROJECT_ROOT / "src" / "ai_billing_audit" / "auditor_prompt.txt").read_bytes()
    pinned = args.pinned_prompt.read_bytes()
    assert bundled == pinned, (
        f"v0 pin at {args.pinned_prompt} does not match the bundled "
        f"src/ copy. Refusing to run the smoke test against a stale pin."
    )
    bundled_normalised = bundled.rstrip(b"\n").decode("utf-8")

    # 2) Round-trip the schema end-to-end (catches Finding/JSON drift).
    _assert_schema_round_trip()

    # 3) Load the first encounter from the v0 test split.
    with open(args.val, "r", encoding="utf-8") as f:
        val = json.load(f)
    assert len(val) == 50, f"expected 50 val encounters, got {len(val)}"
    encounter = val[0]
    assert encounter["encounter_id"] == "enc_10000", (
        f"first val encounter id is {encounter['encounter_id']!r}, "
        f"expected 'enc_10000' (test split may have been regenerated)"
    )

    # 4) The canned response must use a quote from this encounter.
    canned_payload = _build_canned_response(encounter)

    # 5) Dispatch through run_audit with the pinned v0 prompt.
    fake = FakeLLM(canned_payload)
    client = LLMClient(complete=fake.complete)
    result = run_audit(encounter, llm=client, prompt_path=args.pinned_prompt)

    # 6) Verify the LLM saw the v0 system prompt and the encounter context.
    assert len(fake.calls) == 1, f"expected 1 LLM call, got {len(fake.calls)}"
    sent_messages, sent_kwargs = fake.calls[0]
    system_msg = sent_messages[0]
    user_msg = sent_messages[1]
    assert system_msg["role"] == "system", system_msg
    assert system_msg["content"] == bundled_normalised, (
        "LLM did not receive the v0 system prompt verbatim"
    )
    assert "response_format" in sent_kwargs, (
        f"run_audit must pass response_format to the LLM, "
        f"kwargs were {list(sent_kwargs.keys())}"
    )
    assert sent_kwargs["response_format"] is RESPONSE_JSON_SCHEMA
    assert encounter["clinical_note"] in user_msg["content"], (
        "user message did not include the encounter's clinical_note"
    )
    assert user_msg["content"].lstrip().startswith("encounter_id:"), (
        "user message did not render the encounter context header"
    )

    # 7) The returned AuditResult must be the typed shape.
    assert isinstance(result, AuditResult)
    assert result.encounter_id == "enc_10000"
    assert result.summary == canned_payload["summary"]
    assert len(result.findings) == 1
    f = result.findings[0]
    assert isinstance(f, Finding)
    assert f.category == "cardiology"
    assert f.suggested_code == "93000"
    assert f.quote == "ECG performed in office"
    assert f.severity == "medium"
    assert f.rule_ids == ("rule_ecg_001",)

    # 8) build_messages on the same inputs reproduces the same shape
    # (pure-function sanity check; cheap but catches regressions).
    prompt = load_prompt(args.pinned_prompt)
    msgs = build_messages(encounter, prompt=prompt)
    assert msgs[0] == system_msg
    assert msgs[1] == user_msg

    print("[smoke_test_auditor] OK")
    print(f"  pinned prompt : {args.pinned_prompt}")
    print(f"  val split     : {args.val} (50 encounters)")
    print(f"  encounter_id  : {result.encounter_id}")
    print(f"  findings      : {len(result.findings)}")
    print(f"  summary       : {result.summary!r}")
    print(f"  schema keys   : {sorted(RESPONSE_JSON_SCHEMA['required'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
