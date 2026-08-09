"""Tests for ``run_audit`` retry-on-empty path (2026-07-03 calibration fix).

The pinned model on Ollama Cloud (minimax-m3) returned zero findings
on a sample of AHCIP encounters in 2026-07-03 smoke tests where the
v12 recall run had previously caught SOMB issues. Root cause was a
calibration regression: the long prompt + JSON-schema envelope was
flipping the model into "summarize the encounter" mode rather than
"find billing issues" mode. The retry-on-empty path in ``run_audit``
appends a short follow-up user message that re-primes the model
into "find issues" mode without modifying the v12 prompt (which
would invalidate the v12 recall number).

These tests pin the retry contract:

1. When the first call returns findings, no retry happens
   (call count == 1).
2. When the first call returns zero findings AND the clinical_note
   is non-empty, one retry happens (call count == 2). If the
   retry returns findings, those are the result's findings.
3. When the first call returns zero findings AND the clinical_note
   is empty/whitespace, no retry happens (no signal to re-prompt
   on; the note is silent).
4. ``max_retries=0`` disables the retry even when the first call
   returns zero findings.
5. The retry preserves the system prompt and the original user
   message; the new content is appended as a third message with
   role="user" (not replacing any prior turn).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_billing_audit.auditor import RESPONSE_JSON_SCHEMA, run_audit  # noqa: E402
from ai_billing_audit.llm import LLMClient  # noqa: E402


class _ScriptedLLM:
    """Returns a queue of payloads, one per ``complete`` call.

    Records every call's (messages, kwargs) tuple so the test can
    assert on the retry-message append behavior.
    """

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = list(payloads)
        self.calls: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []

    def complete(
        self, *, messages: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append((list(messages), dict(kwargs)))
        if not self._payloads:
            raise AssertionError("ScriptedLLM exhausted; no payload left")
        # Simulate litellm/OpenAI response shape.
        return {
            "choices": [{"message": {"content": _json_dumps(self._payloads.pop(0))}}],
        }


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj)


def _encounter_with_note() -> dict[str, Any]:
    return {
        "encounter_id": "test-enc-001",
        "clinical_note": "65yo M, BP 152/94, A1c 8.9. Increased metformin.",
        "claim": {
            "som_b_codes": ["03.04A"],
            "diagnosis_codes": ["E11.9", "I10"],
            "modifier": "CMGP",
            "patient_health_number": "123456789",
            "date_of_service": "2026-05-15",
        },
    }


def _empty_note_encounter() -> dict[str, Any]:
    e = _encounter_with_note()
    e["clinical_note"] = ""
    return e


def _ws_only_note_encounter() -> dict[str, Any]:
    e = _encounter_with_note()
    e["clinical_note"] = "   \n\t  "
    return e


def test_no_retry_when_first_call_returns_findings():
    """Happy path: first call returns findings → no retry."""
    canned = {
        "findings": [
            {
                "rule_id": "rule_ahcip_em_level",
                "severity": "info",
                "category": "evaluation",
                "suggested_code": "03.04A",
                "quote": "BP 152/94",
                "explanation": "comprehensive visit for diabetes follow-up",
            }
        ],
        "summary": "ok",
    }
    fake = _ScriptedLLM([canned])
    client = LLMClient(complete=fake.complete)
    result = run_audit(_encounter_with_note(), llm=client, max_retries=1)
    assert len(result.findings) == 1
    assert fake.calls and len(fake.calls) == 1, "no retry expected"


def test_retry_triggers_on_zero_findings_with_non_empty_note():
    """Zero findings + non-empty note → one retry. If the retry
    returns findings, those are the result's findings."""
    retry_payload = {
        "findings": [
            {
                "rule_id": "rule_ahcip_cmgp",
                "severity": "high",
                "category": "modifier",
                "suggested_code": "03.04A",
                "quote": "BP 152/94",
                "explanation": "CMGP claimed with 03.04A — incompatible",
            }
        ],
        "summary": "ok on retry",
    }
    fake = _ScriptedLLM([{"findings": [], "summary": "no issues"}, retry_payload])
    client = LLMClient(complete=fake.complete)
    result = run_audit(_encounter_with_note(), llm=client, max_retries=1)
    assert len(fake.calls) == 2, "retry expected after empty first response"
    assert len(result.findings) == 1
    assert result.findings[0].rule_ids == ("rule_ahcip_cmgp",)
    assert result.summary == "ok on retry"


def test_no_retry_on_empty_clinical_note():
    """Empty note + zero findings → no retry (nothing to re-prompt on)."""
    fake = _ScriptedLLM([{"findings": [], "summary": "no note, no findings"}])
    client = LLMClient(complete=fake.complete)
    result = run_audit(_empty_note_encounter(), llm=client, max_retries=1)
    assert len(fake.calls) == 1, "no retry expected for empty note"
    assert not result.findings


