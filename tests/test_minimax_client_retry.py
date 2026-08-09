"""Acceptance tests for the MiniMax retry + exception-translation layer.

These tests cover the contract in the task body:

1. SDK exceptions are translated into the project-local hierarchy
   (:class:`MiniMaxError` and its subclasses).
2. 429 and 5xx trigger an exponential-backoff retry; success after
   429 is the headline acceptance test.
3. 401/403 hard-fail with a message pointing at ``$OPENAI_API_KEY``.
4. Other errors propagate through the translator.
5. Sleeping is injected (no real ``time.sleep`` in tests).

Sleeping is stubbed via the module-level ``_sleep`` in
:mod:`ai_billing_audit.minimax_errors`, and the recorded backoff
values are inspected to confirm the policy is correct.
"""

from __future__ import annotations

import httpx
import pytest

from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
)

import ai_billing_audit.minimax_errors as errs
from ai_billing_audit.minimax_client import MiniMaxClient
from ai_billing_audit.minimax_errors import (
    MINIMAX_BACKOFF_BASE_SECONDS,
    MINIMAX_BACKOFF_CAP_SECONDS,
    MINIMAX_BACKOFF_FACTOR,
    MINIMAX_MAX_ATTEMPTS,
    MiniMaxAuthError,
    MiniMaxError,
    MiniMaxRateLimitError,
    MiniMaxServerError,
    compute_backoff,
    should_retry,
    translate_sdk_exception,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        # A queue of either exceptions to raise or responses to return,
        # consumed in order.  ``None`` means "use default response".
        self.queue: list[object] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.queue:
            raise AssertionError(
                "_FakeCompletions.create called more times than queued responses"
            )
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeTransport:
    """Mimics the surface of ``openai.OpenAI`` that ``MiniMaxClient`` uses."""

    def __init__(self) -> None:
        self.chat = _FakeChat()


def _status_error(
    message: str, status_code: int, body: object = None
) -> APIStatusError:
    """Build a real ``openai.APIStatusError`` for the given status code."""
    request = httpx.Request("POST", "https://api.minimax.io/v1/chat/completions")
    response = httpx.Response(
        status_code,
        request=request,
        headers={"x-request-id": f"req_test_{status_code}"},
    )
    cls = {
        401: AuthenticationError,
        403: PermissionDeniedError,
        404: APIStatusError,
        429: RateLimitError,
        500: APIStatusError,
        502: APIStatusError,
        503: APIStatusError,
        400: BadRequestError,
    }[status_code]
    return cls(message, response=response, body=body)


# ---------------------------------------------------------------------------
# Pytest fixture: swap the module-level sleep for a recording stub
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_sleep(monkeypatch):
    """Replace ``minimax_errors._sleep`` with a recording no-op.

    Tests that exercise the retry loop inject this fixture and then
    inspect ``fake_sleep.calls`` to verify the backoff schedule.
    """
    calls: list[float] = []

    def _record(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr(errs, "_sleep", _record)
    return calls


# ---------------------------------------------------------------------------
# Constants and policy
# ---------------------------------------------------------------------------


def test_max_attempts_is_three() -> None:
    """The retry budget is exactly 3 total attempts (1 + 2 retries)."""
    assert MINIMAX_MAX_ATTEMPTS == 3


def test_backoff_grows_then_caps() -> None:
    """Backoff upper bound doubles per attempt and caps at the configured max."""
    # Sample several times to be robust to jitter; assert the cap holds.
    for _ in range(50):
        # Attempt 1 -> base seconds
        assert 0.0 <= compute_backoff(1) <= MINIMAX_BACKOFF_BASE_SECONDS + 1e-9
        # Attempt 2 -> base * factor
        upper_2 = MINIMAX_BACKOFF_BASE_SECONDS * MINIMAX_BACKOFF_FACTOR
        assert 0.0 <= compute_backoff(2) <= upper_2 + 1e-9
        # Attempt 3 -> base * factor^2, but capped
        raw_3 = MINIMAX_BACKOFF_BASE_SECONDS * (MINIMAX_BACKOFF_FACTOR**2)
        upper_3 = min(raw_3, MINIMAX_BACKOFF_CAP_SECONDS)
        assert 0.0 <= compute_backoff(3) <= upper_3 + 1e-9
    # And confirm the cap kicks in for an absurdly large attempt
    assert 0.0 <= compute_backoff(20) <= MINIMAX_BACKOFF_CAP_SECONDS + 1e-9


def test_should_retry_only_for_429_and_5xx() -> None:
    """``should_retry`` returns True only for 429 and 5xx."""
    assert should_retry(_status_error("rl", 429)) is True
    assert should_retry(_status_error("ise", 500)) is True
    assert should_retry(_status_error("bad gw", 502)) is True
    assert should_retry(_status_error("unavail", 503)) is True
    # 4xx (other than 429) and non-APIStatusError are not retryable
    assert should_retry(_status_error("auth", 401)) is False
    assert should_retry(_status_error("forbid", 403)) is False
    assert should_retry(_status_error("bad req", 400)) is False
    assert should_retry(_status_error("not found", 404)) is False
    # Non-APIStatusError
    assert (
        should_retry(APIConnectionError(request=httpx.Request("GET", "http://x")))
        is False
    )
    assert should_retry(ValueError("boom")) is False


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


def test_translate_401_raises_auth_error_pointing_at_env_var() -> None:
    """A 401 maps to ``MiniMaxAuthError`` whose message names the env var."""
    exc = _status_error("nope", 401)
    translated = translate_sdk_exception(exc)
    assert isinstance(translated, MiniMaxAuthError)
    assert isinstance(translated, MiniMaxError)
    assert "OPENAI_API_KEY" in str(translated)
    assert "401" in str(translated)
    assert translated.__cause__ is exc


def test_translate_403_raises_auth_error_pointing_at_env_var() -> None:
    """A 403 also maps to ``MiniMaxAuthError`` (not retryable)."""
    exc = _status_error("forbidden", 403)
    translated = translate_sdk_exception(exc)
    assert isinstance(translated, MiniMaxAuthError)
    assert "OPENAI_API_KEY" in str(translated)
    assert "403" in str(translated)
    assert translated.__cause__ is exc


def test_translate_429_raises_rate_limit_error() -> None:
    """A 429 maps to ``MiniMaxRateLimitError``."""
    exc = _status_error("slow down", 429)
    translated = translate_sdk_exception(exc)
    assert isinstance(translated, MiniMaxRateLimitError)
    assert "429" in str(translated)
    assert translated.__cause__ is exc


def test_translate_5xx_raises_server_error() -> None:
    """A 500 maps to ``MiniMaxServerError`` with the status code in the message."""
    exc = _status_error("ise", 500)
    translated = translate_sdk_exception(exc)
    assert isinstance(translated, MiniMaxServerError)
    assert "500" in str(translated)
    assert translated.__cause__ is exc


def test_translate_400_falls_through_to_base_error() -> None:
    """A 400 is translated to the base ``MiniMaxError`` (not a specific subclass)."""
    exc = _status_error("bad", 400)
    translated = translate_sdk_exception(exc)
    assert type(translated) is MiniMaxError
    assert translated.__cause__ is exc


# ---------------------------------------------------------------------------
# Retry behaviour: the headline acceptance test
# ---------------------------------------------------------------------------


def test_429_then_200_eventually_succeeds(fake_sleep) -> None:
    """The headline acceptance test: 429 then 200, asserts eventual success.

    With ``MINIMAX_MAX_ATTEMPTS = 3`` the loop tries three times; the
    first two raise 429, the third returns 200.  ``fake_sleep`` is
    inspected to confirm the backoff was called between retries.
    """
    fake = _FakeTransport()
    fake.chat.completions.queue = [
        _status_error("rl", 429),
        _status_error("rl", 429),
        "ok-response",
    ]
    client = MiniMaxClient(transport=fake)
    response = client.chat([{"role": "user", "content": "ping"}])

    # The third attempt returned the string we queued.
    assert response == "ok-response"
    assert len(fake.chat.completions.calls) == 3
    # Backoff was slept twice (between attempt 1->2 and 2->3), not after 3.
    assert len(fake_sleep) == 2
    # All sleeps are within the configured upper bounds.
    for slept, attempt in zip(fake_sleep, [1, 2]):
        upper = min(
            MINIMAX_BACKOFF_CAP_SECONDS,
            MINIMAX_BACKOFF_BASE_SECONDS * (MINIMAX_BACKOFF_FACTOR ** (attempt - 1)),
        )
        assert 0.0 <= slept <= upper + 1e-9


def test_500_then_200_eventually_succeeds(fake_sleep) -> None:
    """5xx is also retried; a single 500 then 200 should succeed on attempt 2."""
    fake = _FakeTransport()
    fake.chat.completions.queue = [
        _status_error("ise", 500),
        "ok-response",
    ]
    client = MiniMaxClient(transport=fake)
    response = client.chat([{"role": "user", "content": "ping"}])

    assert response == "ok-response"
    assert len(fake.chat.completions.calls) == 2
    assert len(fake_sleep) == 1


def test_repeated_429_exhausts_budget_then_raises_translated(
    monkeypatch, fake_sleep
) -> None:
    """If every attempt 429s, the loop raises ``MiniMaxRateLimitError`` after
    the third attempt.  No sleep after the final attempt.
    """
    fake = _FakeTransport()
    fake.chat.completions.queue = [
        _status_error("rl", 429),
        _status_error("rl", 429),
        _status_error("rl", 429),
    ]
    client = MiniMaxClient(transport=fake)

    with pytest.raises(MiniMaxRateLimitError) as excinfo:
        client.chat([{"role": "user", "content": "ping"}])

    # The original SDK exception is attached as __cause__.
    assert isinstance(excinfo.value.__cause__, RateLimitError)
    # Three total attempts, two sleeps (no sleep after the final failure).
    assert len(fake.chat.completions.calls) == 3
    assert len(fake_sleep) == 2


def test_repeated_500_exhausts_budget_then_raises_translated(fake_sleep) -> None:
    """Same shape for 5xx -> ``MiniMaxServerError``."""
    fake = _FakeTransport()
    fake.chat.completions.queue = [
        _status_error("ise", 500),
        _status_error("bad gw", 502),
        _status_error("unavail", 503),
    ]
    client = MiniMaxClient(transport=fake)

    with pytest.raises(MiniMaxServerError) as excinfo:
        client.chat([{"role": "user", "content": "ping"}])

    assert isinstance(excinfo.value.__cause__, APIStatusError)
    assert excinfo.value.__cause__.status_code == 503
    assert len(fake.chat.completions.calls) == 3


# ---------------------------------------------------------------------------
# Hard-fail behaviour
# ---------------------------------------------------------------------------


def test_401_does_not_retry_and_raises_auth_error(fake_sleep) -> None:
    """A 401 must NOT be retried; it raises ``MiniMaxAuthError`` immediately."""
    fake = _FakeTransport()
    fake.chat.completions.queue = [_status_error("bad key", 401)]
    client = MiniMaxClient(transport=fake)

    with pytest.raises(MiniMaxAuthError) as excinfo:
        client.chat([{"role": "user", "content": "ping"}])

    # Single attempt, no sleep.
    assert len(fake.chat.completions.calls) == 1
    assert fake_sleep == []
    # Message is actionable.
    assert "OPENAI_API_KEY" in str(excinfo.value)
    assert "401" in str(excinfo.value)
    # Original SDK exception preserved as __cause__.
    assert isinstance(excinfo.value.__cause__, AuthenticationError)


def test_403_does_not_retry_and_raises_auth_error(fake_sleep) -> None:
    """A 403 must NOT be retried; it raises ``MiniMaxAuthError`` immediately."""
    fake = _FakeTransport()
    fake.chat.completions.queue = [_status_error("forbidden", 403)]
    client = MiniMaxClient(transport=fake)

    with pytest.raises(MiniMaxAuthError) as excinfo:
        client.chat([{"role": "user", "content": "ping"}])

    assert len(fake.chat.completions.calls) == 1
    assert fake_sleep == []
    assert "OPENAI_API_KEY" in str(excinfo.value)
    assert "403" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, PermissionDeniedError)


# ---------------------------------------------------------------------------
# Other error behaviour
# ---------------------------------------------------------------------------


def test_400_does_not_retry_and_raises_base_error(fake_sleep) -> None:
    """A 400 is not retried; it propagates as the base ``MiniMaxError``."""
    fake = _FakeTransport()
    fake.chat.completions.queue = [_status_error("malformed", 400)]
    client = MiniMaxClient(transport=fake)

    with pytest.raises(MiniMaxError) as excinfo:
        client.chat([{"role": "user", "content": "ping"}])

    # Not retried.
    assert len(fake.chat.completions.calls) == 1
    assert fake_sleep == []
    # The base class, not a specific subclass.
    assert type(excinfo.value) is MiniMaxError
    assert isinstance(excinfo.value.__cause__, BadRequestError)


def test_network_error_is_translated_to_base_error(fake_sleep) -> None:
    """An ``APIConnectionError`` is still an OpenAI SDK exception, so it is
    translated to the base ``MiniMaxError`` and re-raised.  It is NOT
    retried (only 429 and 5xx are).
    """
    fake = _FakeTransport()
    request = httpx.Request("GET", "http://localhost:1234/v1")
    network_exc = APIConnectionError(request=request)
    fake.chat.completions.queue = [network_exc]
    client = MiniMaxClient(transport=fake)

    with pytest.raises(MiniMaxError) as excinfo:
        client.chat([{"role": "user", "content": "ping"}])

    # Single attempt, no sleep, and the original SDK exception is
    # preserved as __cause__.
    assert len(fake.chat.completions.calls) == 1
    assert fake_sleep == []
    assert isinstance(excinfo.value.__cause__, APIConnectionError)


def test_non_sdk_exception_is_not_translated(fake_sleep) -> None:
    """A plain ``RuntimeError`` from a fake transport is preserved verbatim."""
    fake = _FakeTransport()
    boom = RuntimeError("transport exploded")
    fake.chat.completions.queue = [boom]
    client = MiniMaxClient(transport=fake)

    with pytest.raises(RuntimeError, match="transport exploded"):
        client.chat([{"role": "user", "content": "ping"}])

    assert len(fake.chat.completions.calls) == 1
    assert fake_sleep == []


# ---------------------------------------------------------------------------
# Package re-exports
# ---------------------------------------------------------------------------


def test_errors_are_re_exported_from_package_root() -> None:
    """The exception types and helpers are importable from ``ai_billing_audit``."""
    import ai_billing_audit

    assert ai_billing_audit.MiniMaxError is MiniMaxError
    assert ai_billing_audit.MiniMaxAuthError is MiniMaxAuthError
    assert ai_billing_audit.MiniMaxRateLimitError is MiniMaxRateLimitError
    assert ai_billing_audit.MiniMaxServerError is MiniMaxServerError
    assert ai_billing_audit.translate_sdk_exception is translate_sdk_exception
    assert ai_billing_audit.should_retry is should_retry
    assert ai_billing_audit.compute_backoff is compute_backoff
    assert ai_billing_audit.MINIMAX_MAX_ATTEMPTS == MINIMAX_MAX_ATTEMPTS
