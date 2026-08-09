"""Compare two smartness-test JSON files and report the delta.

Use this to see whether a new prompt version is actually
better than the baseline. Reports:
* Per-encounter P/R/F1 delta
* Micro-aggregate P/R/F1 delta
* Per-rule recall delta (where the new version actually wins
  or loses)
* Per-severity P/R/F1 delta
* Latency delta
* Encounters where the new version fixed/introduced issues

Usage:
    python3 scripts/compare_smartness.py baseline.json new.json
"""

from __future__ import annotations

import argparse
import json
import sys


def _per_encounter_means(s: dict) -> tuple[float, float, float]:
    m = s["mean_per_encounter"]
    return m["precision"], m["recall"], m["f1"]


def _per_rule_recall(s: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for rid, stats in s["per_rule"].items():
        r = stats["recall"]
        if r is None:
            continue
        out[rid] = r
    return out


def _per_severity(s: dict) -> dict[str, dict[str, float]]:
    return {
        sev: {
            "P": stats["mean_p"],
            "R": stats["mean_r"],
            "F1": stats["mean_f1"],
        }
        for sev, stats in s["per_severity"].items()
    }


def _encounter_level_diff(
    base_results: list[dict], new_results: list[dict]
) -> dict[str, int]:
    """Per-encounter comparison: which encounters moved F1 up/down."""
    base_by_eid = {r["encounter_id"]: r for r in base_results}
    new_by_eid = {r["encounter_id"]: r for r in new_results}
    counts = {"up": 0, "down": 0, "same": 0, "only_base": 0, "only_new": 0}
    for eid in sorted(base_by_eid):
        if eid not in new_by_eid:
            counts["only_base"] += 1
            continue
        bf1 = base_by_eid[eid]["f1"]
        nf1 = new_by_eid[eid]["f1"]
        if nf1 > bf1 + 0.01:
            counts["up"] += 1
        elif nf1 < bf1 - 0.01:
            counts["down"] += 1
        else:
            counts["same"] += 1
    for eid in new_by_eid:
        if eid not in base_by_eid:
            counts["only_new"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two smartness-test JSON files"
    )
    parser.add_argument("baseline", help="Path to baseline JSON")
    parser.add_argument("new", help="Path to new-version JSON")
    parser.add_argument("--label-base", default="baseline")
    parser.add_argument("--label-new", default="new")
    args = parser.parse_args()

    with open(args.baseline) as f:
        base = json.load(f)
    with open(args.new) as f:
        new = json.load(f)

    bs = base["summary"]
    ns = new["summary"]

    print("=" * 72)
    print(f"COMPARISON: {args.label_base} → {args.label_new}")
    print("=" * 72)

    # Top-line numbers
    print()
    print(f"Encounters scored: base={bs['n_encounters']}  new={ns['n_encounters']}")
    print()
    bp, br, bf1 = _per_encounter_means(bs)
    np_, nr, nf1 = _per_encounter_means(ns)
    print("Per-encounter (mean):")
    print("              P       R       F1")
    print(f"  base:      {bp:.3f}  {br:.3f}  {bf1:.3f}")
    print(f"  new:       {np_:.3f}  {nr:.3f}  {nf1:.3f}")
    print(f"  delta:     {np_ - bp:+.3f}  {nr - br:+.3f}  {nf1 - bf1:+.3f}")
    print()
    bm = bs["micro_aggregate"]
    nm = ns["micro_aggregate"]
    print("Micro-aggregate:")
    print("              P       R       F1       TP / predicted / gold")
    print(
        f"  base:      {bm['precision']:.3f}  {bm['recall']:.3f}  {bm['f1']:.3f}  "
        f"{bm['true_positives']} / {bm['total_predicted']} / {bm['total_gold']}"
    )
    print(
        f"  new:       {nm['precision']:.3f}  {nm['recall']:.3f}  {nm['f1']:.3f}  "
        f"{nm['true_positives']} / {nm['total_predicted']} / {nm['total_gold']}"
    )
    print()
    # Per-rule recall delta
    base_rule = _per_rule_recall(bs)
    new_rule = _per_rule_recall(ns)
    common = sorted(set(base_rule) | set(new_rule))
    print("Per-rule recall delta (sorted by absolute improvement):")
    deltas = []
    for rid in common:
        b = base_rule.get(rid, 0.0)
        n = new_rule.get(rid, 0.0)
        deltas.append((n - b, rid, b, n))
    deltas.sort(key=lambda x: x[0], reverse=True)
    for delta, rid, b, n in deltas[:10]:
        print(f"  {rid:30s}  base={b:.2f}  new={n:.2f}  delta={delta:+.2f}")
    print(
        "  ... and {} more (use --detailed to see all)".format(max(0, len(deltas) - 10))
    )
    print()
    print("  Bottom 10 (most regressed):")
    for delta, rid, b, n in sorted(deltas, key=lambda x: x[0])[:10]:
        print(f"  {rid:30s}  base={b:.2f}  new={n:.2f}  delta={delta:+.2f}")
    print()
    # Per-severity delta
    base_sev = _per_severity(bs)
    new_sev = _per_severity(ns)
    print("Per-severity F1 delta:")
    for sev in ["info", "low", "medium", "high", "critical"]:
        if sev in base_sev or sev in new_sev:
            bf1 = base_sev.get(sev, {}).get("F1", 0.0)
            nf1 = new_sev.get(sev, {}).get("F1", 0.0)
            print(f"  {sev:8s}  base={bf1:.3f}  new={nf1:.3f}  delta={nf1 - bf1:+.3f}")
    print()
    # Latency
    blat = bs["latency"]
    nlat = ns["latency"]
    print(
        f"Latency: base mean={blat['mean_s']:.2f}s p95={blat['p95_s']:.2f}s  "
        f"new mean={nlat['mean_s']:.2f}s p95={nlat['p95_s']:.2f}s"
    )
    print()
    # Encounter-level deltas
    counts = _encounter_level_diff(base["results"], new["results"])
    print("Per-encounter F1 movement:")
    print(f"  Improved (F1 up > 0.01):    {counts['up']}")
    print(f"  Regressed (F1 down > 0.01): {counts['down']}")
    print(f"  Same:                       {counts['same']}")
    print(f"  Only in baseline:           {counts['only_base']}")
    print(f"  Only in new:                {counts['only_new']}")
    print()
    # Verdict
    verdict = []
    if nf1 - bf1 > 0.02:
        verdict.append(f"NEW WINS by {nf1 - bf1:.3f} F1")
    elif nf1 - bf1 < -0.02:
        verdict.append(f"NEW REGRESSES by {bf1 - nf1:.3f} F1")
    else:
        verdict.append("NO MEANINGFUL CHANGE")
    if nf1 - bf1 > 0:
        verdict.append(f"+{nr - br:.3f} recall")
    else:
        verdict.append(f"{nr - br:+.3f} recall")
    if np_ - bp > 0:
        verdict.append(f"+{np_ - bp:.3f} precision")
    else:
        verdict.append(f"{np_ - bp:+.3f} precision")
    print("Verdict:", " | ".join(verdict))

    return 0


if __name__ == "__main__":
    sys.exit(main())
