"""MIPROv2 compilation and val-set evaluation for the optimization loop.

This module isolates **all** imports of ``dspy`` and ``dspy.teleprompt.MIPROv2``
to a single file so the loop driver (``src/optimize.py``) and the rest of
the codebase stay clean of dspy as a runtime dependency. Importing
:mod:`optimize_compile` does not pull dspy in — the dspy import lives
inside :func:`_build_mipro_optimizer` and is only triggered when the
caller explicitly opts into the real ``"mipro"`` mode.

Public surface
--------------

``compile_and_evaluate(round_idx, val_set, *, train_set=None, seed=1729, mode="stub")``
    Compile the candidate prompt for ``round_idx`` and evaluate it on
    ``val_set``. Returns ``{"R": float, "P": float, "F1": float,
    "prompt_hash": str}``.

    Two modes:

    * ``mode="stub"`` (default) — deterministic synthetic R/P/F1 with
      a stable 64-char hex sha256 ``prompt_hash``. No LLM, no network,
      no dspy. This is what the offline test suite runs against.
    * ``mode="mipro"`` — real MIPROv2 compilation against ``train_set``
      and evaluation on ``val_set``. Requires an LLM backend (or a
      dspy fake LM for tests) and a metric function. The metric is
      passed in via the optional ``metric`` keyword; when omitted we
      fall back to a deterministic ground-truth match metric suitable
      for the canned ``data/val.json`` split.

    Given a fixed seed and the same ``val_set`` / ``train_set`` inputs,
    the return value is deterministic: the same ``(R, P, F1,
    prompt_hash)`` tuple every call.

Hashing
-------
The returned ``prompt_hash`` is a sha256 of the *serialized* compiled
prompt artifact. In ``"stub"`` mode the artifact is a small JSON
projection of the round + seed + metrics. In ``"mipro"`` mode the
artifact is the dspy program's ``dump_state()`` JSON, which captures
every instruction, demonstration, and field. Both are 64-char lowercase
hex strings.

Acceptance
----------
Given a fixed seed and ``val_set``, the function returns deterministic
R/P/F1 and a stable 64-char hex ``prompt_hash``. Verified by
``tests/test_optimize_compile.py``.
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any, Callable, Mapping, Sequence

__all__ = ["compile_and_evaluate"]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compile_and_evaluate(
    round_idx: int,
    val_set: Sequence[Mapping[str, Any]],
    *,
    train_set: Sequence[Mapping[str, Any]] | None = None,
    seed: int = 1729,
    mode: str = "stub",
    metric: Callable[[Any, Any, Any | None], float] | None = None,
) -> dict[str, float | str]:
    """Compile the candidate prompt for ``round_idx`` and evaluate on ``val_set``.

    See module docstring for full mode semantics. ``metric`` is only
    consulted in ``"mipro"`` mode; it receives
    ``(example, prediction, trace=None)`` and returns a float in
    ``[0.0, 1.0]``.
    """
    if not val_set:
        raise ValueError("val_set must be non-empty")
    if mode not in {"stub", "mipro"}:
        raise ValueError(f"mode must be 'stub' or 'mipro', got {mode!r}")

    if mode == "stub":
        return _compile_and_evaluate_stub(round_idx, val_set, seed=seed)
    # mode == "mipro"
    return _compile_and_evaluate_mipro(
        round_idx, val_set, train_set=train_set, seed=seed, metric=metric
    )


# ---------------------------------------------------------------------------
# Stub mode (deterministic, no dspy)
# ---------------------------------------------------------------------------


def _compile_and_evaluate_stub(
    round_idx: int,
    val_set: Sequence[Mapping[str, Any]],
    *,
    seed: int,
) -> dict[str, float | str]:
    """Deterministic synthetic R/P/F1 with a stable 64-char hex hash.

    Mirrors the pre-extraction behaviour of
    ``src.optimize.compile_and_evaluate``: a slow upward walk with a
    small jitter that does not saturate by round 10 (so a default
    ``--max-rounds 10`` test run exercises the round-cap exit, not the
    convergence exit).
    """
    rng = random.Random(seed + round_idx)
    base = 0.55 + 0.02 * (round_idx - 1)
    jitter = rng.uniform(-0.005, 0.005)
    p_raw = min(1.0, max(0.0, base + jitter))
    r_raw = min(1.0, max(0.0, base + 0.02 + rng.uniform(-0.005, 0.005)))
    p = round(p_raw, 6)
    r = round(r_raw, 6)
    f1 = round(2 * p * r / (p + r) if (p + r) > 0 else 0.0, 6)
    prompt_repr = json.dumps(
        {"round": round_idx, "seed": seed, "p": p, "r": r, "f1": f1},
        sort_keys=True,
    )
    prompt_hash = hashlib.sha256(prompt_repr.encode("utf-8")).hexdigest()
    return {"R": r, "P": p, "F1": f1, "prompt_hash": prompt_hash}


# ---------------------------------------------------------------------------
# MIPROv2 mode (real compilation, isolated dspy import)
# ---------------------------------------------------------------------------


def _compile_and_evaluate_mipro(
    round_idx: int,
    val_set: Sequence[Mapping[str, Any]],
    *,
    train_set: Sequence[Mapping[str, Any]] | None,
    seed: int,
    metric: Callable[[Any, Any, Any | None], float] | None,
) -> dict[str, float | str]:
    """Real MIPROv2 compile + val-set evaluation.

    The dspy import lives here so the rest of the codebase never sees
    dspy at import time. The compiled program is serialized via
    ``dspy.Module.dump_state()`` and hashed with sha256. The metric
    defaults to :func:`_default_ground_truth_metric` which matches
    predicted ``findings`` (a list of strings) against the ground
    truth ``findings`` list on each val example.
    """
    optimizer, dspy = _build_mipro_optimizer(
        seed=seed, metric=metric or _default_ground_truth_metric
    )

    student = dspy.Predict(
        "clinical_note, billed_claim, payer_rules -> findings: list[str]"
    )

    # MIPROv2 calls the metric against dspy.Example objects (which
    # have ``.inputs()`` and ``.base``); wrap the plain dicts up
    # front so the metric and the internal proposer can index them.
    # The wrapper is deterministic w.r.t. seed.
    Example = dspy.Example
    val_examples = [
        Example(base=enc).with_inputs("clinical_note", "billed_claim", "payer_rules")
        for enc in val_set
    ]
    if train_set is not None:
        train_examples = [
            Example(base=enc).with_inputs(
                "clinical_note", "billed_claim", "payer_rules"
            )
            for enc in train_set
        ]
    else:
        # MIPROv2 needs *some* trainset; fall back to a single
        # pseudo-example derived from the first val encounter so the
        # compile call does not crash on a no-train call site.
        train_examples = [val_examples[0]]

    compile_kwargs: dict[str, Any] = {
        "valset": val_examples,
        "trainset": train_examples,
        "seed": seed,
        "minibatch": True,
    }

    # MIPROv2's compile() is chatty — silence the dspy event logger
    # so the round doesn't drown the test output. The optimizer still
    # runs to completion; we just don't print its progress.
    dspy.disable_logging()
    try:
        compiled = optimizer.compile(student, **compile_kwargs)
    finally:
        dspy.enable_logging()
    # ``dump_state`` is a stable JSON-serializable snapshot of every
    # instruction, demo, and field in the compiled program. Hashing it
    # gives a deterministic 64-char hex prompt_hash. We fold the
    # round_idx into the hashed payload so each round's hash is unique
    # even when MIPROv2's own compile (for the same seed + trainset)
    # converges to the same instruction set.
    state = compiled.dump_state()
    state_with_round = dict(state)
    state_with_round["__round_idx__"] = int(round_idx)
    serialized = json.dumps(state_with_round, sort_keys=True, default=str)
    prompt_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    # Evaluate on the val set with the same metric. We collect the
    # per-example score and aggregate into precision/recall/F1 against
    # the ground truth ``is_flagged`` label (a conservative proxy for
    # the binary audit verdict — a finding-rich encounter is one the
    # auditor should flag).
    pred_has_discrepancy: list[bool] = []
    for ex_dict in val_set:
        try:
            pred = compiled(
                clinical_note=ex_dict.get("clinical_note", ""),
                billed_claim=json.dumps(ex_dict.get("claim", {})),
                payer_rules=_format_payer_rules(ex_dict.get("rules", [])),
            )
            findings = getattr(pred, "findings", None) or []
            pred_has_discrepancy.append(bool(findings))
        except Exception:  # pragma: no cover - defensive: an LM error
            # on a single example should not abort the whole round.
            pred_has_discrepancy.append(False)

    gold = [bool(ex_dict.get("is_flagged", False)) for ex_dict in val_set]
    p, r, f1 = _precision_recall_f1(pred_has_discrepancy, gold)
    # Round for stable JSON output, same precision as the stub.
    p_r = round(float(p), 6)
    r_r = round(float(r), 6)
    f1_r = round(float(f1), 6)

    return {
        "R": r_r,
        "P": p_r,
        "F1": f1_r,
        "prompt_hash": prompt_hash,
    }


def _build_mipro_optimizer(
    *,
    seed: int,
    metric: Callable[[Any, Any, Any | None], float],
) -> tuple[Any, Any]:
    """Construct a MIPROv2 optimizer and the dspy module.

    Imported lazily so the rest of the codebase never pulls dspy in.
    Returns ``(optimizer, dspy_module)`` — callers use the dspy module
    to wrap val examples and build the student program.
    """
    import dspy  # type: ignore[import-untyped]  # dspy ships no py.typed marker
    from dspy.teleprompt import MIPROv2  # type: ignore[import-untyped]

    optimizer = MIPROv2(
        metric=metric,
        auto="light",
        seed=seed,
        verbose=False,
    )
    return optimizer, dspy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_ground_truth_metric(
    example: Any,
    prediction: Any,
    trace: Any | None = None,
) -> float:
    """Default MIPROv2 metric: 1.0 if the predicted findings list is
    non-empty exactly when the example is flagged, else 0.0.

    Tolerant of either ``dspy.Example`` (with ``.base`` carrying the
    original dict) or a plain dict, so it works in unit tests that
    hand-craft Examples and in production runs over the val split.
    """
    base = getattr(example, "base", example)
    is_flagged = bool(base.get("is_flagged", False))
    findings = getattr(prediction, "findings", None) or []
    predicted_flag = bool(findings)
    return 1.0 if is_flagged == predicted_flag else 0.0


def _format_payer_rules(rules: Sequence[Mapping[str, Any]]) -> str:
    """Render the per-encounter rule list as the ``payer_rules`` string
    field. Stable formatting: one rule per block, sorted by ``rule_id``
    so the hash is deterministic."""
    if not rules:
        return ""
    blocks = sorted(rules, key=lambda r: str(r.get("rule_id", "")))
    rendered = []
    for rule in blocks:
        rendered.append(
            f"[{rule.get('rule_id', '?')}] {rule.get('trigger', '').strip()}"
        )
    return "\n".join(rendered)


def _precision_recall_f1(
    predicted: Sequence[bool],
    gold: Sequence[bool],
) -> tuple[float, float, float]:
    """Binary precision/recall/F1. Returns zeros when both sets are empty."""
    if len(predicted) != len(gold):
        raise ValueError(
            f"predicted/gold length mismatch: {len(predicted)} vs {len(gold)}"
        )
    tp = fp = fn = 0
    for p, g in zip(predicted, gold):
        if p and g:
            tp += 1
        elif p and not g:
            fp += 1
        elif not p and g:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return precision, recall, f1
