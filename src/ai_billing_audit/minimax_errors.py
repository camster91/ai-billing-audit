"""Project-local exception hierarchy for ``MiniMaxClient`` and retry policy.

The OpenAI Python SDK raises a tree of exceptions rooted at
``openai.OpenAIError``.  Several of those correspond to situations that
``MiniMaxClient`` callers want to handle differently:

* :class:`openai.AuthenticationError` (HTTP 401) and
  :class:`openai.PermissionDeniedError` (HTTP 403) — bad API key. There
  is nothing to retry; the user must fix their credentials.
* :class:`openai.RateLimitError` (HTTP 429) and the 5xx server errors
  (``APIStatusError`` with ``status_code >= 500``) — transient. The
  call should be retried with exponential backoff.
* Everything else (network errors, 4xx other than 401/403/429, JSON
  decode failures) — propagate as-is so the caller decides.

This module provides:

* A small exception hierarchy rooted at :class:`MiniMaxError` with
  three named subclasses that callers can ``except`` directly.
* :func:`translate_sdk_exception` which maps an OpenAI SDK exception
  onto the project hierarchy.  The original SDK exception is attached
  as ``__cause__`` for debugging.
* :func:`should_retry` — a single decision function used by
  ``MiniMaxClient.chat``'s retry loop.
* :func:`compute_backoff` — exponential backoff with full jitter, the
  policy the retry loop uses.  Pulled out as a module-level function
  so unit tests can pin it without monkeypatching ``time.sleep``.

Retry policy
------------

* Max attempts: 3 (1 initial + 2 retries).
* Retryable: HTTP 429 and HTTP 5xx.
* Non-retryable: HTTP 401, HTTP 403, and everything else.
* Backoff: exponential with full jitter, base 0.5s, factor 2.0,
  cap 8.0s.  Attempt N (1-indexed) waits ``random.uniform(0, min(cap, base * factor**(N-1)))``
  before the next try.

Sleeping is injected via the ``_sleep`` module attribute (default
``time.sleep``) so tests can run instantly by swapping it for a no-op.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

try:  # pragma: no cover - import path differs by openai SDK version
    from openai import (
        APIError,
        APIStatusError,
        AuthenticationError,
        OpenAIError,
        PermissionDeniedError,
        RateLimitError,
    )
except ImportError:  # pragma: no cover - guard for missing dep
    # If the openai SDK isn't importable we still want this module to
    # import so unit tests that don't exercise the SDK can run.  The
    # real client (``MiniMaxClient``) raises its own import error
    # earlier if the SDK is missing.
    OpenAIError = APIError = APIStatusError = object  # type: ignore[assignment,misc]
    AuthenticationError = PermissionDeniedError = RateLimitError = object  # type: ignore[assignment,misc]


__all__ = [
    "MiniMaxError",
    "MiniMaxAuthError",
    "MiniMaxRateLimitError",
    "MiniMaxServerError",
    "MINIMAX_MAX_ATTEMPTS",
    "MINIMAX_BACKOFF_BASE_SECONDS",
    "MINIMAX_BACKOFF_FACTOR",
    "MINIMAX_BACKOFF_CAP_SECONDS",
    "translate_sdk_exception",
    "should_retry",
    "compute_backoff",
]


#: Max number of total attempts (1 initial + N-1 retries) before
#: giving up on a transient failure.
MINIMAX_MAX_ATTEMPTS = 3

#: Exponential-backoff base delay, in seconds.  Attempt 1 sees no
#: backoff (it hasn't failed yet); attempt 2 waits a random
#: ``[0, base)`` seconds; attempt 3 waits ``[0, base*factor)`` seconds.
MINIMAX_BACKOFF_BASE_SECONDS = 0.5

#: Exponential-backoff growth factor.  Each retry's upper bound
#: multiplies by this value.
MINIMAX_BACKOFF_FACTOR = 2.0

#: Hard cap on the backoff upper bound, in seconds.
MINIMAX_BACKOFF_CAP_SECONDS = 8.0

#: Module-level sleep function, swappable in tests.
_sleep: Callable[[float], Any] = time.sleep


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class MiniMaxError(RuntimeError):
    """Root of the project-local exception hierarchy.

    All errors raised by :class:`ai_billing_audit.minimax_client.MiniMaxClient`
    are subclasses of this.  Callers that want to catch "anything from
    the MiniMax client" should ``except MiniMaxError``.
    """


class MiniMaxAuthError(MiniMaxError):
    """Raised when the API rejects the credentials (HTTP 401/403).

    This is never retried.  The message always points the user at
    ``$OPENAI_API_KEY`` because that is the env var the MiniMax
    OpenAI-compatible endpoint reads.
    """


class MiniMaxRateLimitError(MiniMaxError):
    """Raised on HTTP 429 after the retry budget is exhausted.

    Individual 429 responses are retried with backoff; this only
    escapes the retry loop if every attempt also 429s.
    """


class MiniMaxServerError(MiniMaxError):
    """Raised on HTTP 5xx after the retry budget is exhausted.

    Same retry behaviour as :class:`MiniMaxRateLimitError`.
    """


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


def _status_code(exc: BaseException) -> int | None:
    """Best-effort extraction of an HTTP status code from an SDK exception."""
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    # Some SDK exceptions don't expose status_code directly; fall back
    # to the response object if attached.
    response = getattr(exc, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def translate_sdk_exception(exc: BaseException) -> MiniMaxError:
    """Translate an OpenAI SDK exception into a :class:`MiniMaxError`.

    Mapping:

    * 401 / 403 -> :class:`MiniMaxAuthError` (with a clear env-var hint)
    * 429 -> :class:`MiniMaxRateLimitError`
    * 5xx -> :class:`MiniMaxServerError`
    * Anything else -> :class:`MiniMaxError` (preserves the message)

    The original SDK exception is attached as ``__cause__`` for
    traceback visibility.
    """
    code = _status_code(exc)

    if code in (401, 403):
        translated: MiniMaxError = MiniMaxAuthError(
            "MiniMax rejected the API key "
            f"(HTTP {code}). Check that $OPENAI_API_KEY is set to a valid "
            "MiniMax key (https://platform.minimax.io). Original error: "
            f"{exc!r}"
        )
    elif code == 429:
        translated = MiniMaxRateLimitError(
            f"MiniMax rate limit hit (HTTP 429). Original error: {exc!r}"
        )
    elif code is not None and 500 <= code < 600:
        translated = MiniMaxServerError(
            f"MiniMax server error (HTTP {code}). Original error: {exc!r}"
        )
    else:
        translated = MiniMaxError(str(exc) or repr(exc))
    translated.__cause__ = exc
    return translated


# ---------------------------------------------------------------------------
# Retry decisions
# ---------------------------------------------------------------------------


def should_retry(exc: BaseException) -> bool:
    """Return True if ``exc`` is a transient failure worth retrying.

    Only 429 and 5xx are retryable.  Auth errors, network errors, and
    4xx other than 429 are NOT retried.
    """
    if not isinstance(exc, APIStatusError):
        # Non-status errors (network failures, parse errors) are not
        # retried here; ``MiniMaxClient`` could be extended to retry
        # ``APIConnectionError`` later, but the task spec only calls
        # out 429 and 5xx.
        return False
    code = exc.status_code
    return code == 429 or 500 <= code < 600


def compute_backoff(attempt: int) -> float:
    """Return the backoff sleep, in seconds, before retry attempt ``attempt``.

    ``attempt`` is 1-indexed and counts the attempt that JUST FAILED.
    So ``compute_backoff(1)`` is the wait before the first retry
    (i.e. before attempt 2), ``compute_backoff(2)`` is the wait before
    the second retry (i.e. before attempt 3).

    Uses full jitter: returns a random uniform in
    ``[0, min(cap, base * factor**(attempt - 1)))``.
    """
    if attempt < 1:
        return 0.0
    upper = MINIMAX_BACKOFF_BASE_SECONDS * (MINIMAX_BACKOFF_FACTOR ** (attempt - 1))
    upper = min(upper, MINIMAX_BACKOFF_CAP_SECONDS)
    return random.uniform(0.0, upper)


def _set_sleep(fn: Callable[[float], Any]) -> None:
    """Test hook: replace the module-level sleep function."""
    global _sleep
    _sleep = fn


def _reset_sleep() -> None:
    """Test hook: restore the default ``time.sleep``."""
    global _sleep
    _sleep = time.sleep
