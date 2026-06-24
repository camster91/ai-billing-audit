"""Render the F1-vs-trial curve for the overfit bug hunt (t_c6838361).

Reads ``logs/optimization_history.jsonl`` (one record per MIPROv2
trial with F1/P/R/prompt_hash/round/timestamp) and emits a text
table + an ASCII bar chart at the F1==1.0 line, plus overlays for
the two held-out F1 measurements (val and seed9999).

The script also writes a CSV-like TSV at ``logs/overfit_curve.tsv``
suitable for plotting in another tool.

Usage:
    python scripts/render_overfit_curve.py \
        --history logs/optimization_history.jsonl \
        --val logs/overfit_val_replication.json \
        --seed9999 logs/overfit_seed9999.json \
        --out docs/BUGS_overfit_curve.txt
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _bar(p: float, width: int = 40) -> str:
    n = max(0, min(width, int(round(p * width))))
    return "█" * n + "·" * (width - n)


def render(history_path: Path, val_path: Path, seed_path: Path, out_path: Path) -> str:
    history = [json.loads(line) for line in history_path.read_text().splitlines() if line.strip()]
    val = json.loads(val_path.read_text()) if val_path.exists() else None
    seed = json.loads(seed_path.read_text()) if seed_path.exists() else None

    lines: list[str] = []
    lines.append("F1 vs. trial (MIPROv2 smoke loop, train_seed=1729, val=50)")
    lines.append("=" * 78)
    lines.append(f"{'trial':>5}  {'F1':>7}  {'P':>7}  {'R':>7}  bar")
    lines.append("-" * 78)
    for rec in history:
        f1 = rec["F1"]
        p = rec.get("P", 0.0)
        r = rec.get("R", 0.0)
        lines.append(
            f"{rec['round']:>5}  {f1:>7.4f}  {p:>7.4f}  {r:>7.4f}  {_bar(f1)}"
        )
    lines.append("-" * 78)
    if val:
        lines.append(
            f"  → held-out val.json (n=50, sha256={val['holdout_sha256'][:24]}…): "
            f"F1={val['pooled_f1']:.4f}  P={val['pooled_precision']:.4f}  "
            f"R={val['pooled_recall']:.4f}"
        )
    if seed:
        lines.append(
            f"  → held-out holdout_seed9999.json (n=50, sha256={seed['holdout_sha256'][:24]}…): "
            f"F1={seed['pooled_f1']:.4f}  P={seed['pooled_precision']:.4f}  "
            f"R={seed['pooled_recall']:.4f}"
        )

    text = "\n".join(lines) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text)
    return text


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--history", type=Path,
                   default=Path("logs/optimization_history.jsonl"))
    p.add_argument("--val", type=Path,
                   default=Path("logs/overfit_val_replication.json"))
    p.add_argument("--seed9999", type=Path,
                   default=Path("logs/overfit_seed9999.json"))
    p.add_argument("--out", type=Path,
                   default=Path("docs/BUGS_overfit_curve.txt"))
    args = p.parse_args()
    print(render(args.history, args.val, args.seed9999, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
