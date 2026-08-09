"""Thin OpenAI SDK wrapper that targets the official MiniMax OpenAI-compatible endpoint.

Source for base URL: https://platform.minimax.io/docs/api-reference/text-openai-api
(MiniMax official API docs, "OpenAI SDK" section). The documented env-var recipe is::

    export OPENAI_BASE_URL=https://api.minimax.io/v1
    export OPENAI_API_KEY=${YOUR_API_KEY}

MiniMax's OpenAI-compatible surface uses Bearer auth, so the standard
``openai`` Python client works unchanged once ``base_url`` is pointed at
``https://api.minimax.io/v1``. The default model id (``MiniMax-M3``) is the
current generation M3 chat model exposed on that endpoint.

This module is intentionally minimal: it only wraps the bits the rest of
this package needs (default model + default temperature + env-var auth) so
that test code can monkeypatch ``MiniMaxClient`` with a fake transport
without dragging in the real ``openai`` SDK at import time.

Public surface:
    MiniMaxClient
        ``MiniMaxClient()`` reads ``OPENAI_API_KEY`` from the environment
        and constructs an :class:`openai.OpenAI` client pinned to
        ``https://api.minimax.io/v1``. ``MiniMaxClient.chat(messages)``
        issues a chat completion request with ``model=MiniMax-M3`` and
        ``temperature=0`` (overridable per call) and returns the raw SDK
        response object.

        For unit tests, pass ``MiniMaxClient(transport=fake)``; the fake
        must expose a ``create(**kwargs)`` method that returns an object
        shaped like ``openai.types.chat.ChatCompletion``.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Optional

try:  # pragma: no cover - import path differs by openai SDK version
    from openai import APIError, OpenAI
except ImportError as _exc:  # pragma: no cover - guard for missing dep
    OpenAI = None  # type: ignore[misc,assignment]
    APIError = None  # type: ignore[misc,assignment]
    _IMPORT_ERROR: Optional[ImportError] = _exc
else:
    _IMPORT_ERROR = None

from ai_billing_audit.minimax_errors import (
    MINIMAX_MAX_ATTEMPTS,
    MiniMaxError,
    compute_backoff,
    should_retry,
    translate_sdk_exception,
)

__all__ = ["MiniMaxClient", "MINIMAX_BASE_URL", "MINIMAX_DEFAULT_MODEL"]

#: Official MiniMax OpenAI-compatible base URL.
#: Source: https://platform.minimax.io/docs/api-reference/text-openai-api
MINIMAX_BASE_URL = "https://api.minimax.io/v1"

#: Default chat model id on the MiniMax OpenAI-compatible endpoint.
#: Pinned to the M3 generation model per the task spec.
MINIMAX_DEFAULT_MODEL = "MiniMax-M3"

#: Default temperature for reproducible runs.
DEFAULT_TEMPERATURE = 0


class MiniMaxClient:
    """OpenAI-SDK-compatible client pinned to the MiniMax endpoint.

    Parameters
    ----------
    api_key:
        Bearer token. Defaults to ``$OPENAI_API_KEY`` for compatibility with
        MiniMax's documented setup. Pass explicitly in tests.
    base_url:
        Override the MiniMax base URL. Defaults to :data:`MINIMAX_BASE_URL`.
        Set to e.g. ``"http://localhost:9999/v1"`` for a local mock server.
    transport:
        Inject a fake transport for unit tests. The fake must expose
        ``chat.completions.create(**kwargs)`` and return an object whose
        ``.choices[0].message.content`` is the assistant reply. When set,
        no real ``openai.OpenAI`` client is constructed and the ``openai``
        SDK does not need to be importable for the test to run.

    Notes
    -----
    ``MiniMaxClient()`` with no arguments is the canonical construction.
    The model id and temperature default are intentionally pinned so
    downstream callers can rely on reproducibility without remembering to
    pass them.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = MINIMAX_BASE_URL,
        transport: Any = None,
        timeout: Optional[float] = 60.0,
    ) -> None:
        if timeout is not None and timeout <= 0:
            raise ValueError(
                f"timeout must be a positive number of seconds; got {timeout!r}"
            )
        self._api_key = (
            api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        )
        self._base_url = base_url
        self._transport = transport
        self._timeout = timeout
        self._client: Any = None
        if transport is None:
            if _IMPORT_ERROR is not None:
                raise _IMPORT_ERROR
            if not self._api_key:
                raise RuntimeError(
                    "MiniMaxClient requires OPENAI_API_KEY in the environment "
                    "or pass api_key= explicitly. Set it to your MiniMax API key "
                    "(https://platform.minimax.io)."
                )
            # The OpenAI SDK reads OPENAI_API_KEY / OPENAI_BASE_URL from the
            # process env when not passed positionally, so we only forward
            # api_key here and let base_url flow through the constructor.
            self._client = OpenAI(
                api_key=self._api_key, base_url=self._base_url, timeout=timeout
            )

    @property
    def base_url(self) -> str:
        """The resolved base URL the client is pinned to."""
        return self._base_url

    def chat(
        self,
        messages: Iterable[dict],
        *,
        model: str = MINIMAX_DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        **kwargs: Any,
    ) -> Any:
        """Issue a chat completion request and return the raw SDK response.

        Parameters
        ----------
        messages:
            Iterable of OpenAI-shaped message dicts (``{"role": ..., "content": ...}``).
            The list is materialised once before being sent so the caller's
            generator is not consumed lazily.
        model:
            Model id; defaults to :data:`MINIMAX_DEFAULT_MODEL` (``MiniMax-M3``).
        temperature:
            Sampling temperature; defaults to :data:`DEFAULT_TEMPERATURE` (0)
            for reproducibility. Per OpenAI's spec the valid range is ``[0, 2]``.
        **kwargs:
            Forwarded verbatim to ``chat.completions.create`` (e.g.
            ``max_tokens``, ``top_p``, ``response_format``, ``stream``).

        Raises
        ------
        ai_billing_audit.minimax_errors.MiniMaxAuthError
            On HTTP 401/403 (no retry — fix the API key).
        ai_billing_audit.minimax_errors.MiniMaxRateLimitError
            On HTTP 429 after the retry budget is exhausted.
        ai_billing_audit.minimax_errors.MiniMaxServerError
            On HTTP 5xx after the retry budget is exhausted.
        ai_billing_audit.minimax_errors.MiniMaxError
            For any other OpenAI SDK error that escapes the transport.

        See :mod:`ai_billing_audit.minimax_errors` for the full retry
        policy (exponential backoff with full jitter, ``MINIMAX_MAX_ATTEMPTS``
        total attempts, sleep injected via ``minimax_errors._sleep`` for
        tests).
        """
        materialised = list(messages)
        if not materialised:
            raise ValueError("messages must be a non-empty list of message dicts")
        if not (0.0 <= float(temperature) <= 2.0):
            raise ValueError(f"temperature must be in [0, 2]; got {temperature!r}")

        target = self._transport if self._transport is not None else self._client
        return self._call_with_retry(
            target,
            model=model,
            messages=materialised,
            temperature=temperature,
            **kwargs,
        )

    def _call_with_retry(
        self,
        target: Any,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        **kwargs: Any,
    ) -> Any:
        """Issue the chat completion, retrying transient errors with backoff.

        Retries up to :data:`MINIMAX_MAX_ATTEMPTS` total attempts.  Only
        :func:`should_retry` failures (HTTP 429 and 5xx) are retried; the
        rest are translated into the project-local hierarchy via
        :func:`translate_sdk_exception` and raised.  Sleeping is delegated
        to the module-level ``_sleep`` in :mod:`ai_billing_audit.minimax_errors`
        so unit tests can run instantly.
        """
        # Late import keeps the module importable even if the openai SDK
        # is missing — the test that injects a transport will never reach
        # this code path.
        from ai_billing_audit.minimax_errors import _sleep

        last_sdk_exc: BaseException | None = None
        for attempt in range(1, MINIMAX_MAX_ATTEMPTS + 1):
            try:
                # When the caller injected a transport (test path) the
                # transport is the raw SDK stub and does not have a
                # ``timeout`` constructor arg; pass it through only when
                # the target is a real openai.OpenAI client, so existing
                # tests that don't construct with timeout keep working.
                call_kwargs = dict(kwargs)
                if (
                    target is self._client
                    and self._timeout is not None
                    and "timeout" not in call_kwargs
                ):
                    call_kwargs["timeout"] = self._timeout
                return target.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    **call_kwargs,
                )
            except BaseException as exc:  # noqa: BLE001 - we re-raise translated
                # The transport/SDK raised. Decide whether to retry, and
                # if not, translate to the project hierarchy.
                if (
                    APIError is not None
                    and isinstance(exc, APIError)
                    and should_retry(exc)
                ):
                    last_sdk_exc = exc
                    if attempt < MINIMAX_MAX_ATTEMPTS:
                        _sleep(compute_backoff(attempt))
                        continue
                    # Out of attempts on a retryable error — translate
                    # to the project hierarchy and raise.
                    raise translate_sdk_exception(exc) from exc
                # Not retryable. Translate (or re-raise if not even an
                # OpenAI SDK error) and surface to caller.
                if APIError is not None and isinstance(exc, APIError):
                    raise translate_sdk_exception(exc) from exc
                # Non-SDK exception (e.g. a fake transport that raises
                # a built-in or arbitrary error). Preserve the original.
                raise
        # Defensive — the loop above always either returns or raises.
        if last_sdk_exc is not None:
            raise translate_sdk_exception(last_sdk_exc) from last_sdk_exc
        raise MiniMaxError("MiniMaxClient.chat: retry loop exited without a result")
