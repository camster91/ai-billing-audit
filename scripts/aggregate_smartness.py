"""Aggregate multiple smartness_test JSON output files into one report.

The 50-encounter test takes ~30 minutes because each audit takes
~30s. We run in chunks (10 encounters per chunk) and stitch the
results back together with this script.

Usage:
    python3 scripts/smartness_test.py --start 0 --n 10 --out chunk_0.json
    python3 scripts/smartness_test.py --start 10 --n 10 --out chunk_1.json
    ...
    python3 scripts/aggregate_smartness.py chunk_*.json --out full.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Import the aggregation helper from the smartness_test module
sys.path.insert(0, str(Path(__file__).resolve().parent))
from smartness_test import (
    EncounterResult,
    _aggregate,
    _print_report,
)


def _reconstruct(chunk: dict) -> list[EncounterResult]:
    results = []
    for r in chunk["results"]:
        results.append(
            EncounterResult(
                encounter_id=r["encounter_id"],
                is_flagged_gold=any(g for g in r["gold_findings"]),
                n_gold=r["n_gold"],
                n_pred=r["n_pred"],
                n_matched=r["n_matched"],
                p=r["p"],
                r=r["r"],
                f1=r["f1"],
                pred_findings=r["pred_findings"],
                gold_findings=r["gold_findings"],
                error=r.get("error"),
                latency_s=r["latency_s"],
            )
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate smartness_test JSON chunks")
    parser.add_argument("chunks", nargs="+", help="JSON files from smartness_test.py")
    parser.add_argument("--out", default=None, help="Write combined JSON to this path")
    args = parser.parse_args()

    all_results: list[EncounterResult] = []
    for path in args.chunks:
        with open(path) as f:
            chunk = json.load(f)
        all_results.extend(_reconstruct(chunk))
        print(f"Loaded {len(chunk['results'])} results from {path}")

    summary = _aggregate(all_results)
    _print_report(summary, all_results)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            json.dump(
                {
                    "summary": summary,
                    "results": [
                        {
                            "encounter_id": r.encounter_id,
                            "n_gold": r.n_gold,
                            "n_pred": r.n_pred,
                            "n_matched": r.n_matched,
                            "p": r.p,
                            "r": r.r,
                            "f1": r.f1,
                            "latency_s": r.latency_s,
                            "error": r.error,
                            "pred_findings": r.pred_findings,
                            "gold_findings": r.gold_findings,
                        }
                        for r in all_results
                    ],
                },
                f,
                indent=2,
            )
        print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
