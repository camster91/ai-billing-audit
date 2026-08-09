"""Acceptance tests for ``MiniMaxClient``.

These tests use a fake transport (no network) to verify the contract
described in the task body:

1. ``MiniMaxClient()`` instantiable with no args when ``OPENAI_API_KEY`` is set.
2. The default model is ``MiniMax-M3`` and the default temperature is 0.
3. The base URL is the official MiniMax OpenAI-compatible endpoint
   (``https://api.minimax.io/v1``) per the public docs at
   https://platform.minimax.io/docs/api-reference/text-openai-api.
4. ``chat(messages)`` returns the underlying SDK response.
5. A custom temperature override is forwarded to the transport.
6. A missing env var raises a clear ``RuntimeError`` (only when no explicit
   ``api_key`` and no injected transport is supplied).
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest

from ai_billing_audit.minimax_client import (
    DEFAULT_TEMPERATURE,
    MINIMAX_BASE_URL,
    MINIMAX_DEFAULT_MODEL,
    MiniMaxClient,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next_response: Any = None

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.next_response


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeTransport:
    """Mimics the surface of ``openai.OpenAI`` that ``MiniMaxClient`` uses."""

    def __init__(self) -> None:
        self.chat = _FakeChat()


# ---------------------------------------------------------------------------
# Acceptance: pinned defaults + env-var auth
# ---------------------------------------------------------------------------


def test_minimax_client_module_constants_pin_official_endpoint() -> None:
    """The module-level constants must match MiniMax's published endpoint."""
    assert MINIMAX_BASE_URL == "https://api.minimax.io/v1"
    assert MINIMAX_DEFAULT_MODEL == "MiniMax-M3"
    assert DEFAULT_TEMPERATURE == 0


def test_chat_with_no_args_uses_default_model_and_zero_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-arg ``chat(messages)`` call must default to model=M3 + temp=0."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    fake = _FakeTransport()
    fake.chat.completions.next_response = MagicMock(
        choices=[MagicMock(message=MagicMock(content="hello back"))]
    )

    client = MiniMaxClient(transport=fake)
    response = client.chat([{"role": "user", "content": "ping"}])

    # The transport was called exactly once with the pinned defaults.
    assert len(fake.chat.completions.calls) == 1
    call = fake.chat.completions.calls[0]
    assert call["model"] == "MiniMax-M3"
    assert call["temperature"] == 0
    assert call["messages"] == [{"role": "user", "content": "ping"}]
    # Response is the (fake) SDK response, returned unchanged.
    assert response is fake.chat.completions.next_response


def test_chat_forwards_temperature_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller-supplied ``temperature`` overrides the default of 0."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    fake = _FakeTransport()
    fake.chat.completions.next_response = MagicMock(
        choices=[MagicMock(message=MagicMock(content="ok"))]
    )

    client = MiniMaxClient(transport=fake)
    client.chat(
        [{"role": "user", "content": "creative please"}],
        temperature=0.7,
    )

    assert fake.chat.completions.calls[0]["temperature"] == 0.7


def test_chat_rejects_out_of_range_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad temperature fails fast with a clear error."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    fake = _FakeTransport()

    client = MiniMaxClient(transport=fake)
    with pytest.raises(ValueError, match="temperature must be in"):
        client.chat([{"role": "user", "content": "x"}], temperature=2.5)


def test_chat_rejects_empty_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty messages list fails before hitting the wire."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    fake = _FakeTransport()

    client = MiniMaxClient(transport=fake)
    with pytest.raises(ValueError, match="non-empty"):
        client.chat([])


def test_base_url_override_is_honoured() -> None:
    """A custom ``base_url`` is reflected on the client (for local mocks)."""
    fake = _FakeTransport()
    client = MiniMaxClient(
        api_key="x", base_url="http://localhost:9999/v1", transport=fake
    )
    assert client.base_url == "http://localhost:9999/v1"


def test_missing_api_key_raises_clear_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env var + no explicit key + no transport -> loud, actionable error."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        MiniMaxClient()  # no transport, no env var -> hard fail


def test_transport_path_does_not_require_api_key() -> None:
    """Tests that inject a transport should run even with no env var set."""
    # Deliberately no monkeypatch.setenv here; the transport must bypass
    # the OPENAI_API_KEY requirement so unit tests don't need a real key.
    os.environ.pop("OPENAI_API_KEY", None)
    fake = _FakeTransport()
    client = MiniMaxClient(transport=fake)
    fake.chat.completions.next_response = MagicMock(
        choices=[MagicMock(message=MagicMock(content="ok"))]
    )
    client.chat([{"role": "user", "content": "x"}])
    assert len(fake.chat.completions.calls) == 1


def test_importable_from_package_root() -> None:
    """The client is re-exported from ``ai_billing_audit``."""
    import ai_billing_audit

    assert ai_billing_audit.MiniMaxClient is MiniMaxClient
    assert ai_billing_audit.MINIMAX_BASE_URL == MINIMAX_BASE_URL
    assert ai_billing_audit.MINIMAX_DEFAULT_MODEL == MINIMAX_DEFAULT_MODEL
