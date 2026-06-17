"""Typed message helpers and request validation for chat completions.

This module is intentionally dependency-free (only the Python standard
library) so it can be imported and unit-tested without any network
access, without any provider SDKs (``openai``, ``anthropic``, etc.),
and without any heavy framework (``litellm``, ``dspy``, ...).

It exists alongside :mod:`ai_billing_audit.minimax_client` and
:mod:`ai_billing_audit.llm` as a *validation layer in front of* the
wire calls. ``MiniMaxClient.chat`` performs a minimal inline check
(non-empty messages + temperature in [0, 2]) because that is the
narrow contract it owns. The richer typed structure here is the
reusable vocabulary the rest of the codebase can adopt whenever it
builds a request, regardless of which backend will eventually send
it.

Public surface
--------------
``Role``
    A :class:`enum.Enum` of the three message roles recognised by the
    OpenAI chat completions spec: ``system``, ``user``, ``assistant``.
    Using an enum (not free strings) catches typos at import time
    rather than at API-call time.

``ChatMessage``
    Frozen dataclass ``(role: Role, content: str)``. Frozen so an
    already-built messages list cannot be mutated after validation.
    ``to_dict()`` returns the OpenAI-shaped ``{"role": ..., "content": ...}``
    representation for serialisation.

``system(content)``, ``user(content)``, ``assistant(content)``
    Tiny constructors for the common case. They exist so call sites
    read like the conversation they represent::

        msgs = [system("You are concise."), user("Hello!")]

``ChatRequest``
    A frozen dataclass bundling the typed messages list with the
    sampling overrides that are common to every provider
    (``model``, ``temperature``, ``max_tokens``). ``to_payload()``
    returns the dict you'd hand to the wire (``to_dict()`` on each
    message plus the three top-level fields).

``validate_messages(messages)``
    Stateless validator. Accepts a list of :class:`ChatMessage`,
    rejects ``None``, empty list, and any element that is not a
    :class:`ChatMessage` (with a clear error message). Returns the
    input list unchanged so it composes naturally in expressions.

``validate_chat_request(request)``
    Stateless validator. Calls :func:`validate_messages` and also
    enforces ``temperature in [0, 2]`` (per the OpenAI spec), an
    ``int``/``None`` ``max_tokens`` that is ``> 0`` when set, and a
    non-empty ``model`` string. Returns the request unchanged.

The validators never raise bare ``Exception``/``ValueError`` from
deep inside helper code; they raise :class:`MessageValidationError`
(a subclass of :class:`ValueError`) so callers can catch the
specific failure mode if they want to.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, List, Optional, Union

__all__ = [
    "Role",
    "ChatMessage",
    "ChatRequest",
    "MessageValidationError",
    "system",
    "user",
    "assistant",
    "validate_messages",
    "validate_chat_request",
]


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """The three message roles defined by the OpenAI chat completions spec.

    Inheriting from ``str`` keeps the wire representation identical to
    the literal string OpenAI expects (``"system"`` / ``"user"`` /
    ``"assistant"``), while still giving us the typo-catching benefit
    of an enum at call sites.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatMessage:
    """A single chat message: a role and a textual content payload.

    Frozen so that an already-validated messages list cannot be mutated
    behind the validator's back. ``to_dict()`` returns the OpenAI-shaped
    representation, which is what the wire calls actually expect.
    """

    role: Role
    content: str

    def __post_init__(self) -> None:
        # Catch the common bug of passing ``None`` as content early.
        if self.content is None:
            raise MessageValidationError(
                "ChatMessage.content must be a string, got None"
            )
        if not isinstance(self.content, str):
            raise MessageValidationError(
                f"ChatMessage.content must be a string, got {type(self.content).__name__}"
            )

    def to_dict(self) -> dict:
        """Return the OpenAI-shaped wire dict for this message."""
        return {"role": self.role.value, "content": self.content}


def system(content: str) -> ChatMessage:
    """Shorthand constructor for a system message."""
    return ChatMessage(role=Role.SYSTEM, content=content)


def user(content: str) -> ChatMessage:
    """Shorthand constructor for a user message."""
    return ChatMessage(role=Role.USER, content=content)


def assistant(content: str) -> ChatMessage:
    """Shorthand constructor for an assistant message."""
    return ChatMessage(role=Role.ASSISTANT, content=content)


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatRequest:
    """A typed chat completion request.

    ``messages`` is a positional-but-named tuple of :class:`ChatMessage`
    instances. ``model``, ``temperature``, and ``max_tokens`` are the
    three sampling overrides common to every provider we talk to; any
    provider-specific extras should be added by the caller when it
    translates the request into a wire call.
    """

    messages: tuple
    model: str
    temperature: float = 1.0
    max_tokens: Optional[int] = None

    def __post_init__(self) -> None:
        # We can't run the *full* validator here because we want the
        # caller to be able to construct a request and then validate
        # it explicitly (so the error message is uniform with
        # ``validate_chat_request``). We do the cheap, always-wrong
        # checks here so a clearly-broken object doesn't even survive
        # construction.
        if not isinstance(self.messages, tuple):
            # Accept lists at construction time but freeze to a tuple
            # so the request is genuinely immutable.
            object.__setattr__(self, "messages", tuple(self.messages))
        if self.model is not None and not isinstance(self.model, str):
            raise MessageValidationError(
                f"ChatRequest.model must be a string, got {type(self.model).__name__}"
            )

    def to_payload(self) -> dict:
        """Return the wire-shaped payload for this request.

        Note that ``max_tokens`` is only included when set; some
        providers reject ``max_tokens: null`` and most treat the
        default (no key) as "let the server pick".
        """
        payload: dict = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [m.to_dict() for m in self.messages],
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        return payload


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class MessageValidationError(ValueError):
    """Raised when a messages list or chat request fails validation.

    Subclasses :class:`ValueError` so existing ``except ValueError``
    blocks continue to work; the dedicated class exists so callers
    that want to distinguish "you built the request wrong" from
    "the provider returned garbage" can do so.
    """


