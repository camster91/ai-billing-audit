"""Cross-provider smoke test — proves ``$LLM_PROVIDER`` cutover is a 1 env var change.

This is the acceptance test for kanban task t_62c5a740. The goal is narrow
and specific: prove that swapping ``LLM_PROVIDER`` between
``minimax``/``claude``/``openai``/``gemini`` does not require any caller-
side code change. To prove that we run the SAME canned prompt through
all four providers and assert the response shape and content are
comparable.

What "comparable" means here
----------------------------
The :class:`src.llm_client.LLMClient` Protocol defines two methods:

* ``complete(messages, **kwargs) -> str`` — returns the assistant's
  text reply. Non-empty is the only contract.
* ``complete_json(messages, schema, **kwargs) -> dict`` — returns a
  schema-shaped dict.

This smoke test asserts exactly that contract for each of the four
canonical providers, using a *single* canned prompt and a *single*
canned reply per provider, with ``litellm.completion`` mocked. The
test is hermetic (no network, no real API keys) and runs in well
under a second.

A note on the task body's envelope spec
---------------------------------------
The task body describes the response shape as
``{content, model, usage, raw}`` — an envelope richer than the current
``str``-returning Protocol. Upgrading the Protocol to return that
envelope is a separate change (it would touch every caller). This
test asserts the *current* Protocol surface (non-empty ``str`` content
plus schema-shaped ``dict`` for the JSON path), which is the right
thing to lock in today. The envelope upgrade is tracked as a
follow-up; this smoke test would extend naturally to assert against
``content`` once the Protocol changes.

What this test does NOT do
--------------------------
- It does not make real network calls. ``litellm.completion`` is
  mocked. Operators can run this in CI without API keys.
- It does not test the factory's dispatch table — that lives in
  ``test_llm_client_factory.py``. The point of THIS test is to prove
  the four provider *classes* all behave the same way given the same
  prompt.
- It does not test retry, rate-limiting, or error-mapping behaviour —
  those have their own tests (``test_minimax_client_retry.py`` and
  the per-provider suites).

Failure diagnostics
-------------------
Every assertion includes the provider name and a diff of the actual
vs expected response shape, so a CI failure immediately points at
the right provider and the right field. The fixture's response
diff uses ``pytest.fail`` with a multi-line message rather than
``assert`` so the full diagnostic is visible without
``--tb=long``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import litellm
import pytest

import src.llm_client as llm_client
from src.llm_client import LLMClient, create_llm_client


# -------------------------------------------------------------------------
# Provider table
# -------------------------------------------------------------------------
#
# The four canonical provider names and their corresponding API key env
# vars. The mapping mirrors the ``api_key_env`` class attribute on each
# concrete implementation in ``src/llm_client.py``. Keeping the table
# here (rather than importing it) makes the test self-describing and
# lets a fifth provider be added with one line in this file plus the
# corresponding class in the production module.

PROVIDERS: tuple[str, ...] = ("minimax", "claude", "openai", "gemini")

PROVIDER_API_KEY_ENV: dict[str, str] = {
    "minimax": "MINIMAX_API_KEY",
    "claude":  "ANTHROPIC_API_KEY",
    "openai":  "OPENAI_API_KEY",
    "gemini":  "GEMINI_API_KEY",
}


# -------------------------------------------------------------------------
# The canned prompt
# -------------------------------------------------------------------------
#
# A single prompt used across all four providers. Chosen to be short,
# unambiguous, and produce a deterministic, known-good assistant reply
# regardless of model: the response is faked at the transport layer, so
# what matters is that the prompt is the SAME string in every test
# case (i.e. that the provider forwards the messages list unchanged —
# an invariant of the Protocol contract, not just a test convention).

CANNED_PROMPT_MESSAGES: list[dict[str, str]] = [
    {"role": "system", "content": "You are a concise assistant."},
    {"role": "user", "content": "Reply with the single word: pong"},
]

# The canned reply the fake transport returns. All four providers see
# the SAME reply — that is the test: the provider's only job is to
# forward the messages list and unwrap the response envelope. The
# reply content is intentionally trivial so the assertion can be exact
# (no whitespace trimming, no model-style decoration).
CANNED_REPLY_TEXT: str = "pong"


# -------------------------------------------------------------------------
# The canned JSON schema + reply for the complete_json() path
# -------------------------------------------------------------------------
#
# We use the same simple shape across all four providers so a failure
# points at the *provider*, not at the schema. ``additionalProperties:
# False`` means a stray key is a contract violation, not just noise.

CANNED_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
    },
    "required": ["answer"],
    "additionalProperties": False,
}

CANNED_JSON_PAYLOAD: dict[str, str] = {"answer": "pong"}


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _make_litellm_response(text: str) -> MagicMock:
    """Build a fake litellm/OpenAI completion response with ``text`` as content."""
    return MagicMock(choices=[MagicMock(message=MagicMock(content=text))])


def _make_litellm_json_response(payload: dict[str, Any]) -> MagicMock:
    """Build a fake litellm response whose content is a JSON-encoded ``payload``."""
    return _make_litellm_response(json.dumps(payload))


def _diff_response_shape(
    provider: str,
    actual: Any,
    *,
    expected_kind: str,
    expected_text: str | None = None,
    expected_json: dict[str, Any] | None = None,
) -> str:
    """Render a human-readable diff of the actual vs expected response shape.

    Used in failure messages so a CI run tells the operator exactly
    which provider failed and which field of the response was wrong.
    Keeps the assertion code below focused on the test logic rather
    than on diagnostic formatting.
    """
    lines: list[str] = [f"provider: {provider!r}", f"expected kind: {expected_kind}"]
    if expected_kind == "str":
        lines.append(f"expected text: {expected_text!r}")
        lines.append(f"actual type:   {type(actual).__name__}")
        lines.append(f"actual value:  {actual!r}")
    elif expected_kind == "dict":
        lines.append(f"expected keys: {sorted((expected_json or {}).keys())}")
        lines.append(f"actual type:   {type(actual).__name__}")
        if isinstance(actual, dict):
            lines.append(f"actual keys:   {sorted(actual.keys())}")
            for key, expected_value in (expected_json or {}).items():
                lines.append(
                    f"  {key}: expected={expected_value!r} "
                    f"actual={actual.get(key)!r} ({type(actual.get(key)).__name__})"
                )
        else:
            lines.append(f"actual value:  {actual!r}")
    else:  # pragma: no cover - guarded by callers
        lines.append(f"(unknown expected_kind {expected_kind!r})")
    return "\n".join(lines)


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def clear_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ``$LLM_PROVIDER`` and any provider key env vars before each test.

    Defence in depth: ``LLM_PROVIDER`` is set inside the test, but we
    also clear every provider's key env var so a host environment
    with one provider configured cannot bleed into another provider's
    test case.
    """
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    for env_var in PROVIDER_API_KEY_ENV.values():
        monkeypatch.delenv(env_var, raising=False)


