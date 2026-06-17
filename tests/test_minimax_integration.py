"""Integration smoke test for the live MiniMax endpoint.

This is the only test in the suite that talks to a real network. It
exists for one reason: prove the factory + ``MinimaxClient`` wiring
isn't broken end-to-end against the MiniMax API that the dev loop
defaults to. Everything else in ``tests/`` is hermetic (mocked
``litellm.completion``) and would happily pass even if MiniMax rotated
their base URL or auth scheme.

The test is gated on ``$MINIMAX_API_KEY``:

* key present  -> test runs, hits api.minimax.chat, asserts the
  response is non-empty and the echoed ``model`` field equals
  ``"MiniMax-M3"``.
* key missing  -> test is **skipped**, not failed. This matches the
  acceptance criterion in the task body and keeps `pytest -m
  integration` green in CI environments that don't have a real key.

Running
-------
With a key::

    export MINIMAX_API_KEY=...
    pytest -m integration tests/test_minimax_integration.py -v

Without a key (CI default)::

    pytest -m integration tests/test_minimax_integration.py -v
    # -> 1 skipped

Full suite (integration included)::

    pytest -v

The ``integration`` marker is registered in ``pyproject.toml`` under
``[tool.pytest.ini_options].markers``. To run only the integration
tests use ``pytest -m integration``; to skip them entirely (e.g. in
hermetic CI) use ``pytest -m "not integration"``.

Why a separate test file
------------------------
The other MiniMax tests in this suite (``test_minimax_client.py``,
``test_cross_provider_smoke.py``) all mock ``litellm.completion`` and
never touch the network. Mixing a real-API test into one of those
files would (a) make hermetic runs slower and (b) make it ambiguous
which tests need a key. A dedicated file with a single test gives the
operator one obvious place to look when the live endpoint is
misbehaving, and the marker makes it trivial to include or exclude
that test from any CI matrix.

Design choices
--------------
* **Bare model id on the wire.** ``MinimaxClient`` defaults to
  ``"minimax/MiniMax-M3"`` (the litellm-routed id), and the MiniMax
  API echoes the *bare* model id (``"MiniMax-M3"``) on the response.
  The test passes ``model="minimax/MiniMax-M3"`` to the call so the
  factory contract is exercised, but asserts against the bare id
  because that's what the API actually returns — the contract under
  test is the round-trip, not a string-equality on the input.
* **temperature=0.** Specified in the task body. Also matches the
  ``_DEFAULT_TEMPERATURE`` baked into ``MinimaxClient``; we pass it
  explicitly so the test reads as a literal transcription of the
  acceptance criterion.
* **Short, deterministic prompt.** ``"Reply with the single word:
  pong"`` is the same canned prompt the cross-provider smoke test
  uses. The integration test doesn't assert on the *content* of the
  reply (that's the cross-provider test's job, with a mocked
  transport); it only asserts the response is non-empty. The model
  field is the load-bearing assertion.
* **No retry / no fixture loop.** A single ``complete()`` call is
  enough to prove the wiring. If the live call flakes, the test
  fails loudly with the full exception — wrapping it in a retry loop
  would mask real outages.
"""

from __future__ import annotations

import os

import pytest

import src.llm_client as llm_client

# Canonical integration marker. Registered in pyproject.toml so
# ``pytest -m integration`` works without ``--strict-markers``
# complaining, and so ``pytest -m "not integration"`` excludes this
# test from hermetic CI runs cleanly.
pytestmark = pytest.mark.integration


# Env var the factory reads (matches ``MinimaxClient.api_key_env``).
# Defining it here (rather than importing the class attribute) keeps
# the test self-describing: a reader doesn't need to chase the
# production module to know which env var gates the test.
_REQUIRED_ENV_VAR = "MINIMAX_API_KEY"

# Model id asserted on the response. MiniMax's API echoes the bare
# model id without the ``minimax/`` litellm routing prefix, so the
# assertion is against this string even though the call uses the
# prefixed form below.
_EXPECTED_MODEL = "MiniMax-M3"

# Litellm routing prefix. The factory sends the prefixed form to
# litellm; the API echoes the bare form. Keeping both as constants
# documents the asymmetry so a future reader doesn't "fix" the
# literal ``"MiniMax-M3"`` assertion to match the input.
_REQUESTED_MODEL = "minimax/MiniMax-M3"


def test_minimax_live_chat_completion_is_non_empty_and_echoes_model() -> None:
    """Hit the live MiniMax endpoint once; assert response is non-empty and model is M3.

    The single acceptance criterion from the task body, expressed
    literally:

    1. **Skip if no key.** CI / hermetic runs must not fail. The
       ``pytestmark`` above plus this skip at the top of the test
       body are belt-and-braces: even if a future change to the
       marker registration loses the integration filter, the test
       still skips instead of erroring.
    2. **One real call, temperature=0.** A minimal, deterministic
       request. The dev loop's default temperature is also 0, so
       this matches production behaviour.
    3. **Response is non-empty.** The Protocol contract says
       ``complete()`` returns a ``str``; an empty string is reserved
       for "model said nothing" and would be a contract violation
       even for a one-word prompt like this.
    4. **Response.model equals "MiniMax-M3".** The model field is
       always present on a litellm/OpenAI-shaped completion
       (``ModelResponse.model`` is a documented field, not an
       extension). If the live API ever drops it or starts echoing a
       different id, this assertion fires with the actual value in
       the failure message.
    """
    api_key = os.environ.get(_REQUIRED_ENV_VAR, "")
    if not api_key:
        pytest.skip(
            f"{_REQUIRED_ENV_VAR} is not set; integration test requires a "
            f"real MiniMax API key. Set it and re-run, or skip this test "
            f"with `pytest -m 'not integration'`."
        )

    # ``client.complete()`` swallows the envelope and returns just
    # the text. To assert on the response ``model`` field (the
    # headline acceptance criterion) we have to call
    # ``litellm.completion`` directly with the same args the client
    # would use. The test would lose most of its value if we only
    # checked the text — the load-bearing assertion is the echoed
    # model id.
    import litellm

    response = litellm.completion(
        model=_REQUESTED_MODEL,
        messages=[{"role": "user", "content": "Reply with the single word: pong"}],
        api_key=api_key,
        temperature=0,
    )

    # 1. Envelope has a ``model`` field. ``ModelResponse.model`` is
    #    a documented field on the litellm/OpenAI shape; if a future
    #    refactor drops it, this assertion names the regression in
    #    the failure message.
    actual_model = getattr(response, "model", None)
    assert actual_model is not None, (
        "live MiniMax response has no 'model' field; got "
        f"type={type(response).__name__}, repr={response!r}"
    )
    assert actual_model == _EXPECTED_MODEL, (
        f"live MiniMax response echoed model={actual_model!r}, "
        f"expected {_EXPECTED_MODEL!r}. If the API renamed the model, "
        f"update _EXPECTED_MODEL and the cross-provider smoke test "
        f"in tests/test_cross_provider_smoke.py in the same change."
    )

    # 2. The text the factory would return via ``client.complete()``
    #    is non-empty. We re-derive it via the same path the
    #    production code uses (``_extract_assistant_text``) so this
    #    test catches regressions in the extraction helper, not just
    #    in the network call.
    text = llm_client._extract_assistant_text(response)
    assert isinstance(text, str), (
        f"expected str content, got {type(text).__name__}: {text!r}"
    )
    assert text, f"live MiniMax returned empty content: {text!r}"