def test_no_retry_on_whitespace_only_note():
    """Whitespace-only note behaves like empty: no retry."""
    fake = _ScriptedLLM([{"findings": [], "summary": "ws-only note"}])
    client = LLMClient(complete=fake.complete)
    result = run_audit(_ws_only_note_encounter(), llm=client, max_retries=1)
    assert len(fake.calls) == 1
    assert not result.findings


def test_max_retries_zero_disables_retry():
    """max_retries=0 short-circuits the retry branch entirely."""
    fake = _ScriptedLLM([{"findings": [], "summary": "first call only"}])
    client = LLMClient(complete=fake.complete)
    result = run_audit(_encounter_with_note(), llm=client, max_retries=0)
    assert len(fake.calls) == 1
    assert not result.findings


def test_retry_appends_user_message_not_replace():
    """The retry must APPEND a new user message to the conversation,
    not replace the original system or user message. The audit
    contract pins the system prompt as the v12 prompt verbatim; if
    the retry replaces it, the v12 recall number is invalidated."""
    retry_payload = {
        "findings": [
            {
                "rule_id": "rule_ahcip_dx_linkage",
                "severity": "high",
                "category": "documentation",
                "suggested_code": "E11.9",
                "quote": "BP 152/94",
                "explanation": "dx linkage check",
            }
        ],
        "summary": "after retry",
    }
    fake = _ScriptedLLM([{"findings": [], "summary": "no"}, retry_payload])
    client = LLMClient(complete=fake.complete)
    run_audit(_encounter_with_note(), llm=client, max_retries=1)

    # First call: system + user (2 messages).
    msgs1, kwargs1 = fake.calls[0]
    assert len(msgs1) == 2
    assert msgs1[0]["role"] == "system"
    assert msgs1[1]["role"] == "user"
    system_content_call_1 = msgs1[0]["content"]
    user_content_call_1 = msgs1[1]["content"]

    # Second call (retry): same system + same user + new user (3 messages).
    msgs2, kwargs2 = fake.calls[1]
    assert len(msgs2) == 3, "retry must append a user message"
    assert msgs2[0]["role"] == "system"
    assert msgs2[1]["role"] == "user"
    assert msgs2[2]["role"] == "user"
    assert msgs2[0]["content"] == system_content_call_1, "system prompt unchanged"
    assert msgs2[1]["content"] == user_content_call_1, "first user msg unchanged"
    # New message must mention SOMB / re-check so a reviewer reading
    # the prompt log understands why the model was re-prompted.
    assert "SOMB" in msgs2[2]["content"] or "Re-check" in msgs2[2]["content"]


def test_temperature_passed_through_to_provider():
    """run_audit passes temperature=0.2 to the provider (the
    deterministic-leaning default). If the temperature default is
    removed, this test fails loud so the calibration contract is
    visible in CI."""
    fake = _ScriptedLLM(
        [
            {"findings": [], "summary": "no"},
            {"findings": [], "summary": "no on retry"},
        ]
    )
    client = LLMClient(complete=fake.complete)
    run_audit(_encounter_with_note(), llm=client, max_retries=1)
    assert fake.calls[0][1].get("temperature") == 0.2, (
        "first call should use temperature=0.2 for deterministic recall"
    )
    assert fake.calls[1][1].get("temperature") == 0.2, (
        "retry should also use temperature=0.2"
    )


def test_response_format_passed_to_provider():
    """run_audit always wraps RESPONSE_JSON_SCHEMA in a constrained-
    decoding envelope. If a future refactor drops this, the model
    is unconstrained and may emit malformed JSON that fails
    validation downstream."""
    fake = _ScriptedLLM(
        [
            {
                "findings": [
                    {
                        "rule_id": "rule_ahcip_em_level",
                        "severity": "info",
                        "category": "evaluation",
                        "suggested_code": "03.04A",
                        "quote": "BP 152/94",
                        "explanation": "ok",
                    }
                ],
                "summary": "ok",
            }
        ]
    )
    client = LLMClient(complete=fake.complete)
    run_audit(_encounter_with_note(), llm=client, max_retries=1)
    sent_kwargs = fake.calls[0][1]
    rf = sent_kwargs.get("response_format")
    assert rf is not None
    # Must be the constrained json_schema envelope, not the legacy
    # unconstrained {"type": "json_object"}.
    assert rf.get("type") == "json_schema"
    assert "json_schema" in rf
    assert rf["json_schema"]["schema"] is RESPONSE_JSON_SCHEMA