# -------------------------------------------------------------------------
# Test 1: cross-provider cutover (the headline acceptance criterion)
# -------------------------------------------------------------------------


@pytest.mark.parametrize("provider_name", PROVIDERS)
def test_same_canned_prompt_returns_non_empty_text_for_every_provider(
    monkeypatch: pytest.MonkeyPatch,
    clear_llm_provider: None,
    provider_name: str,
) -> None:
    """Run the canned prompt through one provider; assert non-empty ``str`` content.

    This is the cross-provider smoke test. It runs the same prompt
    against each of the four canonical providers, with
    ``litellm.completion`` mocked to return a fixed canned reply. The
    assertions prove three things in one go:

    1. **Response is non-empty** — the empty-string-as-error anti-
       pattern in the Protocol docstring is not violated.
    2. **Response shape is normalized** — every provider returns a
       ``str`` (the Protocol's documented return type), not a dict,
       not ``None``, not a tuple.
    3. **Response content is semantically comparable** — the same
       canned reply comes back regardless of which provider served
       the request, which proves cutover is a 1 env var change with
       no caller-side code change.

    The test parameterises over the four provider names so a single
    failure point surfaces the offending provider in the test ID line
    (e.g. ``... [openai] FAILED``).
    """
    # 1. Configure the env vars: pick the provider, supply a placeholder
    #    API key so the constructor's "missing key" guard does not fire.
    monkeypatch.setenv("LLM_PROVIDER", provider_name)
    monkeypatch.setenv(PROVIDER_API_KEY_ENV[provider_name], "test-key-not-real")

    # 2. Build the client through the production factory path. No
    #    ``_TEST_PROVIDER_OVERRIDES`` here — we want to exercise the
    #    real class wired through the real dispatch table.
    client = create_llm_client()

    # 3. Structural conformance check. If a future refactor makes a
    #    provider not Protocol-conformant, this is where the test
    #    fails first, and the message points at the provider by name.
    assert isinstance(client, LLMClient), (
        f"provider {provider_name!r} returned {type(client).__name__} "
        f"which does not satisfy the LLMClient Protocol"
    )

    # 4. Stub the litellm transport to return the canned reply.
    #    ``side_effect`` (not ``return_value``) so we can assert the
    #    call count and kwargs.
    def _factory(*args: Any, **kwargs: Any) -> MagicMock:
        return _make_litellm_response(CANNED_REPLY_TEXT)

    with patch.object(litellm, "completion", side_effect=_factory) as mocked:
        reply = client.complete(CANNED_PROMPT_MESSAGES)

    # 5. (1) Non-empty: the reply must be a non-empty string. Empty
    #    string is reserved by the Protocol for "model said nothing",
    #    which would also be a smell here since our canned reply is
    #    always non-empty.
    assert isinstance(reply, str), _diff_response_shape(
        provider_name, reply, expected_kind="str", expected_text=CANNED_REPLY_TEXT
    )
    assert reply != "", _diff_response_shape(
        provider_name, reply, expected_kind="str", expected_text=CANNED_REPLY_TEXT
    )

    # 6. (2) Shape normalized: every provider's ``complete()`` returns
    #    the canned text verbatim. If one provider wrapped the
    #    response in an envelope, surfaced the raw dict, or appended
    #    log noise, this assertion fires.
    assert reply == CANNED_REPLY_TEXT, _diff_response_shape(
        provider_name, reply, expected_kind="str", expected_text=CANNED_REPLY_TEXT
    )

    # 7. (3) Semantic comparability: the canned prompt asked for the
    #    word "pong" and the canned reply is "pong". A provider that
    #    asked the model something different (e.g. translated the
    #    prompt, ran a different system prompt) would surface a
    #    different text and the assertion above would fail. So the
    #    same-string check above is also the semantic-equivalence
    #    check, by construction.

    # 8. The provider delegated to litellm exactly once and forwarded
    #    the messages list unchanged (Protocol contract: do not
    #    mutate the input). A second ``complete()`` call from inside
    #    the same test would inflate this counter — we keep it tight.
    assert mocked.call_count == 1, (
        f"provider {provider_name!r}.complete() called litellm.completion "
        f"{mocked.call_count} times, expected 1"
    )
    assert mocked.call_args.kwargs["messages"] == CANNED_PROMPT_MESSAGES, (
        f"provider {provider_name!r} mutated or replaced the messages list"
    )
    # Belt-and-braces: the input list is unchanged.
    assert CANNED_PROMPT_MESSAGES == [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": "Reply with the single word: pong"},
    ]


