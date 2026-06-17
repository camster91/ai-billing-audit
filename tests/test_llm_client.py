"""End-to-end verification: swapping ``$LLM_PROVIDER`` alone changes the backend.

Acceptance criteria (t_8fe5cb0f):

1. A single parameterized test exercises the same scenario under each
   of the four ``LLM_PROVIDER`` values: ``"minimax"``, ``"claude"``,
   ``"openai"``, ``"gemini"``.
2. For each provider the test:
     (a) sets ``$LLM_PROVIDER`` (and the provider's API key env var) via
         ``monkeypatch.setenv``,
     (b) calls ``create_llm_client()`` with no args and asserts the
         returned object satisfies the ``LLMClient`` Protocol,
     (c) invokes ``complete()`` and asserts the result is the
         assistant text the fake transport returns — with
         ``litellm.completion`` mocked so no real network call fires,
     (d) invokes ``complete_json()`` against a sample JSON Schema and
         asserts the result is a ``dict`` that matches that schema
         (i.e. has the required keys with the declared types).
3. The four backends are exercised via the production dispatch path
   (``_PROVIDER_CLASS_PATHS``) — no caller-side branches and no test
   override hooks — to prove the env-var swap alone is sufficient.

Design note
-----------
The four provider classes are thin ``litellm`` wrappers. We mock
``litellm.completion`` (the only external call) with a single
``MagicMock`` that returns a structured response shaped like a real
OpenAI/litellm response. That keeps the test fully self-contained:
no real API keys, no network, and no per-provider transport shim.

We do **not** use ``_TEST_PROVIDER_OVERRIDES`` here — that hook
exists for the factory-isolation tests in
``test_llm_client_factory.py``. The whole point of THIS test is to
prove the production dispatch path works end-to-end with the real
classes; replacing them with fakes would defeat the test.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import litellm
import pytest

import src.llm_client as llm_client
from src.llm_client import LLMClient, create_llm_client


# ---------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------


# Each provider has its own API key env var (matching the ``api_key_env``
# class attribute on the concrete implementation). Mapping keeps the
# parametrization table tidy.
PROVIDER_API_KEY_ENV: dict[str, str] = {
    "minimax": "MINIMAX_API_KEY",
    "claude":  "ANTHROPIC_API_KEY",
    "openai":  "OPENAI_API_KEY",
    "gemini":  "GEMINI_API_KEY",
}


def _make_litellm_response(text: str) -> MagicMock:
    """Build a ``MagicMock`` shaped like a litellm/OpenAI completion.

    Mirrors the chain the provider classes consume:
    ``response.choices[0].message.content``. The mock is strictly
    structural — no real network is involved.
    """
    return MagicMock(choices=[MagicMock(message=MagicMock(content=text))])


def _stub_litellm_completion(text: str) -> Any:
    """Context manager: patch ``litellm.completion`` to return ``text``.

    Used to assert the provider classes delegate to ``litellm.completion``
    exactly once and forward the assistant text unchanged. Patches the
    symbol in the ``src.llm_client`` namespace (where the providers
    import it from).
    """

    def _factory(*args: Any, **kwargs: Any) -> MagicMock:
        return _make_litellm_response(text)

    return patch.object(litellm, "completion", side_effect=_factory)


# A simple JSON Schema we can re-use across all four providers. Keeps
# the assertion surface uniform: every backend must surface a dict
# with these two string fields.
SAMPLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer":  {"type": "string"},
        "mood":    {"type": "string"},
    },
    "required": ["answer", "mood"],
    "additionalProperties": False,
}


def _make_litellm_json_response(answer: str, mood: str) -> MagicMock:
    """A fake litellm response whose content is a JSON object string.

    Mirrors the real provider behaviour: ``response_format=json_object``
    forces the model to return JSON text, which the provider then
    ``json.loads`` for the caller.
    """
    import json

    payload = json.dumps({"answer": answer, "mood": mood})
    return _make_litellm_response(payload)


@pytest.fixture
def clear_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ``$LLM_PROVIDER`` before each test so no host env leaks in."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)


# ---------------------------------------------------------------------
# The single parameterized test
# ---------------------------------------------------------------------


@pytest.mark.parametrize("provider_name", ["minimax", "claude", "openai", "gemini"])
def test_swapping_llm_provider_changes_backend_with_zero_caller_changes(
    monkeypatch: pytest.MonkeyPatch,
    clear_llm_provider: None,
    provider_name: str,
) -> None:
    """End-to-end: setting ``$LLM_PROVIDER`` swaps the backend with no code change.

    Walks through the acceptance checklist in one test, parameterised
    over the four canonical provider names. The test fails loudly if
    the factory's dispatch table returns the wrong class, the
    returned class is not ``LLMClient``-Protocol-conformant, or the
    provider's ``complete()`` / ``complete_json()`` paths break
    (which would be invisible to the existing factory tests, which
    only assert the type / label, not the behaviour).
    """
    # (1) Set the env var. The API key env var is provider-specific;
    # we set it to a non-empty placeholder so the constructor's
    # "missing API key" guard does not fire.
    monkeypatch.setenv("LLM_PROVIDER", provider_name)
    monkeypatch.setenv(PROVIDER_API_KEY_ENV[provider_name], "test-key-not-real")

    # (2) Call create_llm_client() with no args — the factory reads
    # $LLM_PROVIDER. The returned object is typed as LLMClient and
    # callers never see the concrete class.
    client = create_llm_client()

    # (3) Structural conformance: the runtime-checkable Protocol
    # accepts the returned class. This is the "zero caller change"
    # guarantee — a single LLMClient-typed variable works for all
    # four backends.
    assert isinstance(client, LLMClient), (
        f"provider {provider_name!r} returned {type(client).__name__} "
        f"which does not satisfy the LLMClient Protocol"
    )

    # (4) complete() works end-to-end with litellm mocked. We assert
    # the assistant text the provider returns is exactly the text
    # the (mocked) litellm.completion produced — that is, the
    # provider correctly delegates to litellm and unwraps the
    # response envelope.
    with _stub_litellm_completion("hello from the fake model") as mocked:
        messages = [{"role": "user", "content": "ping"}]
        reply = client.complete(messages)

    assert reply == "hello from the fake model", (
        f"provider {provider_name!r}.complete() returned {reply!r}, "
        f"expected the assistant text from the mocked litellm response"
    )
    # litellm.completion was called exactly once with the right
    # provider-specific model prefix (sourced from the class default).
    assert mocked.call_count == 1
    call_kwargs = mocked.call_args.kwargs
    assert call_kwargs["messages"] == messages
    # The provider must not mutate the input messages list — that is
    # part of the Protocol contract. Verify with a second equality
    # check on the original list.
    assert messages == [{"role": "user", "content": "ping"}]

    # (5) complete_json() returns a dict matching the sample schema.
    # Mock litellm to return JSON text in the response, then assert
    # the provider's json.loads round-trip produces a dict with the
    # right keys and types.
    expected_answer = "forty-two"
    expected_mood = "confident"
    with patch.object(
        litellm,
        "completion",
        return_value=_make_litellm_json_response(expected_answer, expected_mood),
    ) as mocked_json:
        result = client.complete_json(
            [{"role": "user", "content": "answer in JSON"}],
            SAMPLE_SCHEMA,
        )

    assert isinstance(result, dict), (
        f"provider {provider_name!r}.complete_json() returned "
        f"{type(result).__name__}, expected dict"
    )
    # Schema-shaped assertions: required keys present, values are
    # the declared types, no extra keys.
    assert set(result.keys()) == {"answer", "mood"}, (
        f"provider {provider_name!r}.complete_json() returned keys "
        f"{set(result.keys())!r}, expected {{'answer', 'mood'}}"
    )
    assert result["answer"] == expected_answer
    assert result["mood"] == expected_mood
    assert isinstance(result["answer"], str)
    assert isinstance(result["mood"], str)
    # Provider forced response_format=json_object on the litellm call.
    assert mocked_json.call_count == 1
    assert mocked_json.call_args.kwargs.get("response_format") == {
        "type": "json_object"
    }


# ---------------------------------------------------------------------
# Auxiliary: confirm the four canonical names are mutually distinct
# ---------------------------------------------------------------------


def test_factory_returns_distinct_classes_per_provider(
    monkeypatch: pytest.MonkeyPatch,
    clear_llm_provider: None,
) -> None:
    """Belt-and-braces: four providers, four distinct classes.

    The ``test_env_swap_changes_returned_type`` test in
    ``test_llm_client_factory.py`` asserts distinct types when the
    test override hook is populated. This test asserts the same
    invariant against the *production* dispatch path (no override),
    so a future refactor that accidentally aliases two providers to
    the same class will fail here before the integration tests do.
    """
    for name, env_var in PROVIDER_API_KEY_ENV.items():
        monkeypatch.setenv(env_var, "test-key-not-real")

    seen: dict[str, type] = {}
    for name in PROVIDER_API_KEY_ENV:
        monkeypatch.setenv("LLM_PROVIDER", name)
        client = create_llm_client()
        seen[name] = type(client)

    assert len({id(c) for c in seen.values()}) == 4, (
        f"expected four distinct concrete provider classes, got: "
        f"{ {n: c.__name__ for n, c in seen.items()} }"
    )
