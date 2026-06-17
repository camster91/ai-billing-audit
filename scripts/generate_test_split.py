"""Generate the v0 Auditor test split: 50 val encounters + a manifest.

This is the v0 baseline harness: 50 deterministic synthetic encounters
served as the held-out test set. The audit evaluation (t_1400da1f) reads
this exact output. The fixtures live at:

  data/val.json          — 50 encounters, each with embedded ground_truth
  data/val_manifest.json — per-encounter summary (encounter_id, gold
                           categories, ground_truth_labels)

Both are byte-identical on re-runs (the underlying `ground_truth`
generator is seeded with `train_seed=1729`).

Usage:
    python scripts/generate_test_split.py [--out-dir data]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.ground_truth import (  # noqa: E402
    generate_val_split,
    get_val,
)


def _build_manifest(encounters: list[dict]) -> dict:
    """Derive a per-encounter manifest summary from the val split.

    Each entry exposes:
      - encounter_id:        the synthetic id
      - is_flagged:          whether the source generator flagged the encounter
      - gold_categories:     sorted unique list of category slugs the auditor
                             should surface
      - gold_rule_ids:       sorted list of rule_ids the ground truth cites
      - ground_truth_labels: full ground truth finding dicts (category,
                             severity, suggested_code, rule_id, quote)
      - n_gold_findings:     count of ground truth findings for this encounter
    """
    entries = []
    for enc in encounters:
        gt = enc.get("ground_truth", [])
        entries.append(
            {
                "encounter_id": enc["encounter_id"],
                "is_flagged": enc.get("is_flagged", False),
                "gold_categories": sorted({f["category"] for f in gt}),
                "gold_rule_ids": sorted({f["rule_id"] for f in gt}),
                "ground_truth_labels": gt,
                "n_gold_findings": len(gt),
            }
        )
    return {
        "version": 1,
        "split": "val",
        "size": len(entries),
        "generator": "ai_billing_audit.ground_truth.generate_val_split",
        "train_seed": 1729,
        "notes": (
            "Append-only manifest of the v0 Auditor held-out test split. "
            "Regenerating with the same train_seed yields byte-identical "
            "encounters and ground truth. The 50 val encounters are "
            "disjoint from the 100 train encounters by construction."
        ),
        "entries": entries,
    }


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "data",
        help="Directory to write val.json and val_manifest.json into.",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    val_path = args.out_dir / "val.json"
    manifest_path = args.out_dir / "val_manifest.json"

    # generate_val_split writes val.json (encounters + ground truth).
    val = generate_val_split(val_path)
    # Reload the just-written file so the manifest is built from what
    # landed on disk, not from a separate in-memory copy.
    with open(val_path, "r", encoding="utf-8") as f:
        persisted = json.load(f)
    assert len(persisted) == 50, (
        f"expected 50 val encounters, got {len(persisted)}"
    )

    manifest = _build_manifest(persisted)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    n_findings = sum(e["n_gold_findings"] for e in manifest["entries"])
    n_flagged = sum(1 for e in manifest["entries"] if e["is_flagged"])
    print(
        f"[generate_test_split] wrote {manifest['size']} encounters "
        f"({n_flagged} flagged, {n_findings} gold findings) to "
        f"{val_path}"
    )
    print(
        f"[generate_test_split] wrote manifest with "
        f"{len(manifest['entries'])} entries to {manifest_path}"
    )
    print(
        f"[generate_test_split] val.json sha256 = "
        f"{_file_sha256(val_path)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
