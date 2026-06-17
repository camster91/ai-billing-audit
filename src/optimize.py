"""Optimization loop driver for the ai-billing-audit auditor.

This module wires together a small, thin prompt-optimization loop:

    for round in 1..N:
        result = compile_and_evaluate(round, val_set)  # (R, P, F1, prompt_hash)
        append_history(record, path=log_path)
        if has_converged(history) or budget_exhausted(spend, max_budget):
            break

The loop body in :func:`run_optimization` is intentionally thin. All
work is delegated to four helper functions, each one a leaf operation
so they can be unit-tested in isolation and (eventually) extracted to
their own modules without changing call sites:

* :func:`compile_and_evaluate` — compile the candidate prompt with
  MIPROv2, evaluate it on the val split, and return ``(R, P, F1,
  prompt_hash)``. Implementation lives in
  :mod:`optimize_compile` so the dspy / MIPROv2 imports stay isolated
  from this module. (Sibling task t_0baf9bfd.)
* :func:`append_history` — append a single JSON object per line to
  ``logs/optimization_history.jsonl``. (Sibling task t_027cc958.)
* :func:`has_converged` — pure function that returns ``True`` when
  the last two F1 deltas are each < 0.01. (Sibling task t_f686c9e2.)
* :func:`check_budget` — returns ``True`` when running spend >=
  ``max_budget``. (Sibling task t_b37033e8 — used by the CLI driver
  in :func:`main`.)

The CLI in :func:`main` is the production entrypoint; tests drive
:func:`run_optimization` directly with a fake config and patched
helpers. Exit code 0 on normal completion; 0 also on ``--max-budget
0`` (the loop writes nothing and returns ``None`` as the best pair).

History file format (one JSON object per line)
-----------------------------------------------
Each line is a JSON object with exactly these keys:

    round       int
    R           float
    P           float
    F1          float
    prompt_hash str   (64-char hex sha256 of the compiled prompt)
    timestamp   str   (ISO 8601 UTC, with trailing 'Z')

Append mode only. The file is created (along with any missing parent
directories) on first write. On write failure, :func:`append_history`
raises — it never silently drops a record.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# Re-export the compile-and-evaluate helper so callers that import
# ``optimize`` (the loop driver) see the same name and signature as
# before. The actual implementation — including the isolated
# dspy / MIPROv2 imports — lives in :mod:`optimize_compile` (sibling
# task t_0baf9bfd). Importing it here is safe at module-load time:
# ``optimize_compile`` does not import dspy at import time, only
# inside the mipro path.
from optimize_compile import compile_and_evaluate  # noqa: E402,F401

__all__ = [
    "append_history",
    "check_budget",
    "compile_and_evaluate",
    "has_converged",
    "main",
    "run_optimization",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# ``compile_and_evaluate`` is re-exported from :mod:`optimize_compile` above.
# The historical stub implementation that used to live here has been moved
# to ``optimize_compile._compile_and_evaluate_stub`` and is invoked as the
# default ``mode="stub"`` branch of the public function. The deterministic
# contract (R/P/F1 in [0, 1], 64-char hex prompt_hash, stable for a fixed
# seed + val_set) is preserved.


def append_history(
    record: Mapping[str, Any],
    path: str | Path = "logs/optimization_history.jsonl",
) -> Path:
    """Append ``record`` as a single JSON line to ``path``.

    Creates the parent directory if missing. Append mode only — the
    file is never truncated. Required keys in ``record``:

        round       int
        R           float
        P           float
        F1          float
        prompt_hash str
        timestamp   str   (ISO 8601 UTC)

    Returns the resolved path.

    On write failure, raises — never silently loses a record. (Sibling
    task t_027cc958.)
    """
    required = {"round", "R", "P", "F1", "prompt_hash", "timestamp"}
    missing = required - set(record.keys())
    if missing:
        raise ValueError(f"record is missing required keys: {sorted(missing)}")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(record), sort_keys=True, ensure_ascii=False)
    # ``open(..., "a")`` creates the file if missing. Errors (disk
    # full, permission denied, broken pipe) propagate as exceptions.
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return target


def has_converged(history: Sequence[Mapping[str, Any]]) -> bool:
    """Return ``True`` when the last two F1 deltas are each < 0.01.

    Pure function, no I/O. Needs at least 3 history records to
    evaluate; returns ``False`` otherwise. (Sibling task t_f686c9e2.)

    Acceptance cases (verified by tests/test_optimize.py):

        [0.5, 0.505, 0.508] -> True
        [0.5, 0.52,  0.53]  -> False
    """
    if len(history) < 3:
        return False
    try:
        f1_values = [float(h["F1"]) for h in history[-3:]]
    except (KeyError, TypeError, ValueError):
        return False
    delta_1 = abs(f1_values[-1] - f1_values[-2])
    delta_2 = abs(f1_values[-2] - f1_values[-3])
    return delta_1 < 0.01 and delta_2 < 0.01


def check_budget(
    spent: float,
    max_budget: float,
) -> bool:
    """Return ``True`` when the cumulative spend >= ``max_budget``.

    A ``max_budget`` of 0 is treated as "no budget at all" — the very
    first call returns ``True`` so the loop exits immediately without
    writing any history. (Sibling task t_b37033e8.)
    """
    return float(spent) >= float(max_budget)


# ---------------------------------------------------------------------------
# Loop driver
# ---------------------------------------------------------------------------


def run_optimization(
    config: Mapping[str, Any],
    *,
    compile_and_evaluate_fn: Callable[..., dict[str, Any]] = compile_and_evaluate,
    append_history_fn: Callable[..., Path] = append_history,
    has_converged_fn: Callable[[Sequence[Mapping[str, Any]]], bool] = has_converged,
    check_budget_fn: Callable[[float, float], bool] = check_budget,
) -> tuple[str, float] | None:
    """Run the prompt-optimization loop and return the best ``(prompt_hash, F1)``.

    The loop is intentionally thin: each iteration delegates to the
    four helpers above. The driver is responsible for ordering, best-
    by-F1 tracking, and short-circuiting on convergence or budget.

    Required keys in ``config``:

        val_set        Sequence[Mapping[str, Any]]
        log_path       str | Path
        max_rounds     int
        max_budget     float
        cost_per_round float   (default 0.0; placeholder until sibling t_b37033e8
                               supplies a real cost model)

    Returns ``(prompt_hash, F1)`` for the best round, or ``None`` if
    no rounds were run (e.g. ``max_budget == 0``).
    """
    val_set: Sequence[Mapping[str, Any]] = config["val_set"]
    log_path = Path(config["log_path"])
    max_rounds = int(config["max_rounds"])
    max_budget = float(config["max_budget"])
    cost_per_round = float(config.get("cost_per_round", 0.0))
    train_set: Sequence[Mapping[str, Any]] | None = config.get("train_set")
    seed: int = int(config.get("seed", 1729))

    # ``max_budget == 0`` means the caller wants the loop to do
    # nothing and return None — the CLI contract for --max-budget 0.
    if check_budget_fn(0.0, max_budget):
        return None

    history: list[dict[str, Any]] = []
    best: tuple[str, float] | None = None
    spent = 0.0
    started = time.monotonic()

    for round_idx in range(1, max_rounds + 1):
        result = compile_and_evaluate_fn(
            round_idx, val_set, train_set=train_set, seed=seed
        )
        r_val = float(result["R"])
        p_val = float(result["P"])
        f1_val = float(result["F1"])
        prompt_hash_val = str(result["prompt_hash"])
        record: dict[str, Any] = {
            "round": round_idx,
            "R": r_val,
            "P": p_val,
            "F1": f1_val,
            "prompt_hash": prompt_hash_val,
            "timestamp": _dt.datetime.now(tz=_dt.timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
        }
        append_history_fn(record, log_path)
        history.append(record)
        spent += cost_per_round

        f1 = f1_val
        prompt_hash = prompt_hash_val
        if best is None or f1 > best[1]:
            best = (prompt_hash, f1)

        if has_converged_fn(history):
            break
        if check_budget_fn(spent, max_budget):
            break

    # Silence the unused-binding warning for ``started`` — it's a
    # hook for future wall-clock logging; kept for parity with the
    # pre-existing scripts/optimize.py contract.
    del started
    return best


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="optimize",
        description=(
            "Drive the auditor prompt-optimization loop. Each round "
            "compiles a candidate prompt with MIPROv2, evaluates on "
            "the val split, and appends (round, R, P, F1, prompt_hash) "
            "to the history log. Stops at convergence or when the "
            "budget cap is reached."
        ),
    )
    parser.add_argument(
        "--max-budget",
        type=float,
        default=10.0,
        help="Cumulative USD cap. Loop exits when spend >= this value. "
        "0 means run zero rounds and exit 0 (default: 10.0).",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=50,
        help="Hard cap on optimization rounds (default: 50).",
    )
    parser.add_argument(
        "--val-set",
        type=Path,
        default=Path("data/val.json"),
        help="Path to the val split JSON (default: data/val.json).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("logs/optimization_history.jsonl"),
        help="Path to the JSONL history log (default: logs/optimization_history.jsonl).",
    )
    parser.add_argument(
        "--cost-per-round",
        type=float,
        default=0.0,
        help="Estimated USD cost per round (default: 0.0 placeholder).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1729,
        help="Deterministic seed (default: 1729).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint. Returns a Unix exit code (0 on success)."""
    args = _build_arg_parser().parse_args(argv)

    # Load the val set. For the CLI, we accept either a list of
    # encounters or an object with an "encounters" key (the manifest
    # format). Anything else is a hard error.
    val_path: Path = args.val_set
    if not val_path.exists():
        print(f"val set not found: {val_path}", file=sys.stderr)
        return 2
    with val_path.open("r", encoding="utf-8") as fh:
        val_doc = json.load(fh)
    if isinstance(val_doc, list):
        val_set: Sequence[Mapping[str, Any]] = val_doc
    elif isinstance(val_doc, dict) and isinstance(val_doc.get("encounters"), list):
        val_set = val_doc["encounters"]
    else:
        print(
            f"val set must be a list or {{'encounters': [...]}}; got {type(val_doc).__name__}",
            file=sys.stderr,
        )
        return 2

    config: dict[str, Any] = {
        "val_set": val_set,
        "log_path": args.out,
        "max_rounds": args.max_rounds,
        "max_budget": args.max_budget,
        "cost_per_round": args.cost_per_round,
        "seed": args.seed,
    }

    best = run_optimization(config)
    if best is None:
        # --max-budget 0: zero rounds, zero history, exit 0.
        return 0

    prompt_hash, f1 = best
    print(f"best prompt_hash={prompt_hash} F1={f1:.4f}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
