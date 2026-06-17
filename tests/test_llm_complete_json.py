"""Smoke tests for ``ai_billing_audit.llm.LLMClient.complete_json``.

This is the test that should have existed from day one and didn't. It
exercises the public ``complete_json`` contract with three canned
backend responses:

  1. Conforming JSON that matches the schema  -> success, dict returned.
  2. Non-conforming JSON (right shape, wrong values) -> SchemaValidationError.
  3. Malformed JSON (text the backend returned, not even parseable) -> JSONDecodeError.

Each test injects a ``complete=`` callable into ``LLMClient`` so no real
network call is made. The test is hermetic and runs in well under a
second.

This file ships as part of the fix for kanban review task t_3ebd3694
("Code review: src/llm.py + minimax_client.py + minimax_errors.py"),
finding #3 in the report: the old layer's ``complete_json`` had zero
smoke test coverage and the new layer's smoke hid the validation gap by
faking conforming JSON.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ai_billing_audit.llm import LLMClient, SchemaValidationError


# A simple JSON Schema with a required key, an enum constraint, and
# additionalProperties=False. Lets us assert both the "happy path"
# (conforming) and the "model lied" path (non-conforming but parseable)
# with a single fixture.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "mood": {"type": "string", "enum": ["happy", "sad"]},
    },
    "required": ["answer", "mood"],
    "additionalProperties": False,
}


def _make_complete(text: str):
    """Build a fake ``complete`` callable that returns a litellm-shaped
    response with ``text`` as the assistant content.

    Mirrors the response shape the production ``_default_complete`` (a
    closure over ``litellm.completion``) returns, which is the OpenAI
    chat-completion envelope: ``{"choices": [{"message": {"content":
    <str>}}]}``.
    """
    return lambda *, messages, **kwargs: {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_complete_json_returns_parsed_dict_when_response_conforms() -> None:
    """Happy path: the model returned a JSON string that matches the schema."""
    payload = json.dumps({"answer": "pong", "mood": "happy"})
    client = LLMClient(complete=_make_complete(payload))

    result = client.complete_json(
        [{"role": "user", "content": "Reply with JSON."}],
        SCHEMA,
    )

    assert result == {"answer": "pong", "mood": "happy"}


def test_complete_json_raises_on_nonconforming_response() -> None:
    """The model returned a parseable JSON object that violates the schema.

    This is the failure mode the new validation guards against: the
    shape is JSON, the values are not the declared types/enum. Without
    the ``jsonschema.validate`` call in ``complete_json`` the bad dict
    would escape to the caller and surface as a downstream
    ``KeyError`` / ``TypeError`` somewhere else.
    """
    # Right keys, wrong enum value for ``mood``.
    payload = json.dumps({"answer": "pong", "mood": "confused"})
    client = LLMClient(complete=_make_complete(payload))

    with pytest.raises(SchemaValidationError) as excinfo:
        client.complete_json(
            [{"role": "user", "content": "Reply with JSON."}],
            SCHEMA,
        )

    # The error message should make it obvious what failed. We don't
    # pin the exact wording (jsonschema's message format is library-
    # version-sensitive) but we do pin the leading clause so a future
    # refactor that drops the prefix would fail this test.
    assert "did not conform" in str(excinfo.value)


def test_complete_json_raises_on_additional_property() -> None:
    """A model that adds an undeclared key is also rejected.

    This exercises the ``additionalProperties: False`` branch of the
    schema, which is the most common real-world failure: the model
    invents a field the downstream code didn't expect.
    """
    payload = json.dumps({"answer": "pong", "mood": "happy", "sneaky": "extra"})
    client = LLMClient(complete=_make_complete(payload))

    with pytest.raises(SchemaValidationError):
        client.complete_json(
            [{"role": "user", "content": "Reply with JSON."}],
            SCHEMA,
        )


def test_complete_json_raises_on_missing_required_key() -> None:
    """A model that drops a required key is rejected.

    The other half of the conformance contract: the schema says
    ``required: [answer, mood]``, and the model's response has only
    one. The downstream code would crash with ``KeyError`` on the
    missing key; the layer catches it here instead.
    """
    payload = json.dumps({"answer": "pong"})  # missing ``mood``
    client = LLMClient(complete=_make_complete(payload))

    with pytest.raises(SchemaValidationError):
        client.complete_json(
            [{"role": "user", "content": "Reply with JSON."}],
            SCHEMA,
        )


def test_complete_json_raises_on_malformed_json() -> None:
    """If the backend returns text that isn't even JSON, the layer raises.

    This is a different failure mode from non-conformance: the text
    fails at the ``json.loads`` step before validation ever runs. The
    caller should still get a loud failure (a ``json.JSONDecodeError``
    propagating up), not a silent empty dict.
    """
    client = LLMClient(complete=_make_complete("not json at all"))

    with pytest.raises(json.JSONDecodeError):
        client.complete_json(
            [{"role": "user", "content": "Reply with JSON."}],
            SCHEMA,
        )


def test_complete_json_legacy_envelope_skips_validation() -> None:
    """The legacy ``{"type": "json_object"}`` envelope skips local validation.

    When the caller passes a bare envelope instead of a real JSON
    Schema, there's nothing to validate against. The layer falls
    through to the legacy behaviour (forward the envelope, json.loads,
    return) so existing call sites that pass the legacy shape keep
    working. This is the contract the auditor.py smoke harness relies
    on.
    """
    legacy_envelope = {"type": "json_object"}
    payload = json.dumps({"anything": "goes", "including": "untyped keys"})
    client = LLMClient(complete=_make_complete(payload))

    result = client.complete_json(
        [{"role": "user", "content": "Reply with JSON."}],
        legacy_envelope,
    )

    assert result == {"anything": "goes", "including": "untyped keys"}


def test_llm_client_construction_rejects_invalid_timeout() -> None:
    """A non-positive timeout is a programming error and must fail fast.

    The new ``timeout=`` parameter added by the fix defaults to 60s
    but accepts ``None`` ("wait forever") or any positive float. A
    negative or zero timeout would let a hung connection sit for
    nothing, which is worse than no timeout at all.
    """
    with pytest.raises(ValueError, match="timeout must be a positive"):
        LLMClient(timeout=0)
    with pytest.raises(ValueError, match="timeout must be a positive"):
        LLMClient(timeout=-1.0)