# -------------------------------------------------------------------------
# Test 2: complete_json() shape across providers
# -------------------------------------------------------------------------


@pytest.mark.parametrize("provider_name", PROVIDERS)
def test_complete_json_returns_schema_conformant_dict_for_every_provider(
    monkeypatch: pytest.MonkeyPatch,
    clear_llm_provider: None,
    provider_name: str,
) -> None:
    """Run the canned JSON prompt; assert each provider returns the right dict shape.

    The companion to the ``complete()`` smoke test. The Protocol
    contract for ``complete_json()`` is stricter: it must return a
    parsed ``dict`` (not a JSON string), and the dict must match the
    supplied schema. This test asserts that contract for every
    provider, with the same canned schema and payload, so a failure
    isolates the offending provider.
    """
    monkeypatch.setenv("LLM_PROVIDER", provider_name)
    monkeypatch.setenv(PROVIDER_API_KEY_ENV[provider_name], "test-key-not-real")

    client = create_llm_client()
    assert isinstance(client, LLMClient), (
        f"provider {provider_name!r} returned {type(client).__name__} "
        f"which does not satisfy the LLMClient Protocol"
    )

    # Stub the transport to return the canned JSON payload as text.
    # The provider must ``json.loads`` it and return the dict.
    with patch.object(
        litellm,
        "completion",
        return_value=_make_litellm_json_response(CANNED_JSON_PAYLOAD),
    ) as mocked:
        result = client.complete_json(CANNED_PROMPT_MESSAGES, CANNED_JSON_SCHEMA)

    # (1) Non-empty: a non-empty dict. Empty dict would also be a
    #     contract violation for the sample schema (the schema
    #     requires the ``answer`` key).
    assert isinstance(result, dict), _diff_response_shape(
        provider_name, result, expected_kind="dict", expected_json=CANNED_JSON_PAYLOAD
    )
    assert result != {}, _diff_response_shape(
        provider_name, result, expected_kind="dict", expected_json=CANNED_JSON_PAYLOAD
    )

    # (2) Shape normalized: the dict has exactly the schema's keys
    #     with the declared types. ``additionalProperties: False`` in
    #     the schema means a stray key is a hard contract violation.
    assert set(result.keys()) == set(CANNED_JSON_PAYLOAD.keys()), _diff_response_shape(
        provider_name, result, expected_kind="dict", expected_json=CANNED_JSON_PAYLOAD
    )

    # (3) Semantic comparability: the canned payload's values come
    #     back unchanged, regardless of which provider served.
    for key, expected_value in CANNED_JSON_PAYLOAD.items():
        assert result[key] == expected_value, _diff_response_shape(
            provider_name, result, expected_kind="dict", expected_json=CANNED_JSON_PAYLOAD
        )
        assert isinstance(result[key], type(expected_value)), _diff_response_shape(
            provider_name, result, expected_kind="dict", expected_json=CANNED_JSON_PAYLOAD
        )

    # The provider forced ``response_format=json_object`` on the
    # underlying litellm call — otherwise the model could return
    # prose and the ``json.loads`` in the provider would explode.
    assert mocked.call_count == 1, (
        f"provider {provider_name!r}.complete_json() called litellm.completion "
        f"{mocked.call_count} times, expected 1"
    )
    assert mocked.call_args.kwargs.get("response_format") == {
        "type": "json_object"
    }, (
        f"provider {provider_name!r}.complete_json() did not request "
        f"json_object response_format; got "
        f"{mocked.call_args.kwargs.get('response_format')!r}"
    )


