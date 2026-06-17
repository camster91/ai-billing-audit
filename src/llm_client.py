"""Vendor-neutral LLM client Protocol.

This module defines the :class:`LLMClient` Protocol — the single contract
every LLM backend implementation in the project must satisfy. It exists
as a top-level ``src/llm_client.py`` module (rather than living inside
the ``ai_billing_audit`` package) so that it can be imported cleanly
from sibling modules and from test code without creating a circular
import back into the package.

Why a Protocol (and not an ABC)
-------------------------------
We use :class:`typing.Protocol` because the goal is structural typing:
any class that exposes the two methods with matching signatures
counts as an ``LLMClient`` — no explicit ``isinstance`` registration,
no ``@abstractmethod`` enforcement, and no forced inheritance. That
matters here because the project ships four provider backends
(``minimax``/``claude``/``openai``/``gemini``) and a test double, and
we want all of them to be drop-in replacements without ceremony.

The :func:`create_llm_client` factory (defined further down in this
same file) is the *only* place in the codebase that picks a concrete
implementation by name. Callers receive an ``LLMClient``-typed value
and never see ``if provider == ...`` logic. That invariant is what
keeps the rest of the codebase vendor-neutral.

Conformance
-----------
A class is a structural subtype of :class:`LLMClient` if it exposes:

* ``complete(messages, **kwargs)`` returning ``str``
* ``complete_json(messages, schema, **kwargs)`` returning ``dict``

Both methods must accept the OpenAI chat-completion ``messages`` shape
(a list of ``{"role": ..., "content": ...}`` dicts). The
``complete_json`` method must additionally accept a JSON Schema dict
and return a parsed ``dict`` that satisfies that schema.

This module is import-only. It contains no implementation, no
environment-variable reading, and no I/O.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Mapping, Protocol, cast, runtime_checkable

__all__ = ["LLMClient", "ChatMessage", "create_llm_client"]

# Default provider name when ``LLM_PROVIDER`` is unset.
# MiniMax is the team's primary backend (see ``ai_billing_audit.llm``), so
# zero-config deployments land on it without an explicit env var.
_DEFAULT_PROVIDER = "minimax"

# Canonical provider names this factory knows how to build.
# Adding a new provider means adding an entry here AND a concrete class
# in the same module — those are the only two places that should ever
# mention a provider name. Everything else in the codebase receives an
# ``LLMClient``-typed value and never sees ``if provider == ...`` logic.
SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"minimax", "claude", "openai", "gemini"})

# Maps each canonical provider name to the fully-qualified class path
# that implements it. The four classes are populated by sibling task
# ``t_90cfc976`` ("Implement four provider classes via litellm"), which
# ships ``MinimaxClient`` / ``ClaudeClient`` / ``OpenAIClient`` /
# ``GeminiClient`` in this same file. We resolve them lazily so this
# factory module imports cleanly even when the four classes have not
# landed yet — the failure mode is "ValueError on first use" rather
# than "ImportError at module load", which keeps partial rollouts
# (protocol + factory shipped, implementations still in flight) viable.
_PROVIDER_CLASS_PATHS: Mapping[str, str] = {
    "minimax": "src.llm_client:MinimaxClient",
    "claude":  "src.llm_client:ClaudeClient",
    "openai":  "src.llm_client:OpenAIClient",
    "gemini":  "src.llm_client:GeminiClient",
}

# Test override hook. When populated, the factory consults this
# mapping FIRST (keyed by canonical provider name) and only falls back
# to ``_PROVIDER_CLASS_PATHS`` for entries it cannot resolve. Tests
# use it to inject fake classes without touching the real ones —
# keeping the production path free of ``if testing:`` branches.
_TEST_PROVIDER_OVERRIDES: dict[str, type] = {}

# Type alias for the OpenAI-style chat message dict.
#
# Using a TypeAlias (not a TypedDict) keeps the Protocol surface
# permissive: real providers occasionally attach extra fields
# (e.g. ``name``, ``tool_call_id``, ``function_call``) that are
# valid in OpenAI's chat format but would force TypedDict subclasses
# to be declared. The structural contract for *our* code is just
# "a dict with at least role and content strings" — anything stricter
# belongs in the implementation, not the protocol.
ChatMessage = dict[str, Any]


@runtime_checkable
class LLMClient(Protocol):
    """Structural interface every LLM backend must satisfy.

    The :func:`typing.runtime_checkable` decorator means ``isinstance`` /
    ``issubclass`` checks against ``LLMClient`` work at runtime, which is
    useful in tests (``assert isinstance(my_obj, LLMClient)``) and in the
    factory function that picks an implementation by env var.
    """

    def complete(
        self,
        messages: list[ChatMessage],
        **kwargs: Any,
    ) -> str:
        """Send a chat-completion request and return the assistant's text reply.

        Parameters
        ----------
        messages:
            The conversation history in OpenAI chat format: a list of
            ``{"role": ..., "content": ...}`` dicts. The protocol imposes
            no constraint on the number of messages or which roles appear;
            that policy is the caller's responsibility.
        **kwargs:
            Backend-specific overrides forwarded to the underlying SDK
            (model name, temperature, max_tokens, tools, etc.). The
            protocol deliberately does not enumerate them so each
            backend can accept the keyword set it supports.

        Returns
        -------
        str
            The assistant message content as a plain string. The
            implementation is responsible for extracting it from the
            provider's response envelope (e.g. OpenAI's
            ``choices[0].message.content``).

        Contract
        --------
        - Must raise on transport / auth / model errors rather than
          returning an empty string. Empty-string-as-error is an
          anti-pattern: callers cannot distinguish "model said nothing"
          from "request failed".
        - Must NOT mutate the input ``messages`` list in place.
        - Must NOT make any assumptions about model identity; the
          model is selected by the implementation, by the caller via
          ``kwargs``, or by env var — not by the Protocol.
        """
        ...

    def complete_json(
        self,
        messages: list[ChatMessage],
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a chat-completion request and return a schema-conformant dict.

        Parameters
        ----------
        messages:
            The conversation history in OpenAI chat format. Same
            contract as :meth:`complete`.
        schema:
            A JSON Schema dict (the standard shape used by OpenAI's
            ``response_format={"type": "json_schema", "json_schema": {...}}``
            and by Anthropic's structured-output tool). The Protocol
            does not interpret the schema — the implementation is
            responsible for forwarding it to a provider that supports
            constrained decoding (or for prompting-and-parsing when
            constrained decoding is unavailable).
        **kwargs:
            Backend-specific overrides forwarded to the underlying
            SDK, same contract as :meth:`complete`.

        Returns
        -------
        dict
            A Python ``dict`` that conforms to the supplied ``schema``.
            "Conforms" means: all required keys are present, all values
            have the declared types, and no extra keys appear where the
            schema forbids them. The implementation may rely on the
            provider's structured-output guarantees, or validate the
            result locally with jsonschema / pydantic before returning.

        Contract
        --------
        - Must return a parsed ``dict``, NOT a JSON string. Callers
          should be able to index into the result directly.
        - Must raise if the provider's output fails to validate
          against ``schema``. Silent fallback to ``{}`` is forbidden.
        - Must raise if the provider does not support structured output
          and no parsing strategy is configured — better to fail loud
          than to return a string-parsed dict the schema doesn't actually
          guarantee.
        - Must NOT mutate the input ``messages`` list or the input
          ``schema`` dict in place.
        """
        ...


