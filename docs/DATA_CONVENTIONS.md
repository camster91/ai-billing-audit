# Data Conventions

This document describes the on-disk format conventions for the Zorva billing-audit
datasets. It exists so that future contributors (and audits) add labels in the
right place without having to read every encounter file end-to-end.

## `data/synth/val_ca.json` — AHCIP held-out set

**File:** `data/synth/val_ca.json`
**Format:** JSON array of encounter objects, one per held-out encounter.
**Market / authority:** Canada / Alberta (AHCIP SOMB).
**Generator:** `src/ai_billing_audit/ground_truth.generate_val_split`
**Manifest:** `data/synth/val_manifest.json` (a higher-level summary; this file
is the source of truth for encounter-level gold labels).

### Per-encounter schema

Each encounter object has these top-level keys:

| Key                | Type           | Purpose                                                                              |
|--------------------|----------------|--------------------------------------------------------------------------------------|
| `encounter_id`     | string         | Unique id (e.g. `ca_ahcip_001`). Used as a join key everywhere.                     |
| `is_flagged`       | bool           | Whether the encounter is expected to produce at least one finding.                   |
| `market`           | string         | Always `"CA"` for this file.                                                         |
| `province`         | string         | Always `"AB"` for this file.                                                         |
| `billing_authority`| string         | `"AHCIP Schedule of Medical Benefits (SOMB)"`.                                       |
| `compliance_law`   | string         | `"PIPEDA"` (and `"HIA"` where Alberta-specific health-information applies).          |
| `clinical_note`    | string         | The doctor's free-text note (used as LLM input).                                     |
| `claim`            | object         | The submitted SOMB claim (codes, modifiers, dx, etc.).                               |
| `rules`            | array          | **DEPRECATED / unused.** Always `[]`. See "rules[] vs ground_truth[]" below.         |
| `ground_truth`     | array of object| **Gold labels.** This is where findings live. Add new gold findings here.            |

### `rules[]` vs `ground_truth[]` — the convention

The two array fields have **different meanings** and contributors sometimes confuse
them. The rule is unambiguous:

- **`ground_truth[]` is the gold.** Every AHCIP billing finding that an ideal auditor
  should emit goes here. The auditor is graded against this list (P/R/F1). Add new
  gold labels here.
- **`rules[]` is reserved for an older US/CPT convention and is `[]` on every
  AHCIP encounter.** Do **not** add findings here. Adding a finding to `rules[]`
  means the auditor will never be scored against it (the scorer reads
  `ground_truth[]`), so the contribution will be silently lost.

If you need to mark an encounter as "no findings expected", leave
`is_flagged: false` and set `ground_truth: []`. Do not encode a no-finding
expectation via a non-empty `rules[]` array.

### `ground_truth[]` element schema

Each entry is a finding object:

```json
{
  "finding_id": "ca1",
  "rule_id": "rule_ahcip_em_level",
  "severity": "info | low | medium | high",
  "category": "evaluation | consultation | ...",
  "suggested_code": "03.04A",
  "clinical_evidence_quote": "comprehensive assessment for diabetes follow-up"
}
```

- `finding_id` — short, unique within the encounter (`ca1`, `ca2`, ...).
- `rule_id` — must match an AHCIP rule id in `src/ai_billing_audit/zorva_context.py`
  or `docs/AHCIP_RULE_REFERENCE.md`. The scorer uses this to bucket P/R/F1.
- `severity` — one of `info | low | medium | high`.
- `category` — high-level grouping; not used by the scorer but useful for dashboards.
- `suggested_code` — the SOMB code the auditor should propose (e.g. `03.04A`,
  `03.03A`). May be `null` if the finding is non-billing (e.g. missing dx).
- `clinical_evidence_quote` — verbatim phrase from `clinical_note` that justifies
  the finding. The auditor's matched-quote is scored against this string. Keep
  it short (one sentence or phrase) and verbatim.

### Editing workflow

1. Open `data/synth/val_ca.json`.
2. Find the encounter by `encounter_id`.
3. Append the new finding to `ground_truth[]`. Do **not** touch `rules[]`.
4. Re-run `python -m scripts.optimize --val-set data/synth/val_ca.json` (or the
   per-rule scorer) to confirm the new finding is reachable.
5. Update `prompts/MANIFEST.json` only if you're adding a new **prompt version**,
   not a new gold finding.

### Related files

- `data/synth/fewshot_ca.json` — the few-shot examples that appear inline in v12
  and earlier auditor prompts. These are *train-time* examples, not val labels.
  Overlap between `fewshot_ca.json` and `val_ca.json` is a leakage bug — keep
  them disjoint.
- `data/synth/val.json` — the larger US/CPT val set with the older schema
  (where `rules[]` *is* the canonical label location for US-side rules).
- `data/synth/val_manifest.json` — generator metadata; regenerating with the
  same `train_seed` yields a byte-identical set.

### Why this convention exists

The US-side auditor (`rules[]`) and the AHCIP auditor (`ground_truth[]`) were
designed in different sessions and inherited different schemas. The AHCIP set
was post-hoc converted from the US schema and `rules[]` was kept as an empty
stub for compatibility — the scorer was rewritten to read `ground_truth[]`
only. This doc makes that explicit so we don't accidentally re-introduce
US-side `rules[]` expectations into AHCIP eval.