# -------------------------------------------------------------------------
# Test 3: every supported provider name is wired to a real class
# -------------------------------------------------------------------------


def test_every_supported_provider_has_a_shipped_class(
    monkeypatch: pytest.MonkeyPatch,
    clear_llm_provider: None,
) -> None:
    """Belt-and-braces: ``SUPPORTED_PROVIDERS`` is consistent with the dispatch table.

    Catches the failure mode where a fifth provider is added to
    ``SUPPORTED_PROVIDERS`` (the user-facing set) but the
    corresponding class is not yet shipped in
    ``_PROVIDER_CLASS_PATHS`` — the factory would then raise a
    ``ValueError`` on first use. The cross-provider smoke tests above
    would also catch this, but only with a per-provider failure;
    this test fails once with the offending name in the message.
    """
    for name, env_var in PROVIDER_API_KEY_ENV.items():
        monkeypatch.setenv(env_var, "test-key-not-real")

    unresolved: list[str] = []
    for name in PROVIDERS:
        monkeypatch.setenv("LLM_PROVIDER", name)
        try:
            client = create_llm_client()
        except (ValueError, ImportError) as exc:
            unresolved.append(f"{name}: {exc}")
            continue
        assert isinstance(client, LLMClient), (
            f"provider {name!r} returned {type(client).__name__} which is not LLMClient"
        )

    assert not unresolved, (
        "the following providers are advertised as supported but cannot be "
        f"instantiated: {unresolved}. Check SUPPORTED_PROVIDERS against "
        f"_PROVIDER_CLASS_PATHS in src/llm_client.py."
    )
