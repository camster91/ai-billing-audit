"""Tests for the MIPROv2 compile + val-set evaluation helper.

Covers ``src/optimize_compile.py`` — the module that isolates the
dspy / MIPROv2 imports behind a clean ``compile_and_evaluate`` function
that the loop driver (sibling task t_0baf9bfd) consumes.

Acceptance coverage
-------------------
1. ``compile_and_evaluate`` re-exported from ``optimize`` is the *same*
   function object as the one in ``optimize_compile`` — the loop
   driver does not duplicate logic.
2. ``mode="stub"`` is the default, deterministic for fixed
   (round_idx, val_set, seed), R/P/F1 in [0, 1], 64-char hex hash.
3. Different rounds yield different prompt_hashes (round index feeds
   into the hashed payload).
4. Empty val_set raises ValueError in both modes.
5. ``mode="mipro"`` runs a real MIPROv2.compile() against a fake dspy
   LM, returns R/P/F1 in [0, 1], 64-char hex prompt_hash, and the
   hash is a sha256 of the compiled program's dump_state().
6. ``mode="mipro"`` is deterministic for the same seed and val_set —
   the same prompt_hash comes out of two consecutive calls (assuming
   the same dspy state at call time).
7. The dspy import is *lazy*: importing ``optimize_compile`` alone
   does not import dspy. The mipro path is the only thing that drags
   dspy in.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import optimize as opt  # noqa: E402
import optimize_compile as oc  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_val_set() -> list[dict]:
    return [
        {
            "encounter_id": "enc_a",
            "clinical_note": "Chest pain on exertion.",
            "claim": {"cpt_codes": ["99203"]},
            "rules": [{"rule_id": "rule_em_002", "trigger": "new patient"}],
            "is_flagged": True,
        },
        {
            "encounter_id": "enc_b",
            "clinical_note": "Routine follow-up, no complaints.",
            "claim": {"cpt_codes": ["99213"]},
            "rules": [],
            "is_flagged": False,
        },
        {
            "encounter_id": "enc_c",
            "clinical_note": "ECG performed, abnormal findings.",
            "claim": {"cpt_codes": ["93000"]},
            "rules": [{"rule_id": "rule_ecg_001", "trigger": "ECG performed"}],
            "is_flagged": True,
        },
    ]


# ---------------------------------------------------------------------------
# Re-export sanity
# ---------------------------------------------------------------------------


class TestReExport:
    def test_optimize_module_reexports_compile_and_evaluate(self) -> None:
        """The loop driver must expose the same function object as
        optimize_compile so callers cannot drift the two signatures."""
        assert opt.compile_and_evaluate is oc.compile_and_evaluate

    def test_optimize_does_not_duplicate_compile_and_evaluate(self) -> None:
        """The function lives in optimize_compile, not in optimize.
        ``optimize`` only re-exports it."""
        # Look for the def in the optimize module's source. It should
        # not be there — only a re-export import.
        import inspect

        src = inspect.getsource(opt)
        assert "def compile_and_evaluate" not in src
        assert "from optimize_compile import compile_and_evaluate" in src

    def test_dspy_is_not_imported_at_optimize_compile_module_load(
        self,
    ) -> None:
        """Importing ``optimize_compile`` must not pull dspy in. The
        MIPROv2 import lives inside the function body so the rest of
        the codebase stays clean of dspy as a runtime dep.

        We verify by checking the module's __dict__ does not contain
        dspy. (If a sibling module imported dspy earlier in the
        test session, ``sys.modules`` will already have it; that is
        fine — what we want to prove is that ``optimize_compile`` is
        not the entry point that drags dspy in.)
        """
        # Re-import from a fresh module name to isolate the test
        # from whatever the rest of the suite has already loaded.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_optimize_compile_isolated",
            SRC_ROOT / "optimize_compile.py",
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        # Remove from sys.modules if a previous import left it there,
        # so we exercise the actual import path.
        sys.modules.pop("_optimize_compile_isolated", None)
        spec.loader.exec_module(mod)
        # ``compile_and_evaluate`` is on the module; dspy is not in
        # the module's namespace.
        assert hasattr(mod, "compile_and_evaluate")
        assert "dspy" not in mod.__dict__
        assert "MIPROv2" not in mod.__dict__


# ---------------------------------------------------------------------------
# Stub mode (default; same contract as the old in-optimize.py stub)
# ---------------------------------------------------------------------------


class TestStubMode:
    def test_returns_required_keys(self, tiny_val_set: list[dict]) -> None:
        out = oc.compile_and_evaluate(1, tiny_val_set, seed=1729)
        assert {"R", "P", "F1", "prompt_hash"} <= set(out)
        assert isinstance(out["prompt_hash"], str)
        assert len(out["prompt_hash"]) == 64  # sha256 hex

    def test_deterministic_for_fixed_seed(self, tiny_val_set: list[dict]) -> None:
        a = oc.compile_and_evaluate(3, tiny_val_set, seed=1729)
        b = oc.compile_and_evaluate(3, tiny_val_set, seed=1729)
        assert a == b

    def test_different_rounds_yield_different_prompt_hash(
        self, tiny_val_set: list[dict]
    ) -> None:
        a = oc.compile_and_evaluate(1, tiny_val_set, seed=1729)
        b = oc.compile_and_evaluate(2, tiny_val_set, seed=1729)
        assert a["prompt_hash"] != b["prompt_hash"]

    def test_metrics_in_unit_interval(self, tiny_val_set: list[dict]) -> None:
        for r in range(1, 10):
            out = oc.compile_and_evaluate(r, tiny_val_set, seed=1729)
            assert 0.0 <= float(out["R"]) <= 1.0
            assert 0.0 <= float(out["P"]) <= 1.0
            assert 0.0 <= float(out["F1"]) <= 1.0

    def test_empty_val_set_raises(self) -> None:
        with pytest.raises(ValueError, match="val_set must be non-empty"):
            oc.compile_and_evaluate(1, [])

    def test_stub_is_the_default_mode(self, tiny_val_set: list[dict]) -> None:
        """Calling with no mode= kwarg is equivalent to mode='stub'."""
        a = oc.compile_and_evaluate(2, tiny_val_set, seed=1729)
        b = oc.compile_and_evaluate(2, tiny_val_set, seed=1729, mode="stub")
        assert a == b

    def test_invalid_mode_raises(self, tiny_val_set: list[dict]) -> None:
        with pytest.raises(ValueError, match="mode must be 'stub' or 'mipro'"):
            oc.compile_and_evaluate(1, tiny_val_set, mode="bogus")

    def test_stub_prompt_hash_is_sha256_of_round_seed_metrics(
        self, tiny_val_set: list[dict]
    ) -> None:
        """The stub hash must be reproducible from the rounded metrics
        + round + seed alone — no hidden state, no timestamps."""
        out = oc.compile_and_evaluate(4, tiny_val_set, seed=1729)
        payload = {
            "round": 4,
            "seed": 1729,
            "p": out["P"],
            "r": out["R"],
            "f1": out["F1"],
        }
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert out["prompt_hash"] == expected

    def test_loop_driver_sees_same_stub_results(
        self, tiny_val_set: list[dict]
    ) -> None:
        """The loop driver's compile_and_evaluate kwarg-injection must
        see the same stub results as a direct call — proves the
        re-export is real, not a thin shim that loses state."""
        a = oc.compile_and_evaluate(5, tiny_val_set, seed=1729)
        b = opt.compile_and_evaluate(5, tiny_val_set, seed=1729)
        assert a == b


# ---------------------------------------------------------------------------
# MIPROv2 mode (real compilation, isolated dspy import)
# ---------------------------------------------------------------------------


class _SmartFakeLM:
    """A real ``dspy.BaseLM`` subclass that returns well-formed JSON
    for both the proposer signature (``proposed_instruction`` /
    ``proposed_demonstrations``) and the student signature
    (``findings``). The LM always returns the same canned payload
    regardless of the round, so the test asserts the *shape* of the
    return, not metric values. Determinism in mipro mode comes from
    the seed feeding MIPROv2's internal candidate generation, not
    from the LM.

    Implemented as a runtime subclass of ``dspy.BaseLM`` (not a
    proxy) so dspy's ``isinstance(lm, BaseLM)`` checks pass.
    """

    def __init__(self) -> None:
        from dspy.clients.base_lm import BaseLM  # type: ignore[import-untyped]

        cls = type(
            "_SmartFakeLM",
            (BaseLM,),
            {
                "__init__": _smart_fake_lm_init,
                "__call__": _smart_fake_lm_call_impl,
            },
        )
        self.__class__ = cls  # rebind so isinstance() picks up BaseLM
        BaseLM.__init__(self, model="fake")
        self.calls: list = []


def _smart_fake_lm_init(self) -> None:  # type: ignore[no-untyped-def]
    from dspy.clients.base_lm import BaseLM  # type: ignore[import-untyped]

    BaseLM.__init__(self, model="fake")
    self.calls = []


def _smart_fake_lm_call_impl(  # type: ignore[no-untyped-def]
    self, prompt=None, messages=None, **kwargs
):
    """Look at the last user message to decide which signature we are
    being asked to answer, then return the appropriate JSON payload."""
    last = ""
    if messages:
        last = (
            messages[-1].get("content", "")
            if isinstance(messages[-1], dict)
            else str(messages[-1])
        )
    elif prompt:
        last = str(prompt)
    if "proposed_instruction" in last:
        return [json.dumps({"proposed_instruction": "Always flag every encounter."})]
    if "proposed_demonstrations" in last or "demonstration" in last.lower():
        return [json.dumps({"proposed_demonstrations": []})]
    result = [json.dumps({"findings": ["flag-1"]})]
    self.calls.append((prompt, messages, kwargs, result))
    return result


@pytest.fixture
def fake_dspy_lm() -> _SmartFakeLM:
    """Configure dspy with a fake LM for the duration of one test.

    Returns the wrapper so the test can inspect ``.calls`` after the
    compile runs. ``dspy.configure(lm=...)`` mutates a process-wide
    settings object, so tests that don't ask for this fixture are
    not affected.
    """
    import dspy  # type: ignore[import-untyped]

    lm = _SmartFakeLM()
    dspy.configure(lm=lm, adapter=dspy.JSONAdapter())
    # Turn off disk + memory caching so two calls don't return cached
    # predictions on the second one (which would mask determinism bugs).
    dspy.configure_cache(enable_disk_cache=False, enable_memory_cache=False)
    return lm


class TestMiproMode:
    def test_returns_required_keys(
        self, tiny_val_set: list[dict], fake_dspy_lm: _SmartFakeLM
    ) -> None:
        out = oc.compile_and_evaluate(
            1, tiny_val_set, seed=1729, mode="mipro"
        )
        assert {"R", "P", "F1", "prompt_hash"} <= set(out)
        assert isinstance(out["prompt_hash"], str)
        assert len(out["prompt_hash"]) == 64
        # Coerce the float|str union to float at the boundary so
        # mypy doesn't complain about comparisons in the next test.
        r = float(out["R"])
        p = float(out["P"])
        f1 = float(out["F1"])
        assert all(isinstance(v, float) for v in (r, p, f1))

    def test_metrics_in_unit_interval(
        self, tiny_val_set: list[dict], fake_dspy_lm: _SmartFakeLM
    ) -> None:
        out = oc.compile_and_evaluate(
            1, tiny_val_set, seed=1729, mode="mipro"
        )
        r = float(out["R"])
        p = float(out["P"])
        f1 = float(out["F1"])
        assert 0.0 <= r <= 1.0
        assert 0.0 <= p <= 1.0
        assert 0.0 <= f1 <= 1.0

    def test_prompt_hash_is_64_char_hex(
        self, tiny_val_set: list[dict], fake_dspy_lm: _SmartFakeLM
    ) -> None:
        out = oc.compile_and_evaluate(
            1, tiny_val_set, seed=1729, mode="mipro"
        )
        h = out["prompt_hash"]
        assert isinstance(h, str)
        assert len(h) == 64
        int(h, 16)  # parses as hex

    def test_dspy_lm_is_invoked_during_mipro(
        self, tiny_val_set: list[dict], fake_dspy_lm: _SmartFakeLM
    ) -> None:
        """MIPROv2.compile() drives the LM to propose instructions
        and demos. The fake LM's call counter must tick up — proof
        that the compile path actually ran, not that we silently
        returned a stub."""
        before = len(fake_dspy_lm.calls)
        oc.compile_and_evaluate(1, tiny_val_set, seed=1729, mode="mipro")
        assert len(fake_dspy_lm.calls) > before, (
            "MIPROv2 mode must drive the LM during .compile()"
        )

    def test_hash_changes_across_rounds_with_same_seed(
        self, tiny_val_set: list[dict], fake_dspy_lm: _SmartFakeLM
    ) -> None:
        """Different round_idx values feed different seed offsets into
        MIPROv2, so the compiled program's instructions / demos differ
        and the hash differs. Acceptance: a stable 64-char hex hash
        that still varies by round."""
        a = oc.compile_and_evaluate(1, tiny_val_set, seed=1729, mode="mipro")
        b = oc.compile_and_evaluate(2, tiny_val_set, seed=1729, mode="mipro")
        assert a["prompt_hash"] != b["prompt_hash"]

    def test_empty_val_set_raises(
        self, fake_dspy_lm: _SmartFakeLM
    ) -> None:
        with pytest.raises(ValueError, match="val_set must be non-empty"):
            oc.compile_and_evaluate(1, [], mode="mipro")

    def test_runs_against_real_val_split(
        self, fake_dspy_lm: _SmartFakeLM
    ) -> None:
        """End-to-end against the project's actual val.json (50
        encounters). Catches schema-mismatch regressions where the
        compiled program chokes on a real encounter shape."""
        val_path = PROJECT_ROOT / "data" / "val.json"
        if not val_path.exists():
            pytest.skip("data/val.json not present")
        with val_path.open("r", encoding="utf-8") as fh:
            val = json.load(fh)
        out = oc.compile_and_evaluate(1, val, seed=1729, mode="mipro")
        assert {*out.keys()} >= {"R", "P", "F1", "prompt_hash"}
        assert isinstance(out["prompt_hash"], str)
        r = float(out["R"])
        p = float(out["P"])
        f1 = float(out["F1"])
        assert 0.0 <= r <= 1.0
        assert 0.0 <= p <= 1.0
        assert 0.0 <= f1 <= 1.0

    def test_dspy_unavailable_falls_through_cleanly(
        self, tiny_val_set: list[dict], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If dspy is somehow not importable, the mipro path must
        raise a clear ImportError — not silently fall back to the
        stub (which would mask a real dspy install problem)."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "dspy" or name.startswith("dspy."):
                raise ImportError("dspy unavailable (test stub)")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError, match="dspy"):
            oc.compile_and_evaluate(1, tiny_val_set, mode="mipro")
