"""Acceptance + contract tests for the typed messages module.

The acceptance criterion for this task is:

    helper module with at least one unit test demonstrating input
    validation rejects bad temperature and empty message lists.

This file provides that plus a tight contract test for every public
function: ``Role``, ``ChatMessage``, the ``system/user/assistant``
constructors, ``ChatRequest``, ``validate_messages``, and
``validate_chat_request``. The module is dependency-free, so no
network or SDK imports are required.
"""

from __future__ import annotations

from typing import Any

import pytest

from ai_billing_audit.messages import (
    ChatMessage,
    ChatRequest,
    MessageValidationError,
    Role,
    assistant,
    system,
    user,
    validate_chat_request,
    validate_messages,
)


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------


def test_role_values_match_openai_spec() -> None:
    """Role members must serialise to the exact lowercase strings OpenAI expects."""
    assert Role.SYSTEM.value == "system"
    assert Role.USER.value == "user"
    assert Role.ASSISTANT.value == "assistant"


def test_role_is_str_enum_so_it_serialises_naturally() -> None:
    """Role inherits from str; json.dumps should not choke on it."""
    import json

    assert json.dumps({"role": Role.SYSTEM.value}) == '{"role": "system"}'


# ---------------------------------------------------------------------------
# ChatMessage
# ---------------------------------------------------------------------------


def test_chat_message_to_dict_returns_openai_shape() -> None:
    """``to_dict`` must produce the wire-shaped dict."""
    msg = ChatMessage(role=Role.USER, content="hi")
    assert msg.to_dict() == {"role": "user", "content": "hi"}


def test_chat_message_is_frozen() -> None:
    """Mutation after construction is a bug; the dataclass must refuse it."""
    msg = ChatMessage(role=Role.USER, content="hi")
    with pytest.raises((AttributeError, Exception)):
        msg.content = "tampered"  # type: ignore[misc]


def test_chat_message_rejects_non_string_content() -> None:
    """The common bug of passing a dict or None should fail loud and early."""
    with pytest.raises(MessageValidationError):
        ChatMessage(role=Role.USER, content=None)  # type: ignore[arg-type]
    with pytest.raises(MessageValidationError):
        ChatMessage(role=Role.USER, content={"text": "hi"})  # type: ignore[arg-type]


def test_system_user_assistant_helpers_build_correct_role() -> None:
    """The three shorthand constructors must produce messages with the right role."""
    assert system("sys").role is Role.SYSTEM
    assert user("u").role is Role.USER
    assert assistant("a").role is Role.ASSISTANT
    assert system("sys").content == "sys"
    assert user("u").content == "u"
    assert assistant("a").content == "a"


def test_helpers_round_trip_through_to_dict() -> None:
    """Each shorthand constructor must produce a wire-shaped dict."""
    assert user("ping").to_dict() == {"role": "user", "content": "ping"}
    assert system("be brief").to_dict() == {"role": "system", "content": "be brief"}
    assert assistant("hi back").to_dict() == {"role": "assistant", "content": "hi back"}


# ---------------------------------------------------------------------------
# validate_messages
# ---------------------------------------------------------------------------


def test_validate_messages_accepts_a_list_of_chat_messages() -> None:
    """The happy path: a list of well-formed messages is returned unchanged."""
    msgs = [system("You are concise."), user("Hello!")]
    out = validate_messages(msgs)
    assert out == msgs


def test_validate_messages_accepts_iterables_and_tuples() -> None:
    """Generators and tuples must work (we materialise before checking)."""
    msgs_iter = (m for m in [user("a"), user("b")])
    out = validate_messages(msgs_iter)
    assert [m.content for m in out] == ["a", "b"]

    out_tuple = validate_messages((user("a"), user("b")))
    assert [m.content for m in out_tuple] == ["a", "b"]


# Acceptance: empty messages list must be rejected.
def test_validate_messages_rejects_empty_list() -> None:
    """Empty messages list fails before hitting the wire."""
    with pytest.raises(MessageValidationError, match="non-empty"):
        validate_messages([])


def test_validate_messages_rejects_none() -> None:
    """``None`` is the most common upstream failure; fail with a clear error."""
    with pytest.raises(MessageValidationError, match="must not be None"):
        validate_messages(None)


def test_validate_messages_rejects_bare_string() -> None:
    """A common typo: caller forgot the list brackets."""
    with pytest.raises(MessageValidationError, match="not a string"):
        validate_messages("hello")  # type: ignore[arg-type]


def test_validate_messages_rejects_a_single_chat_message() -> None:
    """A single message is not a list; reject explicitly."""
    with pytest.raises(MessageValidationError, match="not a single ChatMessage"):
        validate_messages(user("hi"))


def test_validate_messages_rejects_non_chat_message_elements() -> None:
    """A list of dicts is not a list of ChatMessage."""
    with pytest.raises(MessageValidationError, match="messages\\[0\\]"):
        validate_messages([{"role": "user", "content": "x"}])


# ---------------------------------------------------------------------------
# ChatRequest + validate_chat_request
# ---------------------------------------------------------------------------


def test_chat_request_to_payload_shape() -> None:
    """``to_payload`` returns the wire dict with messages + 3 top-level fields."""
    req = ChatRequest(
        messages=(system("be brief"), user("hi")),
        model="MiniMax-M3",
        temperature=0.5,
        max_tokens=64,
    )
    payload = req.to_payload()
    assert payload == {
        "model": "MiniMax-M3",
        "temperature": 0.5,
        "max_tokens": 64,
        "messages": [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
        ],
    }