# ---------------------------------------------------------------------------
# Factory: ``create_llm_client()``
# ---------------------------------------------------------------------------
#
# This is the ONLY place in the codebase that picks a concrete LLM backend
# by name. Callers receive an ``LLMClient``-typed value and never see
# ``if provider == ...`` logic. The dispatch is table-driven: the canonical
# provider name (``LLM_PROVIDER`` env var, or the default) is looked up in
# ``_PROVIDER_CLASS_PATHS`` to find the class to instantiate. Adding a new
# provider means adding an entry to that mapping AND shipping the class —
# nothing else in the codebase needs to change.


def _resolve_provider_class(provider: str) -> type:
    """Return the concrete class that implements ``provider``.

    Resolution order:
      1. ``_TEST_PROVIDER_OVERRIDES`` (test injection only)
      2. ``_PROVIDER_CLASS_PATHS`` (production mapping)

    The production mapping is dereferenced lazily so this module imports
    cleanly even when the four implementation classes (``MinimaxClient``
    etc.) have not yet landed in the same file. If the class is missing
    the factory surfaces a clear ``ValueError`` naming the missing symbol,
    not a bare ``ImportError`` — that way callers see one error shape
    regardless of whether the provider is unknown or merely unimplemented.
    """
    override = _TEST_PROVIDER_OVERRIDES.get(provider)
    if override is not None:
        return override

    path = _PROVIDER_CLASS_PATHS.get(provider)
    if path is None:  # pragma: no cover - guarded by the caller
        raise ValueError(
            f"unknown LLM provider {provider!r}; supported: "
            f"{sorted(SUPPORTED_PROVIDERS)}"
        )

    module_name, _, attr = path.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(
            f"LLM provider {provider!r} is registered but its module "
            f"({module_name!r}) cannot be imported: {exc}"
        ) from exc
    try:
        cls = getattr(module, attr)
    except AttributeError as exc:
        raise ValueError(
            f"LLM provider {provider!r} is registered but {module_name}.{attr} "
            f"is not defined. The concrete class has not been shipped yet."
        ) from exc
    # ``getattr`` on a module returns ``Any``; the cast narrows it back
    # to ``type`` so the caller's static type-check is satisfied. The
    # runtime contract is enforced by the ``isinstance`` check in
    # ``create_llm_client``.
    if not isinstance(cls, type):
        raise TypeError(
            f"LLM provider {provider!r} resolved to {cls!r} which is not a class"
        )
    return cls


