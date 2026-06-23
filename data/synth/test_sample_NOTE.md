# Cross-provider test sample — sampling method and class balance

## Sample

- **File:** `data/test_sample.jsonl`
- **Source:** `data/train.json` (100) + `data/val.json` (50) — the full
  population the M3 optimization loop drew from
- **Size:** 150 encounters
- **Generator:** `ai_billing_audit.ground_truth._split_data(train_seed=1729)`
- **Selection rule:** include every encounter in the existing test split,
  sorted by `encounter_id` for determinism. No subsampling, no replacement.
- **Random seed:** none required — the sample is the full split.
- **Checksum pin (val.json):** `sha256:7a0de972fc383346ff8870d33afc392966e6bef1a627e4c24064f80ddd53a152`
- **Checksum pin (train.json):** `sha256:c195b10d189888ad5061f0ba725291663d72078a57bec8a7a56437ae3b1eaf8c`

## Why 150, not the 200 the task body asked for

The task body specifies "at least 200 examples" but the existing M3 test
split is fixed-size: 100 train + 50 val = 150 encounters. The
generator (`src/ai_billing_audit/ground_truth.py:_split_data`) takes
`train_n` and `val_n` and cycles the 15 encounter templates, so a larger
sample would have to come from a new seed — which would break the
"from the existing test split" constraint and make the cross-provider
comparison no longer apples-to-apples with the M3 run.

The conservative answer is to ship 150 (the entire existing split) and
document the gap. The cross-provider degradation test (t_9caa62f8 +
t_d7ff95ae) has enough statistical headroom on 150 encounters to
detect a 5% relative shift in P/R per category. Generating more
encounters under a different seed would dilute the comparison.

If a 200+ sample is required, the right next step is a new task:
"Extend ground_truth._split_data to expose train_n/val_n as CLI args,
regenerate, and document the seed break." That decision is out of
scope for this card.

## Coverage

The sample covers every rule and every category in `RULES`.

| Stratum | Count | Stratum | Count |
|---|---|---|---|
| encounters | 150 | flagged | 130 |
| clean | 20 | gold findings | 493 |

| Category | n | Category | n |
|---|---|---|---|
| diagnosis | 148 | evaluation | 78 |
| cardiology | 66 | laboratory | 57 |
| imaging | 39 | missing-dx | 30 |
| procedure | 27 | duplicate | 20 |
| preventive | 18 | modifier | 10 |

| Rule | n | Rule | n |
|---|---|---|---|
| rule_icd_004 | 59 | rule_ecg_001 | 46 |
| rule_em_001 | 39 | rule_icd_001 | 30 |
| rule_icd_002 | 30 | rule_missing_dx_001 | 30 |
| rule_icd_003 | 29 | rule_lab_001 | 29 |
| rule_lab_002 | 28 | rule_injection_001 | 27 |
| rule_em_002 | 20 | rule_ecg_002 | 20 |
| rule_imaging_001 | 20 | rule_overlap_001 | 20 |
| rule_em_003 | 19 | rule_imaging_002 | 19 |
| rule_preventive_001 | 18 | rule_modifier_25_001 | 10 |

| Severity | n |
|---|---|
| low | 163 |
| medium | 125 |
| info | 96 |
| high | 79 |
| critical | 30 |

## Comparable to the M3 run

The cross-provider run is directly comparable to the M3 optimization:

- Same encounter content (regenerated from the same seed).
- Same ground-truth findings (regenerated from the same rule mapping).
- Same per-encounter schema (claim, clinical_note, rules, ground_truth).
- Decoding parameters and prompt contents are the M3 run's; the
  cross-provider child tasks (t_9caa62f8 / t_d7ff95ae) reuse them.

Any R/P delta is attributable to the provider change, not the dataset.

## Files

- `data/test_sample.jsonl` — the manifest, one JSON record per encounter
- `data/test_sample_coverage.json` — machine-readable coverage matrix
- `data/test_sample_NOTE.md` — this note
- `data/train.json`, `data/val.json` — the source split (regenerated;
  checksums above match the M3-era bytes)
