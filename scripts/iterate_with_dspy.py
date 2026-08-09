"""DSPy MIPROv2 iteration loop — skeleton script.

Kanban: t_db0e0fad (A4) on board 'pilot-ready'. Effort: L.

This is the self-improvement loop described in MASTER_PLAN §4. It is the
research-grade harness, not a config flip. The script:

  1. Loads the val set (or, once A6 lands, the held-out test set)
  2. Runs the auditor with the current prompt
  3. Computes per-rule recall (from A2 / ai_billing_audit.eval.per_rule_scorer)
  4. Generates 5 prompt variations using DSPy MIPROv2 or GEPA
  5. Re-runs val set against each variation
  6. Picks the winner by F1, writes prompts/v{N+1}/auditor_prompt.txt
  7. Logs to artifacts/iteration_log.jsonl with full provenance

Loop until R>=0.70 OR no improvement 2 consecutive rounds.

Usage:
    python3 scripts/iterate_with_dspy.py \
        --val data/synth/val.json \
        --base-prompt prompts/v12/auditor_prompt.txt \
        --rounds 5 \
        --out-dir artifacts/iterations/

Status: skeleton. The MIPROv2 optimizer invocation is stubbed at
_iterate_with_miprov2() below — wire it to your litellm/DSPy setup.

Exit code: 0 if any round improves on the previous best F1 OR if the
acceptance criterion is met; 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = PROJECT_ROOT / "artifacts" / "iterations"
DEFAULT_LOG_PATH = PROJECT_ROOT / "artifacts" / "iteration_log.jsonl"


def _next_version(out_dir: Path) -> int:
    """Find the next v{N} directory based on what's in out_dir/prompts."""
    p = out_dir / "prompts"
    if not p.exists():
        return 0
    existing = sorted(
        int(d.name.lstrip("v"))
        for d in p.iterdir()
        if d.is_dir() and d.name.startswith("v")
    )
    return (existing[-1] + 1) if existing else 0


def _run_audit(prompt_path: Path, val_path: Path, out_path: Path) -> None:
    """Run the auditor with the given prompt and write predictions.jsonl.

    This is a thin shim around the existing scripts/run_ollama_audit.py /
    scripts/run_v0_auditor.py. The exact command depends on the active
    model — see the env var ZORVA_RUN_CMD (default: the existing
    scripts/run_ollama_audit.py).

    Note on subprocess safety: we use shell=False with an argv list, so
    paths containing spaces or shell metacharacters cannot be interpreted
    as commands. The active prompt path is passed via env var, not via
    shell interpolation.
    """
    env_overlay = {
        "ZORVA_AUDITOR_PROMPT_PATH": str(prompt_path),
    }
    argv = [
        sys.executable,
        "scripts/run_ollama_audit.py",
        "--val",
        str(val_path),
        "--out",
        str(out_path),
    ]
    print(
        f"[iterate] running: {' '.join(argv)} (with ZORVA_AUDITOR_PROMPT_PATH={prompt_path})"
    )
    import os

    full_env = {**os.environ, **env_overlay}
    subprocess.run(argv, check=True, cwd=PROJECT_ROOT, env=full_env)