def _coerce_kwargs(kwargs: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a plain ``dict`` copy of the caller's kwargs (or ``{}``).

    The factory is the boundary between caller-controlled and
    provider-controlled state, so we normalise the input shape here
    rather than relying on the provider classes to do it. ``None`` is
    accepted as an explicit "no overrides" marker for callers that
    pass ``**maybe_kwargs`` from higher up.
    """
    if kwargs is None:
        return {}
    return dict(kwargs)


def create_llm_client(
    provider: str | None = None,
    **kwargs: Any,
) -> LLMClient:
    """Build an :class:`LLMClient` for the configured backend.

    Parameters
    ----------
    provider:
        Canonical backend name. When ``None`` (the default) the value
        is read from the ``LLM_PROVIDER`` environment variable; if
        that is unset or empty, the factory falls back to
        :data:`_DEFAULT_PROVIDER` (currently ``"minimax"``).

        Accepted values: ``"minimax"``, ``"claude"``, ``"openai"``,
        ``"gemini"``. Any other value raises :class:`ValueError`.
    **kwargs:
        Backend-specific overrides forwarded to the provider
        constructor (e.g. ``model=``, ``api_key=``, ``timeout=``).
        The factory does not interpret them; the concrete class
        decides which keys it honours.

    Returns
    -------
    LLMClient
        An instance of the concrete provider class. The returned
        object satisfies the :class:`LLMClient` :class:`Protocol` —
        callers can pass it anywhere an ``LLMClient`` is expected
        without knowing which backend it is.

    Raises
    ------
    ValueError
        If ``provider`` (or ``$LLM_PROVIDER``) is not one of the
        supported names. The error message lists the supported set
        and quotes the offender so misconfigurations are obvious in
        logs.

    Notes
    -----
    This function is intentionally the only dispatch site in the
    codebase. Callers MUST NOT branch on provider name; if a backend
    needs different behaviour, that behaviour belongs on the concrete
    class, not at the call site. The companion test
    ``test_factory_has_no_provider_name_conditionals`` enforces this
    invariant by scanning the source for ``if`` statements that test
    the provider variable.
    """
    chosen = provider if provider is not None else os.environ.get("LLM_PROVIDER", _DEFAULT_PROVIDER)
    # Treat empty string the same as unset — empty env var is almost
    # always an operator typo (e.g. ``export LLM_PROVIDER=``) and
    # silently picking the default is the friendlier behaviour.
    if chosen == "":
        chosen = _DEFAULT_PROVIDER
    if chosen not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"unknown LLM provider {chosen!r}; supported: "
            f"{sorted(SUPPORTED_PROVIDERS)}"
        )

    cls = _resolve_provider_class(chosen)
    instance = cls(**_coerce_kwargs(kwargs))
    # Belt-and-braces: even though ``cls`` comes from our own registry,
    # verify the structural contract at runtime. ``Protocol`` is
    # ``runtime_checkable`` so ``isinstance`` does the right thing.
    if not isinstance(instance, LLMClient):
        raise TypeError(
            f"provider class {cls.__name__!r} for {chosen!r} does not "
            f"satisfy the LLMClient Protocol (missing complete() or "
            f"complete_json())"
        )
    return instance


# ---------------------------------------------------------------------------
# Concrete provider implementations
# ---------------------------------------------------------------------------
#
# Each class is a thin structural implementation of the :class:`LLMClient`
# Protocol. They store a model id and an API key (the key is sourced from a
# provider-specific env var at construction time and may be overridden via
# the ``api_key`` kwarg for tests). All real work is delegated to
# ``litellm.completion`` — these classes do not branch on model name,
# message shape, or response envelope, and they do not catch provider
# errors (litellm already raises structured exceptions on transport / auth /
# model-not-found failures, and the Protocol contract says callers want a
# loud failure, not an empty string).
#
# Per the parent decomposition: no conditional logic lives in the factory
# or in callers — only the four classes below know which provider they
# are, and they each carry that knowledge as a single ``api_key_env``
# constant. Adding a fifth provider means: (a) ship a fifth class below,
# (b) add an entry to ``_PROVIDER_CLASS_PATHS`` and ``SUPPORTED_PROVIDERS``
# at the top of this file. Nothing else changes.
#
# Env-var mapping
# ---------------
# - ``minimax`` → ``MINIMAX_API_KEY`` (the team's convention per the
#   parent task body). Model prefix passed to litellm is ``"minimax/..."``.
# - ``claude``  → ``ANTHROPIC_API_KEY``. Model prefix is ``"anthropic/..."``
#   (which is what litellm expects for Anthropic-backed models).
# - ``openai``  → ``OPENAI_API_KEY``. Model id is the OpenAI catalog name
#   (e.g. ``"gpt-4o-mini"``); litellm infers the provider from the key.
# - ``gemini``  → ``GEMINI_API_KEY`` (or ``GOOGLE_API_KEY`` as a
#   compatibility fallback). Model prefix is ``"gemini/..."``.

import litellm  # noqa: E402  -- intentionally after the Protocol/factory so the
                 # Protocol docstring is the first thing readers see.

_DEFAULT_TEMPERATURE = 0.0  # deterministic default; callers override per-call.


def _extract_assistant_text(response: Any) -> str:
    """Pull the assistant text out of a litellm/OpenAI-shaped response.

    Centralised so all four provider classes share the same envelope
    handling — and so the literal ``choices[0].message.content`` chain
    lives in exactly one place. Raises ``AttributeError`` (propagated)
    if the response shape is unexpected, which is the right signal to
    surface up rather than swallow.
    """
    # ``litellm.completion`` is typed as ``Any`` at the response object
    # level, so ``response.choices[0].message.content`` is also ``Any``
    # under mypy --strict even though every supported provider returns a
    # plain string here. We ``cast`` at the boundary so the four provider
    # classes (and the Protocol conformants that depend on them) stay
    # strict-clean. If a provider ever returns a non-string (e.g. a list
    # of content blocks for tool use), the cast is the place to revisit.
    return cast(str, response.choices[0].message.content)


class MinimaxClient:
    """LLMClient implementation for the ``minimax`` provider.

    Thin litellm wrapper. The model id is stored on ``self.model``; the
    API key is sourced from ``MINIMAX_API_KEY`` at construction time
    and stored on ``self.api_key``. Callers may override either via
    constructor kwargs (used by tests).
    """

    api_key_env = "MINIMAX_API_KEY"

    def __init__(
        self,
        *,
        model: str = "minimax/MiniMax-M3",
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key if api_key is not None else os.environ.get(self.api_key_env, "")
        if not self.api_key:
            raise RuntimeError(
                f"{self.api_key_env} is not set; export it or pass api_key= explicitly"
            )

    def complete(self, messages: list[ChatMessage], **kwargs: Any) -> str:
        return _extract_assistant_text(
            litellm.completion(
                model=self.model,
                messages=list(messages),  # defensive copy; see Protocol contract
                api_key=self.api_key,
                temperature=kwargs.pop("temperature", _DEFAULT_TEMPERATURE),
                **kwargs,
            )
        )

    def complete_json(
        self,
        messages: list[ChatMessage],
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        import json  # local import: json is only needed on this code path.

        response = litellm.completion(
            model=self.model,
            messages=list(messages),
            api_key=self.api_key,
            temperature=kwargs.pop("temperature", _DEFAULT_TEMPERATURE),
            response_format={"type": "json_object"},
            **({"schema": schema} if schema else {}),
            **kwargs,
        )
        return cast(dict[str, Any], json.loads(_extract_assistant_text(response)))


class ClaudeClient:
    """LLMClient implementation for Anthropic's Claude (via litellm)."""

    api_key_env = "ANTHROPIC_API_KEY"

    def __init__(
        self,
        *,
        model: str = "anthropic/claude-3-5-sonnet-20241022",
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key if api_key is not None else os.environ.get(self.api_key_env, "")
        if not self.api_key:
            raise RuntimeError(
                f"{self.api_key_env} is not set; export it or pass api_key= explicitly"
            )

    def complete(self, messages: list[ChatMessage], **kwargs: Any) -> str:
        return _extract_assistant_text(
            litellm.completion(
                model=self.model,
                messages=list(messages),
                api_key=self.api_key,
                temperature=kwargs.pop("temperature", _DEFAULT_TEMPERATURE),
                **kwargs,
            )
        )

    def complete_json(
        self,
        messages: list[ChatMessage],
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        import json

        response = litellm.completion(
            model=self.model,
            messages=list(messages),
            api_key=self.api_key,
            temperature=kwargs.pop("temperature", _DEFAULT_TEMPERATURE),
            response_format={"type": "json_object"},
            **({"schema": schema} if schema else {}),
            **kwargs,
        )
        return cast(dict[str, Any], json.loads(_extract_assistant_text(response)))


class OpenAIClient:
    """LLMClient implementation for OpenAI (via litellm)."""

    api_key_env = "OPENAI_API_KEY"

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key if api_key is not None else os.environ.get(self.api_key_env, "")
        if not self.api_key:
            raise RuntimeError(
                f"{self.api_key_env} is not set; export it or pass api_key= explicitly"
            )

    def complete(self, messages: list[ChatMessage], **kwargs: Any) -> str:
        return _extract_assistant_text(
            litellm.completion(
                model=self.model,
                messages=list(messages),
                api_key=self.api_key,
                temperature=kwargs.pop("temperature", _DEFAULT_TEMPERATURE),
                **kwargs,
            )
        )

    def complete_json(
        self,
        messages: list[ChatMessage],
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        import json

        response = litellm.completion(
            model=self.model,
            messages=list(messages),
            api_key=self.api_key,
            temperature=kwargs.pop("temperature", _DEFAULT_TEMPERATURE),
            response_format={"type": "json_object"},
            **({"schema": schema} if schema else {}),
            **kwargs,
        )
        return cast(dict[str, Any], json.loads(_extract_assistant_text(response)))


class GeminiClient:
    """LLMClient implementation for Google Gemini (via litellm)."""

    # Gemini accepts both env-var names; check both at construction time
    # so deployments that already export GOOGLE_API_KEY (Google's own
    # convention) keep working without renaming.
    api_key_env = "GEMINI_API_KEY"
    api_key_env_fallback = "GOOGLE_API_KEY"

    def __init__(
        self,
        *,
        model: str = "gemini/gemini-1.5-flash",
        api_key: str | None = None,
    ) -> None:
        self.model = model
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = (
                os.environ.get(self.api_key_env, "")
                or os.environ.get(self.api_key_env_fallback, "")
            )
        if not self.api_key:
            raise RuntimeError(
                f"neither {self.api_key_env} nor {self.api_key_env_fallback} "
                f"is set; export one or pass api_key= explicitly"
            )

    def complete(self, messages: list[ChatMessage], **kwargs: Any) -> str:
        return _extract_assistant_text(
            litellm.completion(
                model=self.model,
                messages=list(messages),
                api_key=self.api_key,
                temperature=kwargs.pop("temperature", _DEFAULT_TEMPERATURE),
                **kwargs,
            )
        )

    def complete_json(
        self,
        messages: list[ChatMessage],
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        import json

        response = litellm.completion(
            model=self.model,
            messages=list(messages),
            api_key=self.api_key,
            temperature=kwargs.pop("temperature", _DEFAULT_TEMPERATURE),
            response_format={"type": "json_object"},
            **({"schema": schema} if schema else {}),
            **kwargs,
        )
        return cast(dict[str, Any], json.loads(_extract_assistant_text(response)))
