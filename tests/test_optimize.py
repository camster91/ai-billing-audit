"""Tests for the optimization loop driver (src/optimize.py).

Acceptance coverage
-------------------
1. ``run_optimization`` writes a 3-line JSONL file when run for 3
   rounds (matches sibling task t_027cc958 acceptance).
2. ``run_optimization`` honors ``max_budget`` (zero budget => no
   history, no crash; positive budget caps the loop).
3. ``run_optimization`` honors ``max_rounds`` and never exceeds it.
4. ``run_optimization`` returns the best-by-F1 ``(prompt_hash, F1)``
   pair, not the final round.
5. ``run_optimization`` short-circuits on convergence.
6. ``has_converged`` returns True for the hand-crafted [0.5, 0.505,
   0.508] case and False for [0.5, 0.52, 0.53] (sibling task
   t_f686c9e2 acceptance).
7. ``compile_and_evaluate`` returns deterministic results for a fixed
   seed.
8. ``append_history`` creates parent directories and refuses to drop
   records silently.
9. ``check_budget`` semantics: max_budget=0 always exhausted,
   max_budget=positive respects the running total.
10. CLI smoke: ``--max-budget 0`` exits 0 with no history written;
    ``--max-budget 5`` exits 0 with history written.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import optimize as opt  # noqa: E402

VAL_PATH = PROJECT_ROOT / "data" / "synth" / "val.json"
OPTIMIZE_PATH = SRC_ROOT / "optimize.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_val_set() -> list[dict]:
    """Three encounters is enough to exercise the loop."""
    return [
        {"encounter_id": "enc_a", "is_flagged": True, "rules": []},
        {"encounter_id": "enc_b", "is_flagged": False, "rules": []},
        {"encounter_id": "enc_c", "is_flagged": True, "rules": []},
    ]


@pytest.fixture
def tmp_log_path(tmp_path: Path) -> Path:
    return tmp_path / "logs" / "optimization_history.jsonl"


@pytest.fixture
def def_config(tiny_val_set: list[dict], tmp_log_path: Path) -> dict:
    return {
        "val_set": tiny_val_set,
        "log_path": tmp_log_path,
        "max_rounds": 3,
        "max_budget": 10.0,
        "cost_per_round": 0.0,
        "seed": 1729,
    }


# ---------------------------------------------------------------------------
# append_history
# ---------------------------------------------------------------------------


class TestAppendHistory:
    def test_writes_one_json_object_per_line(self, tmp_path: Path) -> None:
        path = tmp_path / "h.jsonl"
        for round_idx in range(1, 4):
            opt.append_history(
                {
                    "round": round_idx,
                    "R": 0.5,
                    "P": 0.5,
                    "F1": 0.5,
                    "prompt_hash": "x" * 64,
                    "timestamp": "2026-06-16T18:00:00Z",
                },
                path=path,
            )
        text = path.read_text(encoding="utf-8").splitlines()
        assert len(text) == 3
        for line in text:
            obj = json.loads(line)
            assert {"round", "R", "P", "F1", "prompt_hash", "timestamp"} == set(obj)

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "a" / "b" / "c" / "h.jsonl"
        assert not path.parent.exists()
        opt.append_history(
            {
                "round": 1,
                "R": 0.0,
                "P": 0.0,
                "F1": 0.0,
                "prompt_hash": "0" * 64,
                "timestamp": "2026-06-16T18:00:00Z",
            },
            path=path,
        )
        assert path.exists()

    def test_appends_does_not_truncate(self, tmp_path: Path) -> None:
        path = tmp_path / "h.jsonl"
        base_record = {
            "R": 0.5,
            "P": 0.5,
            "F1": 0.5,
            "prompt_hash": "0" * 64,
            "timestamp": "2026-06-16T18:00:00Z",
        }
        opt.append_history({**base_record, "round": 1}, path=path)
        opt.append_history({**base_record, "round": 2}, path=path)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["round"] == 1
        assert json.loads(lines[1])["round"] == 2

    def test_missing_keys_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "h.jsonl"
        with pytest.raises(ValueError, match="missing required keys"):
            opt.append_history({"round": 1, "R": 0.5}, path=path)


# ---------------------------------------------------------------------------
# has_converged
# ---------------------------------------------------------------------------


class TestHasConverged:
    def test_hand_crafted_converged(self) -> None:
        history = [{"F1": 0.5}, {"F1": 0.505}, {"F1": 0.508}]
        assert opt.has_converged(history) is True

    def test_hand_crafted_not_converged(self) -> None:
        history = [{"F1": 0.5}, {"F1": 0.52}, {"F1": 0.53}]
        assert opt.has_converged(history) is False

    def test_needs_at_least_three_rounds(self) -> None:
        assert opt.has_converged([]) is False
        assert opt.has_converged([{"F1": 0.5}]) is False
        assert opt.has_converged([{"F1": 0.5}, {"F1": 0.6}]) is False

    def test_handles_malformed_entries_gracefully(self) -> None:
        # Non-numeric F1 should not crash; falls back to False.
        assert opt.has_converged([{"F1": "x"}, {"F1": "y"}, {"F1": "z"}]) is False


# ---------------------------------------------------------------------------
# compile_and_evaluate
# ---------------------------------------------------------------------------


class TestCompileAndEvaluate:
    def test_returns_required_keys(self, tiny_val_set: list[dict]) -> None:
        out = opt.compile_and_evaluate(1, tiny_val_set, seed=1729)
        assert {"R", "P", "F1", "prompt_hash"} <= set(out)
        assert isinstance(out["prompt_hash"], str)
        assert len(out["prompt_hash"]) == 64  # sha256 hex

    def test_deterministic_for_fixed_seed(self, tiny_val_set: list[dict]) -> None:
        a = opt.compile_and_evaluate(3, tiny_val_set, seed=1729)
        b = opt.compile_and_evaluate(3, tiny_val_set, seed=1729)
        assert a == b

    def test_different_rounds_yield_different_prompt_hash(
        self, tiny_val_set: list[dict]
    ) -> None:
        a = opt.compile_and_evaluate(1, tiny_val_set, seed=1729)
        b = opt.compile_and_evaluate(2, tiny_val_set, seed=1729)
        assert a["prompt_hash"] != b["prompt_hash"]

    def test_metrics_in_unit_interval(self, tiny_val_set: list[dict]) -> None:
        for r in range(1, 10):
            out = opt.compile_and_evaluate(r, tiny_val_set, seed=1729)
            assert 0.0 <= out["R"] <= 1.0
            assert 0.0 <= out["P"] <= 1.0
            assert 0.0 <= out["F1"] <= 1.0

    def test_empty_val_set_raises(self) -> None:
        with pytest.raises(ValueError, match="val_set must be non-empty"):
            opt.compile_and_evaluate(1, [])


# ---------------------------------------------------------------------------
# check_budget
# ---------------------------------------------------------------------------


class TestCheckBudget:
    def test_zero_budget_always_exhausted(self) -> None:
        assert opt.check_budget(0.0, 0.0) is True

    def test_positive_budget_respects_running_total(self) -> None:
        assert opt.check_budget(0.0, 5.0) is False
        assert opt.check_budget(4.99, 5.0) is False
        assert opt.check_budget(5.0, 5.0) is True
        assert opt.check_budget(100.0, 5.0) is True


# ---------------------------------------------------------------------------
# run_optimization
# ---------------------------------------------------------------------------


class TestRunOptimization:
    def test_writes_three_lines_for_three_rounds(
        self, def_config: dict
    ) -> None:
        opt.run_optimization(def_config)
        log_path: Path = def_config["log_path"]
        text = log_path.read_text(encoding="utf-8").splitlines()
        assert len(text) == 3
        for line in text:
            json.loads(line)  # parseable

    def test_returns_best_by_f1_not_final_round(self, def_config: dict) -> None:
        # Force a non-monotonic trajectory: round 1 high, round 2 low,
        # round 3 mid. The best should be round 1, not round 3.
        sequence = [
            {"R": 0.9, "P": 0.9, "F1": 0.9, "prompt_hash": "1" * 64},
            {"R": 0.4, "P": 0.4, "F1": 0.4, "prompt_hash": "2" * 64},
            {"R": 0.6, "P": 0.6, "F1": 0.6, "prompt_hash": "3" * 64},
        ]
        idx = {"i": 0}

        def fake_compile(round_idx, val_set, **kwargs):
            return sequence[idx["i"] // 1] if idx["i"] < len(sequence) else sequence[-1]

        # The above closure needs to advance properly per round; redo it
        # cleanly so the test is unambiguous.
        calls = {"i": 0}

        def compile_and_evaluate_fn(round_idx, val_set, **kwargs):
            i = calls["i"]
            calls["i"] += 1
            return sequence[i]

        best = opt.run_optimization(
            def_config, compile_and_evaluate_fn=compile_and_evaluate_fn
        )
        assert best is not None
        prompt_hash, f1 = best
        assert prompt_hash == "1" * 64
        assert f1 == pytest.approx(0.9)
        assert calls["i"] == 3

    def test_zero_budget_returns_none_no_history(
        self, def_config: dict
    ) -> None:
        def_config["max_budget"] = 0.0
        # Use a counter so we can assert compile_and_evaluate was never called.
        calls = {"i": 0}

        def compile_and_evaluate_fn(round_idx, val_set, **kwargs):
            calls["i"] += 1
            return {
                "R": 1.0,
                "P": 1.0,
                "F1": 1.0,
                "prompt_hash": "f" * 64,
            }

        result = opt.run_optimization(
            def_config, compile_and_evaluate_fn=compile_and_evaluate_fn
        )
        assert result is None
        assert calls["i"] == 0
        assert not def_config["log_path"].exists()

    def test_max_rounds_is_a_hard_cap(self, def_config: dict) -> None:
        def_config["max_rounds"] = 5
        calls = {"i": 0}

        def compile_and_evaluate_fn(round_idx, val_set, **kwargs):
            calls["i"] += 1
            # F1 keeps moving so convergence never trips.
            return {
                "R": 0.5 + 0.05 * round_idx,
                "P": 0.5 + 0.05 * round_idx,
                "F1": 0.5 + 0.05 * round_idx,
                "prompt_hash": str(round_idx).zfill(64),
            }

        opt.run_optimization(
            def_config, compile_and_evaluate_fn=compile_and_evaluate_fn
        )
        assert calls["i"] == 5
        lines = def_config["log_path"].read_text().splitlines()
        assert len(lines) == 5

    def test_budget_cap_short_circuits(self, def_config: dict) -> None:
        def_config["max_rounds"] = 100
        def_config["max_budget"] = 2.0
        def_config["cost_per_round"] = 1.0
        calls = {"i": 0}

        def compile_and_evaluate_fn(round_idx, val_set, **kwargs):
            calls["i"] += 1
            return {
                "R": 0.5,
                "P": 0.5,
                "F1": 0.5,
                "prompt_hash": str(round_idx).zfill(64),
            }

        opt.run_optimization(
            def_config, compile_and_evaluate_fn=compile_and_evaluate_fn
        )
        # spent after round 1 = 1.0, round 2 = 2.0, round 3 = 3.0 -> exits at 3.
        # 1.0 < 2.0 (continue), 2.0 >= 2.0 (exit), so 2 rounds ran.
        assert calls["i"] == 2
        lines = def_config["log_path"].read_text().splitlines()
        assert len(lines) == 2

    def test_convergence_short_circuits(self, def_config: dict) -> None:
        # F1 stops moving after round 1 -> convergence should fire on round 3.
        def_config["max_rounds"] = 20
        calls = {"i": 0}

        def compile_and_evaluate_fn(round_idx, val_set, **kwargs):
            i = calls["i"]
            calls["i"] += 1
            return {
                "R": 0.5,
                "P": 0.5,
                "F1": 0.5 + i * 0.001,  # delta < 0.01 each step
                "prompt_hash": str(i).zfill(64),
            }

        opt.run_optimization(
            def_config, compile_and_evaluate_fn=compile_and_evaluate_fn
        )
        # Round 1: history=[r1], no convergence check possible.
        # Round 2: history=[r1,r2], still only 2 entries, no convergence.
        # Round 3: history=[r1,r2,r3], deltas 0.001 and 0.001 -> convergence.
        # Loop exits at end of round 3. So 3 rounds ran, 3 lines written.
        assert calls["i"] == 3
        lines = def_config["log_path"].read_text().splitlines()
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


class TestCLI:
    def test_max_budget_zero_exits_zero_no_history(
        self, tmp_path: Path
    ) -> None:
        log_path = tmp_path / "h.jsonl"
        result = subprocess.run(
            [
                sys.executable,
                str(OPTIMIZE_PATH),
                "--max-budget",
                "0",
                "--max-rounds",
                "100",
                "--val-set",
                str(VAL_PATH),
                "--out",
                str(log_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, result.stderr
        assert not log_path.exists()

    def test_max_budget_five_runs_and_exits_zero(
        self, tmp_path: Path
    ) -> None:
        log_path = tmp_path / "h.jsonl"
        result = subprocess.run(
            [
                sys.executable,
                str(OPTIMIZE_PATH),
                "--max-budget",
                "5",
                "--max-rounds",
                "10",
                "--val-set",
                str(VAL_PATH),
                "--out",
                str(log_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, result.stderr
        # With cost_per_round=0 (default), 10 rounds should run.
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 10
        # Last line stdout prints the best pair.
        assert "best prompt_hash=" in result.stdout
