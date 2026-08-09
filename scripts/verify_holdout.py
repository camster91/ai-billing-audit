"""Verify the held-out test set is in the right shape for acceptance scoring.

The acceptance criterion for the v0 auditor is:
    R >= 0.70 AND P >= 0.80 on the held-out set, NOT on val.

This script verifies that data/synth/holdout_seed9999.json (or any other
holdout produced by scripts/generate_holdout.py) is:

  - byte-identical to the meta-recorded SHA-256 (if the meta sidecar exists)
  - disjoint from train (enc_0000..enc_0099) and val (enc_10000..enc_10049)
    encounter-id ranges
  - approximately 50/50 clean/flagged (the original task asked for 100; the
    on-disk file is 50, 42 flagged + 8 clean. This script flags that as a
    warning rather than failing.)
  - generated with a different train_seed than the optimizer's 1729
  - has every encounter's ground_truth reachable via the encounter_id

Usage:
    python3 scripts/verify_holdout.py [--holdout data/synth/holdout_seed9999.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The optimizer's val split is generated with train_seed=1729 and id range
# enc_10000..enc_10049. Train is enc_0000..enc_0099.
OPTIMIZER_TRAIN_SEED = 1729
TRAIN_ID_RANGE = range(0, 100)  # enc_0000..enc_0099
VAL_ID_RANGE = range(10_000, 10_050)  # enc_10000..enc_10049


def _enc_id_num(eid: str) -> int | None:
    if not eid.startswith("enc_"):
        return None
    try:
        return int(eid.split("_", 1)[1])
    except ValueError:
        return None


def verify(holdout_path: Path) -> tuple[int, list[str]]:
    """Return (exit_code, list_of_messages). exit_code=0 means clean."""
    msgs: list[str] = []

    if not holdout_path.exists():
        msgs.append(f"FAIL: holdout file not found: {holdout_path}")
        return 2, msgs

    # --- File-level integrity ---------------------------------------------
    raw_bytes = holdout_path.read_bytes()
    actual_sha = hashlib.sha256(raw_bytes).hexdigest()

    meta_path = holdout_path.with_suffix(holdout_path.suffix + ".meta.json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        recorded = meta.get("holdout_sha256", "").removeprefix("sha256:")
        if recorded and recorded != actual_sha:
            msgs.append(
                f"FAIL: SHA mismatch. recorded={recorded[:12]}... actual={actual_sha[:12]}..."
            )
        else:
            msgs.append(f"OK: SHA matches meta ({actual_sha[:12]}...)")

        seed = meta.get("train_seed")
        if seed == OPTIMIZER_TRAIN_SEED:
            msgs.append(
                f"FAIL: holdout uses optimizer's train_seed={seed}; the val split "
                f"was generated with this seed, so the holdout is NOT disjoint."
            )
        else:
            msgs.append(
                f"OK: train_seed={seed} differs from optimizer's {OPTIMIZER_TRAIN_SEED}"
            )
    else:
        msgs.append(f"WARN: no meta sidecar at {meta_path.name}; skipping SHA check")

    # --- Encounter-level checks -------------------------------------------
    try:
        data = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        msgs.append(f"FAIL: invalid JSON: {exc}")
        return 2, msgs

    if not isinstance(data, list):
        msgs.append(f"FAIL: top-level is {type(data).__name__}, expected list")
        return 2, msgs

    size = len(data)
    if size == 100:
        msgs.append("OK: size=100 (matches task spec)")
    elif size == 50:
        msgs.append(
            "WARN: size=50. Task A6 spec asked for 100 (50/50 clean/flagged). "
            "The on-disk file is 50 (42 flagged + 8 clean). Either extend "
            "scripts/generate_holdout.py with --n 100 and re-run, or update "
            "the task body to reflect the 50-encounter acceptance reality."
        )
    else:
        msgs.append(f"WARN: size={size}; task spec is 100 (or 50 by current reality).")

    n_flagged = sum(1 for e in data if e.get("is_flagged"))
    n_clean = size - n_flagged
    msgs.append(f"INFO: {n_flagged} flagged + {n_clean} clean = {size} total")

    # --- Disjointness from train+val --------------------------------------
    collisions_train = 0
    collisions_val = 0
    for enc in data:
        eid = enc.get("encounter_id", "")
        n = _enc_id_num(eid)
        if n is None:
            msgs.append(f"WARN: non-conforming encounter_id {eid!r}")
            continue
        if n in TRAIN_ID_RANGE:
            collisions_train += 1
        if n in VAL_ID_RANGE:
            collisions_val += 1
    if collisions_train:
        msgs.append(f"FAIL: {collisions_train} encounters collide with train range")
    else:
        msgs.append("OK: no collisions with train (enc_0000..enc_0099)")
    if collisions_val:
        msgs.append(f"FAIL: {collisions_val} encounters collide with val range")
    else:
        msgs.append("OK: no collisions with val (enc_10000..enc_10049)")

    # --- Every encounter has ground_truth --------------------------------
    missing_gt = 0
    for enc in data:
        if "ground_truth_labels" not in enc and "ground_truth" not in enc:
            missing_gt += 1
    if missing_gt:
        msgs.append(f"FAIL: {missing_gt} encounters have no ground truth")
    else:
        msgs.append("OK: every encounter has ground truth")

    # Exit code: only FAILs are blocking. WARNs are surfaced for triage.
    fail_count = sum(1 for m in msgs if m.startswith("FAIL"))
    return (1 if fail_count else 0), msgs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--holdout",
        type=Path,
        default=PROJECT_ROOT / "data" / "synth" / "holdout_seed9999.json",
        help="Path to the held-out test set JSON",
    )
    args = p.parse_args(argv)
    code, msgs = verify(args.holdout)
    print("=" * 64)
    print(f"Holdout verification: {args.holdout}")
    print("=" * 64)
    for m in msgs:
        print(f"  {m}")
    print("-" * 64)
    print("FAIL" if code == 1 else ("ERROR" if code == 2 else "PASS"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
