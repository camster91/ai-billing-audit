"""Build the 150-encounter gold manifest for the cross-provider acceptance run.

Reads the 150-encounter test sample (data/test_sample.jsonl) and merges the
encounter content from data/train.json (100) and data/val.json (50) to
produce data/test_sample_manifest.json — a single self-contained gold
manifest with per-encounter ``gold_categories`` derived from each
encounter's ground_truth findings.

The output schema mirrors data/val_manifest.json exactly:

  {
    "version": "1.0",
    "split": "test_sample",
    "size": 150,
    "generator": "scripts.build_test_sample_manifest",
    "source": "data/test_sample.jsonl + data/train.json + data/val.json",
    "test_sample_jsonl_sha256": "sha256:...",
    "train_json_sha256": "sha256:...",
    "val_json_sha256": "sha256:...",
    "entries": [
      {
        "encounter_id": "enc_0000",
        "is_flagged": true,
        "split": "train",
        "n_gold_findings": 5,
        "gold_categories": ["cardiology", "diagnosis", "evaluation", "laboratory", "modifier"],
        "gold_rule_ids": ["rule_ecg_001", "rule_em_001", "rule_icd_001", "rule_lab_001", "rule_modifier_25_001"]
      },
      ...
    ]
  }

The two checksums in the manifest (train.json + val.json) match the pins
recorded in data/test_sample_NOTE.md; if either drifts, the script prints
a loud warning but does not refuse to build (the test_sample manifest is
itself a derived artifact — the test_sample.jsonl manifest is the
authoritative encounter-id list).

Run from the project root:
    python scripts/build_test_sample_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_SAMPLE_PATH = PROJECT_ROOT / "data" / "test_sample.jsonl"
TRAIN_PATH = PROJECT_ROOT / "data" / "train.json"
VAL_PATH = PROJECT_ROOT / "data" / "val.json"
OUT_PATH = PROJECT_ROOT / "data" / "test_sample_manifest.json"


def _sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _categories_from_ground_truth(ground_truth: list[dict]) -> list[str]:
    """Return the sorted unique list of categories from the encounter's findings.

    Mirrors the multiset semantics of scripts/score_predictions.py
    (``gold_categories`` is the sorted unique set, ``n_gold_findings`` is
    the raw multiset count). The comparison report's TP/FP/FN is computed
    off the multiset, but exposing the unique set is useful for coverage
    checks and for the human reader.
    """
    cats: list[str] = []
    for gt in ground_truth or []:
        if not isinstance(gt, dict):
            continue
        c = gt.get("category")
        if c and c not in cats:
            cats.append(c)
    return sorted(cats)


def _rule_ids_from_ground_truth(ground_truth: list[dict]) -> list[str]:
    """Return the sorted unique list of rule_ids from the encounter's findings."""
    seen: list[str] = []
    for gt in ground_truth or []:
        if not isinstance(gt, dict):
            continue
        rid = gt.get("rule_id")
        if rid and rid not in seen:
            seen.append(rid)
    return sorted(seen)


def main() -> int:
    if not TEST_SAMPLE_PATH.exists():
        print(f"ERROR: {TEST_SAMPLE_PATH} missing", file=sys.stderr)
        return 1
    if not TRAIN_PATH.exists():
        print(f"ERROR: {TRAIN_PATH} missing", file=sys.stderr)
        return 1
    if not VAL_PATH.exists():
        print(f"ERROR: {VAL_PATH} missing", file=sys.stderr)
        return 1

    # Read the test_sample manifest (just encounter_ids, splits, is_flagged,
    # coverage metadata).
    sample_records: list[dict] = []
    with TEST_SAMPLE_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            sample_records.append(json.loads(line))
    # Read both source splits.
    train = json.loads(TRAIN_PATH.read_text())
    val = json.loads(VAL_PATH.read_text())
    by_id: dict[str, dict] = {e["encounter_id"]: e for e in train}
    for e in val:
        by_id[e["encounter_id"]] = e

    # Resolve each sample id; the test_sample_NOTE.md guarantees all resolve.
    entries: list[dict] = []
    missing: list[str] = []
    for sample_rec in sample_records:
        eid = sample_rec["encounter_id"]
        encounter = by_id.get(eid)
        if encounter is None:
            missing.append(eid)
            continue
        gt = encounter.get("ground_truth", []) or []
        entries.append(
            {
                "encounter_id": eid,
                "is_flagged": bool(encounter.get("is_flagged", False)),
                "split": sample_rec.get("split", encounter.get("split", "unknown")),
                "n_gold_findings": len(gt),
                "gold_categories": _categories_from_ground_truth(gt),
                "gold_rule_ids": _rule_ids_from_ground_truth(gt),
            }
        )

    if missing:
        print(
            f"ERROR: {len(missing)} encounter_ids in test_sample.jsonl could not "
            f"be resolved against train+val: {missing[:5]}...",
            file=sys.stderr,
        )
        return 1

    # Sanity: count categories across the whole sample (used for coverage).
    cat_counter: Counter[str] = Counter()
    for e in entries:
        for c in e["gold_categories"]:
            cat_counter[c] += 1

    manifest = {
        "version": "1.0",
        "split": "test_sample",
        "size": len(entries),
        "generator": "scripts.build_test_sample_manifest",
        "source": "data/test_sample.jsonl + data/train.json + data/val.json",
        "test_sample_jsonl_sha256": _sha256_of(TEST_SAMPLE_PATH),
        "train_json_sha256": _sha256_of(TRAIN_PATH),
        "val_json_sha256": _sha256_of(VAL_PATH),
        "category_distribution": dict(sorted(cat_counter.items(), key=lambda x: -x[1])),
        "entries": entries,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    OUT_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {OUT_PATH} ({len(entries)} entries, {len(cat_counter)} categories)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
