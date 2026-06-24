"""LLM access layer.

All LLM calls in this package MUST go through this module. The rest of the
codebase must never import provider SDKs (openai, anthropic, cohere, ...) directly.
The active backend is selected by the ``LLM_PROVIDER`` environment variable and
configured via ``LLM_API_KEY`` / ``LLM_BASE_URL`` (and any other provider-specific
companion vars that litellm recognises). See README.md for the full contract.

Public surface:
    LLMClient
        The single class the rest of the codebase depends on. Encapsulates
        the env-var reading, provider dispatch, and JSON-mode reasoning.
        It is a regular class (not a module of free functions) so callers
        can pass a fake implementation into ``run_audit(..., llm=fake)`` for
        unit testing without monkeypatching the process environment.

        LLMClient is intentionally lightweight: it is the *only* object in
        the package that calls into litellm. Every other module imports
        LLMClient and nothing else from this module.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

import litellm

__all__ = ["LLMClient", "provider", "default_model", "PINNED_DEFAULT_MODEL", "SchemaValidationError"]

# Pinned default model id.
#
# This is the SINGLE place to change when bumping the default model that
# ``default_model()`` falls back to. It is intentionally NOT ``"latest"``:
# pinning to a specific id means deterministic builds, reproducible test
# runs, and a loud 404/auth failure from the provider if the id is ever
# removed — rather than a silent swap to a different model that could
# change behaviour and cost without anyone noticing.
#
# To bump: pick the new model id from the provider's model catalog,
# change the string below, update README.md ("Pinned default model")
# and CHANGELOG, then run ``pytest`` and re-run the smoke test in
# ``scripts/optimize.py`` to confirm nothing regressed.
PINNED_DEFAULT_MODEL = "gpt-4o-mini"


def provider() -> str:
    """Return the configured LLM provider name (driven by ``LLM_PROVIDER``)."""
    return os.environ.get("LLM_PROVIDER", "openai")


def default_model() -> str:
    """Return the configured default model (driven by ``LLM_MODEL``).

    Falls back to :data:`PINNED_DEFAULT_MODEL` when ``LLM_MODEL`` is unset.
    """
    return os.environ.get("LLM_MODEL", PINNED_DEFAULT_MODEL)


def _default_complete(**kwargs: Any) -> Any:
    """Default completion closure: dispatch through litellm."""
    return litellm.completion(**kwargs)


class LLMClient:
    """Vendor-neutral LLM client.

    All LLM calls in the package must use this class. A default-constructed
    instance reads ``LLM_PROVIDER`` / ``LLM_MODEL`` / ``LLM_API_KEY`` from
    the process environment and routes through ``litellm.completion``.

    Tests can construct ``LLMClient(complete=fn)`` to inject a fake
    completion function — the fake receives the same ``messages`` and
    keyword arguments the real backend would receive, and is expected to
    return a dict in the litellm/OpenAI response shape:

        {
            "choices": [{"message": {"content": "<json string>"}}],
            "usage": {...},
        }

    Parameters
    ----------
    complete:
        Optional completion function. Defaults to a closure over
        ``litellm.completion`` that reads the model name from
        ``LLM_MODEL`` (or :data:`PINNED_DEFAULT_MODEL`) on each call.
        The closure is captured at construction time; to pick up a
        changed ``LLM_MODEL`` mid-process, construct a new LLMClient.
    model:
        Optional explicit model override. When ``None``, ``LLM_MODEL`` is
        consulted on each call.
    """

    def __init__(
        self,
        *,
        complete: Callable[..., Any] | None = None,
        model: str | None = None,
        timeout: float | None = 60.0,
    ) -> None:
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be a positive number of seconds; got {timeout!r}")
        self._model_override = model
        self._timeout = timeout
        self._complete: Callable[..., Any] = complete if complete is not None else _default_complete

    def _resolve_model(self, kwargs: dict[str, Any]) -> str:
        """Pick a model name: explicit override > LLM_MODEL env > PINNED_DEFAULT_MODEL."""
        if self._model_override is not None:
            return self._model_override
        if "model" in kwargs:
            return kwargs["model"]
        return default_model()

    def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Any:
        """Dispatch a chat completion through the configured backend."""
        kwargs.setdefault("model", self._resolve_model(kwargs))
        # Pass through LLM_BASE_URL as api_base so litellm knows
        # where to dial. Without this, litellm falls back to its
        # default for the provider, which for ollama is
        # localhost:11434 (refused inside the container).
        if "api_base" not in kwargs:
            base = os.environ.get("LLM_BASE_URL")
            if base:
                kwargs["api_base"] = base
        # Map LLM_API_KEY → api_key if the caller didn't set one.
        # Many providers (Ollama, OpenRouter, OpenAI-compatible
        # gateways) read the key from the env when api_key is not
        # passed explicitly; setting it here makes LLMClient match
        # that contract.
        if "api_key" not in kwargs:
            key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
            if key:
                kwargs["api_key"] = key
        # T0.AC (2026-06-18): for the openai provider pointing at Ollama
        # cloud (https://ollama.com/v1), litellm routes the call to
        # /v1/chat/completions as expected. But if a caller passes
        # api_base without model prefix, the model name must already
        # include the "openai/" prefix. This block normalises that.
        model = kwargs.get("model", "")
        if model and "/" not in model:
            kwargs["model"] = "openai/" + model
        if self._timeout is not None and "timeout" not in kwargs:
            kwargs["timeout"] = self._timeout
        return self._complete(messages=messages, **kwargs)

    def complete_json(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Dispatch a chat completion and parse the response as JSON.

        The schema is forwarded to the backend as ``response_format`` so
        providers that support constrained decoding return a JSON object
        directly. The ``message.content`` of the first choice is then
        ``json.loads``'d and locally validated against ``json_schema`` before
        being returned — a model that emits a non-conformant object raises
        :class:`SchemaValidationError` instead of letting the mis-shape
        escape to callers.
        """
        import json
        import jsonschema

        # If the caller passed OpenAI's legacy ``{"type": "json_object"}``
        # envelope instead of a real JSON Schema, there's nothing to
        # validate against. Skip the local check rather than crashing.
        if "type" in json_schema and "properties" not in json_schema:
            response = self.complete(messages, response_format=json_schema, **kwargs)
            content = response["choices"][0]["message"]["content"]
            return json.loads(content)

        # Constrained-decoding envelope: tell the provider the shape we want
        # AND validate the result locally. Belt-and-braces — a model that
        # ignores the constraint (or a provider that doesn't honour it) is
        # caught by the jsonschema.validate call below.
        json_schema_envelope = {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": json_schema},
        }
        response = self.complete(messages, response_format=json_schema_envelope, **kwargs)
        content = response["choices"][0]["message"]["content"]
        # Strip markdown fences if the model wraps the JSON in ```json ... ```
        # (common with reasoning models and some local servers). Without
        # this, json.loads raises on the first ``` line. Fixes BUG-LLM-02.
        if content is not None:
            fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
            if fence_match:
                content = fence_match.group(1).strip()
        parsed = json.loads(content)
        # Normalize severity to lowercase BEFORE jsonschema validation.
        # Different models echo back "CRITICAL" vs "critical"; the schema
        # enum is lowercase. We lowercase the field on every finding
        # so a model that wrote "CRITICAL" gets accepted and the rest
        # of the audit pipeline (which assumes lowercase) stays simple.
        if isinstance(parsed, dict) and isinstance(parsed.get("findings"), list):
            for f in parsed["findings"]:
                if isinstance(f, dict) and isinstance(f.get("severity"), str):
                    f["severity"] = f["severity"].strip().lower()
        try:
            jsonschema.validate(instance=parsed, schema=json_schema)
        except jsonschema.ValidationError as exc:
            raise SchemaValidationError(
                f"LLM response did not conform to the requested JSON schema: {exc.message}"
            ) from exc
        return parsed


class SchemaValidationError(ValueError):
    """Raised by :meth:`LLMClient.complete_json` when the model output fails
    local JSON Schema validation.

    This is a *defence-in-depth* error: providers that support constrained
    decoding (OpenAI ``json_schema`` mode, Anthropic structured outputs)
    should never trigger it, but it catches the case where the provider
    doesn't honour the constraint or the model emits a malformed object
    anyway. Callers that want to retry on a validation failure can catch
    this error specifically and decide whether to fall back to a different
    backend.
    """
