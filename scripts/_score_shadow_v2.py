#!/usr/bin/env python3
"""
Score a shadow runner JSON output against ground_truth to produce
a per-rule confusion matrix + aggregate P/R/F1.

This is the second half of the blind test: the shadow runner
produces findings, this script scores them against the planted
gold we wrote into data/mock/prospect_demo_100.json.

Definitions
-----------
- TP (true positive): ground_truth has rule_id R + finding's rule_id
  (or category / explanation) semantically matches R.
- FP (false positive): ground_truth empty + finding has rule_id R.
- FN (false negative): ground_truth has rule_id R + no finding matches R.
- TN (true negative): ground_truth empty + no finding.

Because the live v12 auditor uses a US-CPT-style rule-id namespace
(MOD-25-*, DX-MATCH-*, MEDICARE_AWV_*, etc.) but the val_ca.json
gold set + our mock generator use the AHCIP-tuned namespace
(rule_ahcip_missing_procedure, etc.), we score via SEMANTIC BUCKETS
rather than literal rule_id equality. Each ground_truth bucket is
mapped to one or more LLM rule patterns that indicate the same
finding:

  rule_ahcip_missing_procedure   <- MOD-25*, E_M_PROCEDURE_MODIFIER
  rule_ahcip_em_level_upcode     <- som_b_*, DX-PROCEDURE-ALIGNMENT
  rule_ahcip_em_level            <- som_b_*, DX-MATCH-*
  rule_ahcip_same_day_conflict   <- MOD-25-SAME-DAY-001, MOD-STD-001
  rule_ahcip_non_insured_service <- MEDICARE_AWV*, ZCODE-*, Z00_*, MEDICARE-*

A finding matches if its rule_id (or category / explanation) hits any
of the patterns for the bucket.

Usage::

    python3 scripts/_score_shadow_v2.py runs/shadow/prospect_demo_100-<ts>.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Semantic bucket mapping: planted rule_id -> list of regex patterns
# that the LLM would emit for the same finding.
#
# P11 round-3 (2026-07-02): the runner now canonicalizes raw LLM
# rule_ids to ``rule_ahcip_*`` (via ``_canonicalize_rule_id``) before
# writing the report JSON. The bucket patterns below therefore MUST
# match BOTH:
#   - the canonical rule_id (e.g. ``rule_ahcip_modifier_25_unlock``)
#   - the legacy raw LLM output (e.g. ``MOD-25-SAME-DAY-001``) which
#     may still appear if a finding slipped past the canonicalizer
#     (e.g. multi-rule comma-joined strings).
BUCKET_PATTERNS: dict[str, list[str]] = {
    # Same-day bucket listed FIRST so its more-specific pattern
    # (``^MOD-25-SAME-DAY``) wins over the generic ``^MOD-25-`` in the
    # missing_procedure bucket below for legacy raw LLM output that
    # slipped past the canonicalizer. (Canonical rule_ids resolve
    # via the \b...\b boundary patterns regardless of order.)
    r"rule_ahcip_same_day_conflict": [
        r"\brule_ahcip_same_day_conflict\b",
        r"^MOD-25-SAME-DAY",
        r"same.day.conflict",
        r"same_day_conflict",
    ],
    r"rule_ahcip_missing_procedure": [
        r"\brule_ahcip_modifier_25_unlock\b",
        r"\brule_ahcip_missing_procedure\b",
        r"^MOD-25-",
        r"^E_M_PROCEDURE_MODIFIER",
        r"^MOD-STD-001",
        r"procedure.*e/m",
        r"missing_modifier",
    ],
    r"rule_ahcip_em_level_upcode": [
        r"\brule_ahcip_em_level_upcode\b",
        r"^som_b_",
        r"^DX-PROCEDURE-ALIGNMENT",
        r"em_level_upcode|comprehensive|undercoded|undercode",
        r"e/m level too low",
    ],
    r"rule_ahcip_em_level": [
        r"\brule_ahcip_em_level\b",
        r"\brule_ahcip_dx_linkage\b",
        r"\brule_ahcip_global_window\b",
        r"^som_b_",
        r"^DX-MATCH-",
        r"^DX-DOC-",
        r"evaluation.*level",
    ],
    r"rule_ahcip_non_insured_service": [
        r"\brule_ahcip_non_insured_service\b",
        r"^MEDICARE_AWV",
        r"^Z00_",
        r"^ZCODE-",
        r"^AWV-",
        r"annual.*physical|preventive.*non.insured|non.insured.*annual",
        r"z00_00_no_abnormal",
    ],
    r"rule_ahcip_global_window": [
        r"\brule_ahcip_global_window\b",
        r"^SCOPE-OF-PRACTICE",
        r"global.*period|post.op|surgical.*global",
    ],
}


def matches_bucket(
    rule_id: str, category: str, explanation: str, patterns: list[str]
) -> bool:
    """Return True if (rule_id OR category OR explanation) matches any pattern."""
    haystack = f"{rule_id} {category} {explanation}".lower()
    for pat in patterns:
        if re.search(pat, haystack, re.IGNORECASE):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path, help="Shadow runner JSON output")
    args = parser.parse_args()

    if not args.report.is_file():
        print(f"ERROR: report not found: {args.report}", file=sys.stderr)
        return 2

    # Load both: shadow runner output + the input mock data (so we can
    # read planted ground_truth since the runner doesn't write it back).
    report = json.loads(args.report.read_text())
    # The runner JSON has only claim+findings per encounter; find
    # the planted ground truth via encounter_id by re-reading the mock file.
    encounters_meta: dict[str, dict] = {}
    # The mock file path is encoded nowhere — re-discover by iterating
    # all data/mock/*.json files looking for matching encounter_ids.
    mock_files = list(Path("data/mock").glob("*.json"))
    for mf in mock_files:
        try:
            md = json.loads(mf.read_text())
            for e in md:
                if "encounter_id" in e:
                    encounters_meta[e["encounter_id"]] = e
        except Exception:
            pass

    encounters = report.get("encounters", [])
    if not encounters:
        print("ERROR: report has no encounters", file=sys.stderr)
        return 3

    per_bucket = Counter()  # bucket -> (TP, FP, FN)
    tp_total = fp_total = fn_total = tn_total = 0
    by_severity = Counter()
    by_category = Counter()  # what categories the LLM uses for TP

    for enc in encounters:
        meta = encounters_meta.get(enc["encounter_id"], {})
        planted_buckets = list({gt["rule_id"] for gt in meta.get("ground_truth", [])})

        # Findings: rule_id may be comma-separated
        predicted_buckets: set[str] = set()
        predicted_meta: list[dict] = []
        for f in enc.get("findings", []):
            rid = f.get("rule_id", "")
            if rid in ("STUB_NO_DATA", "AUDIT_ERROR", "VALIDATION_ERROR", ""):
                continue
            for single in rid.split(","):
                single = single.strip()
                if not single:
                    continue
                for planted_b, patterns in BUCKET_PATTERNS.items():
                    if matches_bucket(
                        single,
                        f.get("category", ""),
                        f.get("explanation", ""),
                        patterns,
                    ):
                        predicted_buckets.add(planted_b)
                        predicted_meta.append({**f, "matched_bucket": planted_b})
                # Predictions with no bucket match stay as raw predictions
                # (counted as FP per-bucket if planted is empty, or just
                # not counted if planted has a bucket and LLM missed it
                # — that's an FN).

        if not planted_buckets and not predicted_buckets:
            tn_total += 1
        elif not planted_buckets and predicted_buckets:
            # FPs across planted-empty categories
            for _ in predicted_buckets:
                fp_total += 1
        elif planted_buckets and not predicted_buckets:
            for _ in planted_buckets:
                fn_total += 1
            per_bucket_stats = Counter()
            for b in planted_buckets:
                per_bucket_stats[(b, "FN")] += 1
            per_bucket += per_bucket_stats
        else:
            # Both planted and predicted — match by bucket
            tp_this = predicted_buckets & set(planted_buckets)
            fn_this = set(planted_buckets) - predicted_buckets
            fp_this = predicted_buckets - set(planted_buckets)
            for b in tp_this:
                per_bucket[(b, "TP")] += 1
                tp_total += 1
                # Severity + category of the TP
                for m in predicted_meta:
                    if m["matched_bucket"] == b:
                        by_severity[m.get("severity", "unknown")] += 1
                        by_category[m.get("category", "unknown")] += 1
                        break
            for b in fn_this:
                per_bucket[(b, "FN")] += 1
                fn_total += 1
            for _ in fp_this:
                fp_total += 1

    precision = tp_total / (tp_total + fp_total) if (tp_total + fp_total) > 0 else 0.0
    recall = tp_total / (tp_total + fn_total) if (tp_total + fn_total) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    print(
        f"=== Blind-test scoring v2 (semantic bucket matching) — {args.report.name} ==="
    )
    print()
    print(f"Encounters audited: {len(encounters)}")
    planted_total = sum(
        len(encounters_meta.get(e["encounter_id"], {}).get("ground_truth", []))
        for e in encounters
    )
    print(f"Planted findings:   {planted_total}")
    audit_total = sum(
        1
        for e in encounters
        for f in e.get("findings", [])
        if f.get("rule_id")
        not in ("STUB_NO_DATA", "AUDIT_ERROR", "VALIDATION_ERROR", "")
    )
    print(f"Audit findings (real): {audit_total}")
    print()
    print("Confusion matrix (semantic-bucket level):")
    print(f"  TP: {tp_total}  FP: {fp_total}  FN: {fn_total}  TN: {tn_total}")
    print()
    print(f"Precision (semantic):  {precision:.3f} = TP / (TP + FP)")
    print(f"Recall    (semantic):  {recall:.3f} = TP / (TP + FN)")
    print(f"F1                     : {f1:.3f}")
    print()
    print(f"TP by severity: {dict(by_severity)}")
    print(f"TP by category: {dict(by_category)}")
    print()
    print("Per-bucket breakdown:")
    buckets = sorted({b for (b, _) in per_bucket.keys()})
    for b in buckets:
        tp = per_bucket[(b, "TP")]
        fp = per_bucket.get((b, "FP"), 0)
        fn = per_bucket[(b, "FN")]
        if tp + fp + fn == 0:
            continue
        p_b = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r_b = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        line = f"  {b}: TP={tp} FP={fp} FN={fn} (P={p_b:.2f} R={r_b:.2f})"
        print(line)

    # Bonus: cases LLM caught we DIDN'T plant (curiosity check)
    print()
    print("Bonus — LLM predicted findings on clean encounters (no planted gold):")
    bonus = 0
    for enc in encounters:
        meta = encounters_meta.get(enc["encounter_id"], {})
        if not meta.get("ground_truth"):
            for f in enc.get("findings", []):
                rid = f.get("rule_id", "")
                if rid in ("STUB_NO_DATA", "AUDIT_ERROR", "VALIDATION_ERROR", ""):
                    continue
                bonus += 1
    print(f"  Bonus findings on clean encounters: {bonus}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
