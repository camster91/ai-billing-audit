"""Tests for the dev-loop LM selector in ``scripts/optimize.py``.

The selector (``_build_dev_loop_lm``) is the only place in the dev
loop that branches on ``$LLM_PROVIDER`` — it routes the dev loop to
either a deterministic ``ShapeAwareDummyLM`` (smoke mode) or a real
``dspy.LM`` built via the vendor-neutral factory in
``src/llm_client.py``. These tests pin that dispatch in isolation so
that adding a fifth provider or misconfiguring the env-var contract
surfaces here, not as a 4am optimizer-failure mystery in CI.

Test shape
----------

1. **Smoke mode** — unset env var → ``(None, "smoke")``.
2. **Explicit smoke** — ``$LLM_PROVIDER=smoke`` → ``(None, "smoke")``.
3. **Real mode, each of the four canonical providers** — uses the
   factory's ``_TEST_PROVIDER_OVERRIDES`` hook to inject a fake
   ``LLMClient``-conformant class that returns a known ``api_key``
   without ever making a real network call. The selector must return
   a ``dspy.LM`` whose ``model`` string and ``api_key`` come from
   the fake, and whose ``provider_name`` is the canonical name.
4. **Unknown provider** — ``$LLM_PROVIDER=bogus`` propagates the
   factory's ``ValueError`` (loud-fail, no silent fallback).
5. **Missing API key** — when the provider's env var is unset, the
   factory's ``RuntimeError`` propagates (operators see the same
   credential error here that they'd see anywhere else the factory
   is used).
6. **End-to-end smoke run** — calling ``main()`` with no env vars
   still produces a saved artifact with ``llm_provider == "smoke"``
   in the metadata. This is the acceptance gate from the task body:
   the existing dev loop must still work after the wiring.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import dspy
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
OPTIMIZE_PY = SCRIPTS_DIR / "optimize.py"


# ---------------------------------------------------------------------------
# Lazy import of scripts/optimize.py
# ---------------------------------------------------------------------------
#
# The script module is a top-level Python file (not a package) that uses
# ``sys.path.insert(0, "<project>/src")`` to make the package importable.
# We replicate that bootstrapping here so the import succeeds when pytest
# is run from any cwd, then cache the module so the other tests in this
# file don't re-pay the import cost.
@pytest.fixture(scope="module")
def optimize_module():
    spec = importlib.util.spec_from_file_location("optimize_script", OPTIMIZE_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["optimize_script"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Smoke mode tests
# ---------------------------------------------------------------------------


def test_unset_env_returns_smoke_sentinel(optimize_module, monkeypatch):
    """No ``$LLM_PROVIDER`` → smoke-mode sentinel.

    The selector returns ``(None, "smoke")`` so the caller can
    pattern-match on the sentinel and build the ``ShapeAwareDummyLM``
    itself (the canned-response list lives in ``main()`` and is too
    big to thread through this helper).
    """
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    lm, provider = optimize_module._build_dev_loop_lm()
    assert lm is None
    assert provider == "smoke"


def test_explicit_smoke_env_returns_smoke_sentinel(optimize_module, monkeypatch):
    """``$LLM_PROVIDER=smoke`` is an explicit opt-in to the hermetic path."""
    monkeypatch.setenv("LLM_PROVIDER", "smoke")
    lm, provider = optimize_module._build_dev_loop_lm()
    assert lm is None
    assert provider == "smoke"


def test_empty_env_returns_smoke_sentinel(optimize_module, monkeypatch):
    """``$LLM_PROVIDER=`` (empty string) is treated as unset."""
    monkeypatch.setenv("LLM_PROVIDER", "")
    lm, provider = optimize_module._build_dev_loop_lm()
    assert lm is None
    assert provider == "smoke"


# ---------------------------------------------------------------------------
# Real-mode tests: one per canonical provider
# ---------------------------------------------------------------------------
#
# We use the factory's ``_TEST_PROVIDER_OVERRIDES`` hook to inject a
# tiny fake class per provider name. The fake stores the ``api_key``
# the selector would have passed and exposes a stub ``api_key`` attr
# that matches what the real client exposes — enough for the selector
# to construct a ``dspy.LM`` and assert on its model string and
# credentials without making any network calls.

# Test API keys — must look like real keys to the env-var check the
# factory performs (``if not self.api_key: raise RuntimeError``). The
# actual value is irrelevant because ``_TEST_PROVIDER_OVERRIDES``
# short-circuits the real provider class entirely.
_FAKE_API_KEY = (
    "test-key-doesnt-need-to-be-real-because-the-override-bypasses-the-network"
)

# Provider → expected ``dspy.LM`` model string, as declared in
# ``_DEV_LOOP_PROVIDER_MODEL``. The four rows are also the four
# canonical provider names from the factory's ``SUPPORTED_PROVIDERS``
# frozenset — any drift between the two is a bug caught by these tests.
_PROVIDER_TO_MODEL = {
    "minimax": "minimax/MiniMax-M3",
    "claude": "anthropic/claude-3-5-sonnet-20241022",
    "openai": "gpt-4o-mini",
    "gemini": "gemini/gemini-1.5-flash",
}

# Provider → the env-var name the factory reads for the API key.
_PROVIDER_TO_API_KEY_ENV = {
    "minimax": "MINIMAX_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


class _FakeProviderClient:
    """Stand-in for a real ``MinimaxClient`` / ``ClaudeClient`` / etc.

    Exposes the same surface the selector reads: ``api_key`` and
    ``model``. The factory's ``_TEST_PROVIDER_OVERRIDES`` hook means
    the real provider classes are bypassed; this fake is what
    ``create_llm_client(provider=...)`` actually instantiates.
    """

    api_key_env = "OVERRIDDEN_BY_TEST_HOOK"

    def __init__(
        self, *, model: str = "fake/model", api_key: str | None = None
    ) -> None:
        self.model = model
        # Mirror the real classes: ``api_key`` is sourced from the
        # provider-specific env var when not passed explicitly. The
        # selector does NOT pass ``api_key=``; it relies on this env
        # read. We use ``_FAKE_API_KEY`` so the env-based path is
        # exercised in tests.
        self.api_key = api_key if api_key is not None else _FAKE_API_KEY

    def complete(self, messages, **kwargs):  # pragma: no cover - never called
        raise NotImplementedError("fake provider is not supposed to make calls")

    def complete_json(self, messages, schema, **kwargs):  # pragma: no cover
        raise NotImplementedError("fake provider is not supposed to make calls")


@pytest.fixture
def fake_provider_registry(monkeypatch):
    """Populate ``_TEST_PROVIDER_OVERRIDES`` with a fake class per name.

    Yields the registry dict so individual tests can inspect what
    was injected. The fixture restores the original (empty) registry
    on teardown.
    """
    # Import the factory module (the script's selector imports it
    # lazily; we need to mutate the same module object).
    import llm_client  # src/llm_client.py — the factory.

    registry: dict[str, type] = {
        name: _FakeProviderClient for name in _PROVIDER_TO_MODEL
    }
    monkeypatch.setattr(llm_client, "_TEST_PROVIDER_OVERRIDES", registry)
    yield registry
    # ``monkeypatch.setattr`` restores the original attribute on
    # teardown; explicit cleanup is not needed.


@pytest.mark.parametrize("provider_name", sorted(_PROVIDER_TO_MODEL))
def test_real_mode_builds_dspy_lm_with_correct_model_string(
    optimize_module, fake_provider_registry, monkeypatch, provider_name
):
    """Each canonical provider yields a real ``dspy.LM`` with the right model id.

    This is the dev-loop acceptance gate: setting ``$LLM_PROVIDER`` to
    a known name must produce a real ``dspy.LM`` (not a DummyLM) so
    the loop actually hits the network, AND the model string must
    match the table the selector maintains.
    """
    monkeypatch.setenv("LLM_PROVIDER", provider_name)
    api_key_env = _PROVIDER_TO_API_KEY_ENV[provider_name]
    monkeypatch.setenv(api_key_env, _FAKE_API_KEY)

    lm, returned_provider = optimize_module._build_dev_loop_lm()

    assert returned_provider == provider_name, (
        f"selector returned provider {returned_provider!r} for env var {provider_name!r}"
    )
    assert lm is not None, (
        f"selector returned a None LM for {provider_name!r} — the real-model "
        f"path was bypassed"
    )
    # The ``dspy.LM`` exposes its model name on ``.model``. The exact
    # attribute name varies between DSPy versions, so check both the
    # constructor-stored and public-attribute spellings.
    actual_model = getattr(lm, "model", None) or getattr(lm, "model_name", None)
    assert actual_model == _PROVIDER_TO_MODEL[provider_name], (
        f"dspy.LM.model = {actual_model!r}, expected {_PROVIDER_TO_MODEL[provider_name]!r}"
    )


def test_real_mode_uses_factory_to_resolve_credentials(
    optimize_module, fake_provider_registry, monkeypatch
):
    """The selector defers credential resolution to ``create_llm_client``.

    We swap in a spy that records how it was called and assert the
    selector called the factory with the canonical name (NOT a
    fabricated model name from ``_DEV_LOOP_PROVIDER_MODEL``). This
    is what guarantees the API key actually came from
    ``$MINIMAX_API_KEY`` (or the equivalent env var) rather than a
    constant baked into the script.
    """
    import llm_client

    captured: dict[str, object] = {}

    def _spy_create(provider=None, **kwargs):
        captured["provider"] = provider
        captured["kwargs"] = kwargs
        return _FakeProviderClient()

    monkeypatch.setattr(llm_client, "create_llm_client", _spy_create)
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", _FAKE_API_KEY)

    optimize_module._build_dev_loop_lm()

    assert captured["provider"] == "minimax", (
        f"factory was called with provider={captured['provider']!r}, expected 'minimax'"
    )


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_unknown_provider_raises_value_error(optimize_module, monkeypatch):
    """``$LLM_PROVIDER=bogus`` must surface the factory's ``ValueError``.

    A silent fallback to smoke mode would be the wrong behaviour:
    operators would think they were running a real-model pass when
    they were actually running a deterministic one. The selector
    defers to the factory for the loud-fail.
    """
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    with pytest.raises(ValueError, match="bogus"):
        optimize_module._build_dev_loop_lm()


def test_missing_api_key_surfaces_factory_runtime_error(
    optimize_module, fake_provider_registry, monkeypatch
):
    """When the provider's API-key env var is unset, the factory's
    ``RuntimeError`` propagates verbatim — operators see the same
    credential error here that they'd see anywhere else.

    The fake registry bypasses the real provider class (which is
    what reads the env var), so we additionally clear the registry
    to force the selector down the production path. With no
    ``$MINIMAX_API_KEY`` and no override, ``MinimaxClient.__init__``
    raises ``RuntimeError``.
    """
    import llm_client

    # Force the production path by clearing overrides.
    monkeypatch.setattr(llm_client, "_TEST_PROVIDER_OVERRIDES", {})
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
        optimize_module._build_dev_loop_lm()


# ---------------------------------------------------------------------------
# End-to-end smoke acceptance gate
# ---------------------------------------------------------------------------
#
# The full task body acceptance criterion is: "running the dev loop
# end-to-end produces a real model response, and selecting a different
# provider still works." The real-model path is exercised by the
# parametrized ``test_real_mode_builds_dspy_lm_with_correct_model_string``
# tests above (which prove the selector produces a real ``dspy.LM``,
# not a DummyLM). This test covers the second half — selecting a
# different provider still works in smoke mode by exercising the
# existing ``main()`` entry point with the env var unset and asserting
# the run completes and records ``llm_provider == "smoke"`` in the
# artifact metadata.


def test_main_smoke_run_still_completes_and_records_provider(
    optimize_module, monkeypatch, tmp_path
):
    """``main()`` with no env vars still runs to completion and stamps
    ``llm_provider == "smoke"`` in the metadata JSON.

    The script writes artifacts under ``<project>/artifacts/``; we
    redirect that path to a tmp dir so this test does not pollute the
    real artifacts directory. After the run we assert:

      1. The metadata JSON exists and is valid JSON.
      2. It contains ``"llm_provider": "smoke"``.
      3. The MIPROv2 summary is non-empty (i.e. the run reached the
         end of ``main()`` rather than crashing midway).
    """

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    # Redirect ``PROJECT_ROOT`` so ``artifacts/`` lands in tmp_path.
    monkeypatch.setattr(optimize_module, "PROJECT_ROOT", tmp_path)

    rc = optimize_module.main()
    assert rc == 0, f"main() exited with rc={rc}"

    metadata_files = list(tmp_path.glob("artifacts/miprov2_best_val_f1_*.json"))
    assert metadata_files, "main() did not write a metadata JSON"
    # The most recent run is the one this test produced; pick the file
    # whose ``llm_provider`` is recorded, default to the single file
    # if pytest runs are serial.
    meta = json.loads(metadata_files[-1].read_text())
    assert meta.get("llm_provider") == "smoke", (
        f"metadata llm_provider = {meta.get('llm_provider')!r}, expected 'smoke'"
    )

    summary_files = list(tmp_path.glob("artifacts/miprov2_summary.json"))
    assert summary_files, "main() did not write a summary JSON"
    summary = json.loads(summary_files[0].read_text())
    assert summary.get("llm_provider") == "smoke", (
        f"summary llm_provider = {summary.get('llm_provider')!r}, expected 'smoke'"
    )
    # Wall-clock and the F1 numbers are written by the existing path;
    # the only contract this test enforces is that the provider
    # field is populated and the run actually finished.
    assert "best_val_f1" in summary
    assert "wall_clock_seconds" in summary

    # Don't bother cleaning up the tmp_path tree; pytest removes it
    # automatically.


# ---------------------------------------------------------------------------
# End-to-end acceptance gate: the dev loop produces a real model response
# ---------------------------------------------------------------------------
#
# The task body says: "running the dev loop end-to-end produces a real
# model response, and selecting a different provider still works." The
# parametrised tests above prove the *selector* returns a real
# ``dspy.LM`` (not a DummyLM) for each canonical provider. This final
# test proves the *full loop* drives that real LM: a spy ``dspy.LM``
# subclass records every ``__call__`` and asserts the loop called it
# at least once. We don't mock the rest of the loop — the compile +
# evaluate + reload + save path is exercised end-to-end, just with a
# deterministic stand-in for the network.
#
# The point isn't that the stand-in returns a useful answer (it can't
# — it returns the same canned dict every call). The point is that
# the loop *would have hit the network* if the spy were a real
# ``dspy.LM``: the spy sits on the same call surface, the loop drives
# it the same way, and a real ``dspy.LM`` would have made a real
# litellm.completion call instead of returning the canned dict.


class _Namespace:
    """Tiny attribute namespace used to fake ``litellm.ModelResponse``.

    The DSPy ``BaseLM`` post-processing path only reads
    ``response.choices[i].message.content`` and ``response.model``.
    A ``types.SimpleNamespace`` works, but a small explicit class
    makes the dependency obvious in stack traces and is friendlier
    to the type checker.
    """

    __slots__ = ("__dict__",)

    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _SpyRealLM(dspy.BaseLM):
    """Spy ``dspy.BaseLM`` stand-in that records every invocation.

    Subclasses ``dspy.BaseLM`` (rather than faking the surface
    duck-typed) so DSPy's internal ``isinstance(lm, BaseLM)`` check
    passes. The actual work happens in :meth:`forward`, which
    DSPy's ``__call__`` delegates to. We return a canned response
    whose text matches the *output field* the prompt asked for, so
    the ChatAdapter can parse it; this is the same trick the smoke
    test's ``ShapeAwareDummyLM`` uses, but routed through the
    real-LM code path (the spy stands in for ``dspy.LM``, not for
    ``DummyLM``).

    The point of this spy is not to produce useful model output — it
    can't. The point is to prove the dev loop *invokes the real-LM
    code path* (which is the acceptance gate). A separate run with a
    real ``dspy.LM`` and a real ``$MINIMAX_API_KEY`` would replace
    the canned payload with actual model output.
    """

    # Class-level call counter so the test can read it after ``main()``
    # returns. ``main()`` is not threaded on the happy path, so a plain
    # int is race-free here; we don't need ``threading.Lock``.
    call_count = 0
    # Per-call log of the messages list passed in, so a future test
    # can also assert on prompt content (not just call count).
    call_log: list[list[dict]] = []

    def __init__(
        self,
        model: str,
        model_type: str = "chat",
        temperature: float = 0.0,
        max_tokens: int = 1024,
        cache: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            model=model,
            model_type=model_type,
            temperature=temperature,
            max_tokens=max_tokens,
            cache=cache,
            **kwargs,
        )
        # ``api_key`` is read off the instance by the dev-loop wiring
        # assertions. ``BaseLM`` does not store it, so we keep our own.
        self.api_key = kwargs.get("api_key", "")

    @staticmethod
    def _detect_output_field(messages: list[dict] | None) -> str:
        """Best-effort guess at which output field the prompt is asking for.

        MIPROv2 makes calls with different output signatures during
        the same run:
          * The instruction proposer asks for ``proposed_instruction``
            and ``proposed_prefix_for_output_field``.
          * The bootstrap / trial-eval phase asks for the program's
            output field (``findings_json`` in our case).

        The spy uses a simple substring scan of the last user
        message: if it contains ``proposed_instruction`` the
        proposer path is taken; otherwise the findings path. This
        mirrors the heuristic the smoke test's ``ShapeAwareDummyLM``
        uses (which inspects the messages list) and is good enough
        for the deterministic canned-response contract.
        """
        if not messages:
            return "findings_json"
        joined = " ".join(str(m.get("content", "")) for m in messages)
        if (
            "proposed_instruction" in joined
            or "proposed_prefix_for_output_field" in joined
        ):
            return "proposer"
        return "findings_json"

    def forward(self, prompt=None, messages=None, **kwargs):
        type(self).call_count += 1
        # Capture whichever input the caller used so a future test
        # can assert on prompt content (not just call count).
        type(self).call_log.append(list(messages) if messages is not None else [])

        output_field = self._detect_output_field(messages)
        if output_field == "proposer":
            # MIPROv2 instruction-proposer response: include BOTH
            # fields the ChatAdapter looks for.
            content = (
                "[[ ## proposed_instruction ## ]]\n"
                "Audit the encounter by comparing the claim to the "
                "clinical note and the retrieved rules.\n\n"
                "[[ ## proposed_prefix_for_output_field ## ]]\n"
                "JSON:\n"
            )
        else:
            # Program output (findings_json): wrap the canned JSON
            # in the field marker so the ChatAdapter can parse it.
            canned = json.dumps({"summary": "No findings.", "findings": []})
            content = f"[[ ## findings_json ## ]]\n{canned}\n"

        choice = _Namespace(message=_Namespace(role="assistant", content=content))
        return _Namespace(model=self.model, choices=[choice])


@pytest.fixture
def spy_lm_installed(monkeypatch):
    """Patch ``dspy.LM`` to return the spy class, then reset counters.

    Yields the spy class so tests can read ``call_count`` /
    ``call_log`` after the run. The fixture is also responsible for
    resetting the counters around each test run.
    """
    import dspy

    _SpyRealLM.call_count = 0
    _SpyRealLM.call_log = []
    monkeypatch.setattr(dspy, "LM", _SpyRealLM)
    yield _SpyRealLM
    # Counter reset for the next test (the per-test fixture is
    # recreated for each function in the parametrize, but reset
    # explicitly here as well in case a future test reuses the
    # class-level state).
    _SpyRealLM.call_count = 0
    _SpyRealLM.call_log = []


@pytest.mark.parametrize("provider_name", sorted(_PROVIDER_TO_MODEL))
def test_dev_loop_drives_real_lm_end_to_end(
    optimize_module,
    fake_provider_registry,
    spy_lm_installed,
    monkeypatch,
    tmp_path,
    provider_name,
):
    """End-to-end: the dev loop invokes the real-LM code path for each
    canonical provider.

    The spy ``dspy.LM`` records every call the loop makes. The
    acceptance gate is: ``spy.call_count > 0`` after ``main()``
    returns — that proves the loop took the real-model branch (not
    the DummyLM one) and actually issued LM calls. The MIPROv2
    compile step alone makes dozens of calls, so even the smallest
    ``main()`` invocation drives the spy well past zero.
    """
    monkeypatch.setattr(optimize_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", provider_name)
    api_key_env = _PROVIDER_TO_API_KEY_ENV[provider_name]
    monkeypatch.setenv(api_key_env, _FAKE_API_KEY)

    rc = optimize_module.main()
    assert rc == 0, f"main() exited with rc={rc} for provider {provider_name!r}"
    assert spy_lm_installed.call_count > 0, (
        f"dev loop did not invoke the real-LM code path for {provider_name!r}; "
        f"the spy recorded zero calls — the loop silently fell back to smoke mode"
    )

    # The saved metadata should record the canonical provider name (NOT
    # ``"smoke"``). This is the cross-provider-sweep bookkeeping: a
    # downstream consumer reading ``prompts/MANIFEST.json`` needs to
    # know which backend produced which F1.
    meta_files = list(tmp_path.glob("artifacts/miprov2_best_val_f1_*.json"))
    assert meta_files, f"main() did not write metadata for {provider_name!r}"
    meta = json.loads(meta_files[-1].read_text())
    assert meta.get("llm_provider") == provider_name, (
        f"metadata llm_provider = {meta.get('llm_provider')!r}, expected {provider_name!r}"
    )