# OpenAI's documented valid range for ``temperature`` is [0, 2].
# We re-use this constant in ``validate_chat_request`` and surface it
# in error messages so the constraint is discoverable.
_TEMPERATURE_MIN = 0.0
_TEMPERATURE_MAX = 2.0


def _as_message_list(messages: Any) -> List[ChatMessage]:
    """Coerce + validate a messages list. Used by both validators.

    Accepts any iterable of :class:`ChatMessage` (so generators and
    tuples work) but rejects ``None``, strings, single messages, and
    iterables that contain anything other than :class:`ChatMessage`.
    """
    if messages is None:
        raise MessageValidationError("messages must not be None")
    if isinstance(messages, ChatMessage):
        raise MessageValidationError(
            "messages must be a non-empty list of ChatMessage, not a single ChatMessage"
        )
    if isinstance(messages, str):
        raise MessageValidationError(
            "messages must be a list of ChatMessage, not a string"
        )
    if not isinstance(messages, (list, tuple)):
        # Generators and other iterables are fine if they yield ChatMessage.
        try:
            materialised = list(messages)
        except TypeError as exc:  # pragma: no cover - defensive
            raise MessageValidationError(
                f"messages must be iterable, got {type(messages).__name__}"
            ) from exc
    else:
        materialised = list(messages)

    if not materialised:
        raise MessageValidationError("messages must be a non-empty list")

    for index, item in enumerate(materialised):
        if not isinstance(item, ChatMessage):
            raise MessageValidationError(
                f"messages[{index}] must be a ChatMessage, got {type(item).__name__}"
            )
    return materialised


def validate_messages(
    messages: Union[Iterable[ChatMessage], None],
) -> List[ChatMessage]:
    """Validate a messages list. Returns the list unchanged on success.

    Rejects:
      * ``None`` (clear error, not a TypeError on iteration).
      * A bare string (common typo: forgot the list brackets).
      * A single :class:`ChatMessage` (you must pass a list).
      * An empty list.
      * Any element that is not a :class:`ChatMessage`.
    """
    return _as_message_list(messages)


def validate_chat_request(request: Any) -> ChatRequest:
    """Validate a :class:`ChatRequest` and return it unchanged.

    Rejects anything that is not a :class:`ChatRequest`, plus the
    per-field rules:

      * messages: same rules as :func:`validate_messages`.
      * model: must be a non-empty string.
      * temperature: must be a real number in ``[_TEMPERATURE_MIN, _TEMPERATURE_MAX]``
        (default 1.0; the OpenAI spec range is ``[0, 2]``).
      * max_tokens: must be ``None`` or a positive int (``> 0``).

    Validation is centralised here (rather than only in
    ``ChatRequest.__post_init__``) so callers can build-then-validate
    and get a single uniform error path, and so the rules are easy
    to test in isolation.
    """
    if not isinstance(request, ChatRequest):
        raise MessageValidationError(
            f"validate_chat_request expected a ChatRequest, got {type(request).__name__}"
        )

    # Re-run the messages check so the error message is uniform
    # regardless of whether the caller built the request directly.
    validate_messages(request.messages)

    if not request.model or not isinstance(request.model, str):
        raise MessageValidationError(
            f"ChatRequest.model must be a non-empty string, got {request.model!r}"
        )

    try:
        temperature = float(request.temperature)
    except (TypeError, ValueError) as exc:
        raise MessageValidationError(
            f"ChatRequest.temperature must be a number, got {request.temperature!r}"
        ) from exc
    if not (_TEMPERATURE_MIN <= temperature <= _TEMPERATURE_MAX):
        raise MessageValidationError(
            f"ChatRequest.temperature must be in [{_TEMPERATURE_MIN}, "
            f"{_TEMPERATURE_MAX}]; got {request.temperature!r}"
        )

    if request.max_tokens is not None:
        # bool is a subclass of int in Python; reject it explicitly so
        # ``max_tokens=True`` doesn't sneak through as 1.
        if isinstance(request.max_tokens, bool) or not isinstance(
            request.max_tokens, int
        ):
            raise MessageValidationError(
                f"ChatRequest.max_tokens must be a positive int or None, "
                f"got {type(request.max_tokens).__name__}"
            )
        if request.max_tokens <= 0:
            raise MessageValidationError(
                f"ChatRequest.max_tokens must be > 0 when set, got {request.max_tokens!r}"
            )

    return request