def _score(val_path: Path, preds_path: Path, scores_path: Path) -> dict:
    """Score predictions using the per-rule scorer (A2)."""
    cmd = [
        sys.executable,
        "-m",
        "ai_billing_audit.eval.per_rule_scorer",
        "--val",
        str(val_path),
        "--preds",
        str(preds_path),
        "--out",
        str(scores_path),
    ]
    print(f"[iterate] scoring: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)
    return json.loads(scores_path.read_text())


def _summarize(scores: dict) -> dict:
    """Reduce a per-rule report to {precision, recall, f1}."""
    overall = scores.get("overall", {})
    return {
        "precision": overall.get("precision", 0.0),
        "recall": overall.get("recall", 0.0),
        "f1": overall.get("f1", 0.0),
    }


def _iterate_with_miprov2(
    base_prompt_path: Path,
    n_variations: int,
    seed: int,
) -> list[str]:
    """Generate n_variations prompt variants using DSPy MIPROv2.

    SKELETON. Wire this to your DSPy setup. The expected return is a
    list of prompt strings (one per variation) ready to be written to
    prompts/v{N}/auditor_prompt.txt and scored.

    Reference: https://dspy-docs.vercel.app/api/optimizers/MIPROv2

    Recommended starting point (commented out — uncomment + adapt):

        import dspy
        from dspy.teleprompt import MIPROv2
        lm = dspy.LM("ollama/minimax-m3:cloud")  # or your provider
        dspy.configure(lm=lm)
        teleprompter = MIPROv2(metric=audit_metric, auto="light", num_threads=4)
        optimized = teleprompter.compile(
            student=ZorvaAuditorModule(prompt=base_prompt_path.read_text()),
            trainset=load_trainset(),
            valset=load_valset(),
        )
        return [str(p) for p in optimized.prompt_variants[:n_variations]]
    """
    # Placeholder: return n variations of "tell me about this encounter"
    # so the rest of the loop can be exercised end-to-end on a stub.
    base = base_prompt_path.read_text(encoding="utf-8")
    return [f"{base}\n\n[VARIANT {i}]" for i in range(n_variations)]


def _write_prompt(out_dir: Path, version: int, content: str) -> Path:
    pdir = out_dir / "prompts" / f"v{version}"
    pdir.mkdir(parents=True, exist_ok=True)
    p = pdir / "auditor_prompt.txt"
    p.write_text(content, encoding="utf-8")
    return p


def _append_log(log_path: Path, entry: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--val", required=True, type=Path, help="Path to the val or holdout JSON"
    )
    p.add_argument(
        "--base-prompt",
        required=True,
        type=Path,
        help="Path to the starting prompt (e.g. prompts/v12/auditor_prompt.txt)",
    )
    p.add_argument(
        "--rounds", type=int, default=5, help="Max iteration rounds (default 5)"
    )
    p.add_argument(
        "--n-variations",
        type=int,
        default=5,
        help="Number of MIPROv2 prompt variations per round",
    )
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH)
    p.add_argument(
        "--target-recall",
        type=float,
        default=0.70,
        help="Acceptance: stop when R >= this",
    )
    p.add_argument("--seed", type=int, default=1729)
    args = p.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Score the baseline (round 0).
    base_v = _next_version(args.out_dir)
    base_pred = args.out_dir / f"round{base_v}" / "predictions.jsonl"
    base_pred.parent.mkdir(parents=True, exist_ok=True)
    _run_audit(args.base_prompt, args.val, base_pred)
    base_scores = _score(
        args.val, base_pred, args.out_dir / f"round{base_v}" / "scores.json"
    )
    base_summary = _summarize(base_scores)
    _append_log(
        args.log,
        {
            "round": base_v,
            "phase": "baseline",
            "prompt": str(args.base_prompt),
            "metrics": base_summary,
            "ts": int(time.time()),
        },
    )
    print(f"[iterate] baseline: {base_summary}")

    best_f1 = base_summary["f1"]
    best_recall = base_summary["recall"]
    no_improve_count = 0
    won_round = base_v

    for r in range(1, args.rounds + 1):
        if best_recall >= args.target_recall:
            print(
                f"[iterate] R={best_recall:.3f} >= target {args.target_recall}; stopping"
            )
            break
        if no_improve_count >= 2:
            print("[iterate] no improvement for 2 rounds; stopping")
            break

        variations = _iterate_with_miprov2(
            args.base_prompt, args.n_variations, args.seed
        )
        round_best_f1 = best_f1
        round_best_v = None

        for i, var in enumerate(variations):
            v = base_v + (r - 1) * args.n_variations + i + 1
            prompt_path = _write_prompt(args.out_dir, v, var)
            pred_path = args.out_dir / f"round{v}" / "predictions.jsonl"
            pred_path.parent.mkdir(parents=True, exist_ok=True)
            _run_audit(prompt_path, args.val, pred_path)
            scores = _score(
                args.val, pred_path, args.out_dir / f"round{v}" / "scores.json"
            )
            summary = _summarize(scores)
            _append_log(
                args.log,
                {
                    "round": v,
                    "phase": "variation",
                    "prompt": str(prompt_path),
                    "metrics": summary,
                    "ts": int(time.time()),
                },
            )
            print(f"[iterate] round {r} variation {i}: v{v} → {summary}")
            if summary["f1"] > round_best_f1:
                round_best_f1 = summary["f1"]
                round_best_v = v

        if round_best_v is None or round_best_f1 <= best_f1:
            no_improve_count += 1
            print(f"[iterate] round {r}: no improvement (best_f1={round_best_f1:.3f})")
        else:
            no_improve_count = 0
            best_f1 = round_best_f1
            won_round = round_best_v
            print(f"[iterate] round {r}: new best v{round_best_v} f1={best_f1:.3f}")
            # Promote winner to "current best" prompt.
            shutil.copyfile(
                args.out_dir / "prompts" / f"v{won_round}" / "auditor_prompt.txt",
                args.out_dir / "current_best_prompt.txt",
            )

    # Final acceptance check.
    won_path = args.out_dir / "prompts" / f"v{won_round}" / "auditor_prompt.txt"
    print(f"[iterate] winner: v{won_round} ({won_path}) f1={best_f1:.3f}")
    return 0 if best_recall >= args.target_recall or best_f1 > base_summary["f1"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