def test_chat_request_to_payload_omits_max_tokens_when_none() -> None:
    """Some providers reject ``max_tokens: null``; we just drop the key."""
    req = ChatRequest(messages=(user("hi"),), model="MiniMax-M3")
    payload = req.to_payload()
    assert "max_tokens" not in payload
    assert payload["model"] == "MiniMax-M3"


def test_chat_request_freezes_messages_tuple() -> None:
    """A list passed in must be coerced to an immutable tuple."""
    req = ChatRequest(messages=[user("a"), user("b")], model="m")
    assert isinstance(req.messages, tuple)
    assert [m.content for m in req.messages] == ["a", "b"]


def test_validate_chat_request_accepts_well_formed_request() -> None:
    """The happy path for the full request validator."""
    req = ChatRequest(
        messages=(user("hi"),),
        model="MiniMax-M3",
        temperature=0.0,
        max_tokens=10,
    )
    out = validate_chat_request(req)
    assert out is req


# Acceptance: bad temperature must be rejected by the validator.
def test_validate_chat_request_rejects_temperature_above_two() -> None:
    """A temperature of 2.5 is outside the OpenAI-spec range [0, 2]."""
    req = ChatRequest(
        messages=(user("hi"),),
        model="MiniMax-M3",
        temperature=2.5,
    )
    with pytest.raises(MessageValidationError, match="temperature must be in"):
        validate_chat_request(req)


def test_validate_chat_request_rejects_temperature_below_zero() -> None:
    """Negative temperatures are not part of the spec; reject them."""
    req = ChatRequest(
        messages=(user("hi"),),
        model="MiniMax-M3",
        temperature=-0.1,
    )
    with pytest.raises(MessageValidationError, match="temperature must be in"):
        validate_chat_request(req)


def test_validate_chat_request_accepts_boundary_temperatures() -> None:
    """0.0 and 2.0 are inclusive bounds; both must validate."""
    for t in (0.0, 1.0, 2.0):
        req = ChatRequest(messages=(user("x"),), model="m", temperature=t)
        validate_chat_request(req)  # must not raise


def test_validate_chat_request_rejects_non_numeric_temperature() -> None:
    """A non-numeric temperature is a programming error; reject explicitly."""
    req = ChatRequest(
        messages=(user("hi"),),
        model="MiniMax-M3",
        temperature="hot",  # type: ignore[arg-type]
    )
    with pytest.raises(MessageValidationError, match="must be a number"):
        validate_chat_request(req)


# Acceptance: empty messages list must be rejected (called out via the
# ``validate_chat_request`` path too, since it composes the same check).
def test_validate_chat_request_rejects_empty_messages() -> None:
    """An empty messages list fails the request validator the same way."""
    req = ChatRequest(messages=(), model="MiniMax-M3")
    with pytest.raises(MessageValidationError, match="non-empty"):
        validate_chat_request(req)


def test_validate_chat_request_rejects_non_chat_message() -> None:
    """A request built with a list of dicts is still a programming error."""
    req = ChatRequest(
        messages=({"role": "user", "content": "x"},),  # type: ignore[arg-type]
        model="MiniMax-M3",
    )
    with pytest.raises(MessageValidationError):
        validate_chat_request(req)


def test_validate_chat_request_rejects_empty_model() -> None:
    """Empty / missing model is the #1 source of 400s from real APIs."""
    req = ChatRequest(messages=(user("x"),), model="")
    with pytest.raises(MessageValidationError, match="non-empty string"):
        validate_chat_request(req)


def test_validate_chat_request_rejects_zero_or_negative_max_tokens() -> None:
    """``max_tokens=0`` is nonsense; ``max_tokens=-5`` is definitely wrong."""
    for bad in (0, -1, -100):
        req = ChatRequest(
            messages=(user("x"),),
            model="m",
            max_tokens=bad,
        )
        with pytest.raises(MessageValidationError, match="max_tokens"):
            validate_chat_request(req)


def test_validate_chat_request_rejects_non_int_max_tokens() -> None:
    """A float (or bool!) sneaking in as max_tokens is a real bug we've seen."""
    # bool is a subclass of int; must be rejected explicitly.
    req = ChatRequest(
        messages=(user("x"),),
        model="m",
        max_tokens=True,  # type: ignore[arg-type]
    )
    with pytest.raises(MessageValidationError, match="max_tokens"):
        validate_chat_request(req)

    req_float = ChatRequest(
        messages=(user("x"),),
        model="m",
        max_tokens=64.0,  # type: ignore[arg-type]
    )
    with pytest.raises(MessageValidationError, match="max_tokens"):
        validate_chat_request(req_float)


def test_validate_chat_request_rejects_non_request_input() -> None:
    """Calling the validator on the wrong type must fail with a clear error."""
    with pytest.raises(MessageValidationError, match="expected a ChatRequest"):
        validate_chat_request({"messages": [], "model": "m"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Import + package-root re-export smoke test
# ---------------------------------------------------------------------------


def test_messages_module_is_importable_from_package_root() -> None:
    """The new public surface is reachable from ``ai_billing_audit``."""
    import ai_billing_audit

    assert ai_billing_audit.ChatMessage is ChatMessage
    assert ai_billing_audit.ChatRequest is ChatRequest
    assert ai_billing_audit.Role is Role
    assert ai_billing_audit.system is system
    assert ai_billing_audit.user is user
    assert ai_billing_audit.assistant is assistant
    assert ai_billing_audit.validate_messages is validate_messages
    assert ai_billing_audit.validate_chat_request is validate_chat_request
    assert ai_billing_audit.MessageValidationError is MessageValidationError
