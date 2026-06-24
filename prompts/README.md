# ai-billing-audit / prompts

This directory holds the prompt templates, grader configuration, and
the v0 prompt pin used by the Auditor Agent baseline. Everything
versioned here reproduces a given model behaviour.

## Layout

```
prompts/
├── README.md                # this file
├── MANIFEST.json            # append-only log of canonical optimization runs (R/P + hash per run)
├── grader_config.json       # judge model + temperature=0 + seed=42
├── grader_prompt.txt        # LLM judge system prompt
├── v0/                      # the unoptimized v0 Auditor prompt (baseline reference, canonical)
│   ├── MANIFEST.json        # v0 pin (content_sha256 + paired test split hash)
│   └── auditor_prompt.txt   # verbatim copy of the v0 system prompt
├── v1..v11/                 # archived / superseded prompts; each begins with a STATUS header
│   └── auditor_prompt.txt   # first line: "# STATUS: superseded by v12 AHCIP-only. Do not use."
├── v12/                     # the shipped AHCIP-only Auditor (canonical, current)
│   └── auditor_prompt.txt
└── v13/                     # trimmed v12 derivative (production-candidate; not in MANIFEST)
    └── auditor_prompt.txt
```

**Why only 2 entries in `MANIFEST.json`?**  The codebase iterates through many prompt
versions (v0..v13) but only v0 (the unoptimized baseline) and v12 (the shipped
AHCIP-only rewrite) are canonical.  v1–v7 were US-only single-market iterations,
v8–v11 were multi-market / AHCIP-aware but still carried a US-modifier (-24) leak,
and all eleven are superseded by v12.  v13 is a trimmed derivative of v12 for
production latency.  See `MANIFEST.json`'s `archived_versions` and `status_note`
keys for the full per-version rationale, and the `# STATUS: superseded by v12...`
header at the top of each `v1..v11/auditor_prompt.txt` file.

## v0 Auditor prompt (baseline)

The v0 prompt is the unoptimized auditor system prompt that ships
with the package. It is pinned at `prompts/v0/auditor_prompt.txt`
with its content hash recorded in `prompts/v0/MANIFEST.json`. This is
the baseline the v1+ optimizer is measured against — once MIPROv2
emits a tuned prompt, that one will be pinned at `prompts/v1/`.

The source-of-truth copy lives at
`src/ai_billing_audit/auditor_prompt.txt` (bundled with the package
via `pyproject.toml`'s `package-data`). The pinned copy in
`prompts/v0/` MUST match the bundled copy byte-for-byte. Verify
with:

```bash
diff -q src/ai_billing_audit/auditor_prompt.txt prompts/v0/auditor_prompt.txt
```

If `load_prompt()` is called with no `path=` argument, it loads the
bundled copy at `src/ai_billing_audit/auditor_prompt.txt`. Pass
`path="prompts/v0/auditor_prompt.txt"` to force-load the pinned
copy.

The v0 pin is paired with the 50-encounter held-out test split at
`data/val.json` (see `data/val_manifest.json`); the hashes of both
are recorded in `prompts/v0/MANIFEST.json` so a single
`audit_evaluate.py` run can be reproduced end-to-end by checking the
hashes match.

## Grader reproducibility

The LLM-based grader (`ai_billing_audit.grader.Grader`) is configured
for byte-identical reproducibility via `prompts/grader_config.json`:

* judge `temperature = 0` (fully deterministic greedy decoding)
* judge `seed = 42` (provider-side RNG seeded identically)
* constrained JSON-schema response format (no resampling/repair)
* prompt template loaded from `prompts/grader_prompt.txt` (versioned)

Run `python scripts/verify_grader_reproducibility.py` to confirm two
consecutive grader runs on the same input produce byte-identical
output. See the contract in the section below.

## Files

| File | Purpose |
| --- | --- |
| `grader_config.json` | The grader's LLM-judge configuration. Pins the judge model, sampling temperature (= 0), seed (= 42), and prompt template path. |
| `grader_prompt.txt` | The LLM judge's system prompt. Committed to disk and loaded by `ai_billing_audit.grader.Grader` at construction time. |
| `v0/auditor_prompt.txt` | The v0 Auditor system prompt, pinned verbatim. |
| `v0/MANIFEST.json` | The v0 pin (content hash, byte size, paired test split hash). |
| `MANIFEST.json` | Append-only log of MIPROv2 optimization runs (R/P + hash per run). |

## Reproducibility guarantee (grader)

The grader is configured for **byte-identical** reproducibility:

* `judge.temperature = 0` → fully deterministic greedy decoding.
* `judge.seed = 42` → provider-side RNG seeded identically on every call.
* `judge.response_format.json_schema` with `strict = true` → constrained
  decoding; the provider rejects any response that does not match the
  schema, eliminating any post-hoc resampling or repair.
* The prompt template is loaded from a versioned file
  (`grader_prompt.txt`) that is committed alongside the config.
* `ai_billing_audit.grader.Grader` resolves the model, temperature, seed,
  and prompt path from the config at construction time. No
  environment-variable overrides are consulted at judge-call time.
* The Python-side RNG is seeded with `random.seed(42)` at grader
  construction; no `os.urandom`, no thread-pool reordering, no
  timestamp-based branching.

With these settings, the same `(predicted, ground_truth, context)`
input always produces the same `GraderVerdict` (a `verdict` string,
a `score` float, and a `rationale` string), byte for byte.

Run `python scripts/verify_grader_reproducibility.py` to exercise the
grader twice on a fixed sample input and confirm byte-identical
output.
