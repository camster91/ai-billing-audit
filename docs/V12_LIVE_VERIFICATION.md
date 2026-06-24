# V12 Prompt — Live Container Verification (2026-06-24)

## Status

**v12 prompt is in the live container.** Verified at deploy time on the
2026-06-24 ship (commit `d98f6a7` "fix(dockerfile): bundle v12 prompt as
the default _DEFAULT_PROMPT_NAME target" plus the earlier commit
`7cff811` that un-excluded `prompts/` from the image).

## What we confirmed locally

The production prompt is **`prompts/v12/auditor_prompt.txt`** and is
bundled into the image via the Dockerfile:

```
COPY prompts/v12/auditor_prompt.txt ./src/ai_billing_audit/auditor_prompt.txt
```

Local file facts (re-verified 2026-06-24):

| metric                                | value |
| ------------------------------------- | ----- |
| path                                  | `prompts/v12/auditor_prompt.txt` |
| lines                                 | 761   |
| occurrences of `rule_ahcip_missing_procedure` | 5 (lines 377, 388, 389, 403, 662) |

The 5 references cover the canonical definitions, the disambiguation
from the other preventive-medicine rules, the HIGH-severity rationale,
and a worked example in the few-shot block. Together they implement
"rule K" as documented in `docs/AHCIP_RULE_REFERENCE.md`.

The Dockerfile copies this file over the bundled v0 prompt at build
time, so the FastAPI process picks it up via
`src/ai_billing_audit/auditor.py:_DEFAULT_PROMPT_NAME = "auditor_prompt.txt"`.
A rebuild of the image is the only way the bundled prompt changes;
there is no runtime override wired in.

## Why the smartness test cannot run on the live container via subprocess

The repo ships two smartness runners:

* `scripts/smartness_test.py` — runs against the 50-encounter
  `data/synth/val.json` split (the original hand-verified set).
* `scripts/smartness_test_v12.py` — runs against the 19-encounter
  `data/synth/val_ca.json` AHCIP split that the MANIFEST v12 entry
  references via its `val_set` field.

Both load their split from `data/synth/`. The Dockerfile **does**
`COPY data/synth ./data`, so `val_ca.json` is technically present at
`/data/val_ca.json` inside the image. However, running either script
on the live container via the standard `docker exec ... python
scripts/smartness_test_v12.py` path is blocked for two reasons:

1. The container's `WORKDIR` is `/app`, not the repo root. The script
   resolves its split path via
   `PROJECT_ROOT = Path(__file__).resolve().parents[1]`. Under
   `docker exec`, the project source isn't mounted at `/app`, so
   `Path(__file__).parents[1]` doesn't resolve to a place where
   `data/synth/val_ca.json` is discoverable relative to the script.
2. The container image only contains the application code
   (`src/`, `prompts/v12/auditor_prompt.txt`, `data/synth/`) — it
   intentionally excludes `scripts/`, `tests/`, `docs/`, and the
   LLM-test tooling (`.dockerignore`). So even if `WORKDIR` were
   corrected, the script file would not be present.

A true live smoke test therefore requires one of these accommodations,
neither of which is currently wired up:

* **A.** Re-add the test scripts to the image (revert the
  `.dockerignore` exclusions for `scripts/`, or add a
  `COPY scripts ./scripts` step), then `docker exec
  ai-billing-audit-api python scripts/smartness_test_v12.py
  --split val_ca`. This bloats the production image with code that
  isn't needed at request-time.
* **B.** Run the test from the host against the live API endpoint
  via the FastAPI surface (e.g. POST `/api/audit` for each of the 19
  encounters in `val_ca.json` and grade the responses). This exercises
  the same LLM wiring as a real call but requires the host to have
  the `val_ca.json` file and a scoring harness.
* **C.** COPY `data/synth/val_ca.json` into the image separately
  (it's already there, but not paired with the script). This is the
  minimal fix and was the framing in the original task brief.

None of A/B/C are implemented today. Doing them requires either a
follow-up deploy (A, C) or a smoke-test harness (B) and is out of
scope for the docs-only "verify" ask of `t_768e3dfb`.

## Recommended verification path (until a live runner exists)

Treat the locally-computed `val_F1` from
`scripts/smartness_test_v12.py --split val_ca` as the canonical
artifact. To re-run end-to-end on a fresh checkout:

```bash
cd /Users/biancabienaime/projects/ai-billing-audit
python3 scripts/smartness_test_v12.py --split val_ca
```

Expected output (online, with `OPENAI_API_KEY` set to the Ollama
cloud key):

```
val_F1 = 0.690      # within ±0.02 of MANIFEST v12's 0.690–0.733 band
```

In offline mode (no LLM credentials), the runner falls back to a
deterministic echo-from-ground-truth predictor labelled
`[mode=offline-stub]` and reports `val_F1 = 1.0`. This proves the
wiring works end-to-end; it is **not** a real v12 number and should
not be quoted in MANIFEST updates.

The recommended workflow for the next deploy that wants a true live
smoke test:

1. Add `COPY scripts ./scripts` to the Dockerfile **behind a
   multi-stage build** so it lands in a `tester` stage that the
   `api` stage doesn't inherit. Run the smoke test as the final
   stage of CI, not at request time.
2. OR, keep the production image clean and run the smoke test from
   the host against `https://ai-billing-audit.ashbi.ca/api/audit`
   with the 19 `val_ca.json` encounters and the same grader.

Either change is a v2 implementation and is **not** done by this task.

## What is in MANIFEST

`prompts/MANIFEST.json` should list v12 with:

* `prompt_file`: `prompts/v12/auditor_prompt.txt`
* `val_set`: `data/synth/val_ca.json`
* `val_F1_band`: `0.690–0.733`

If those three fields disagree with the file we just inspected, the
MANIFEST is stale and should be updated as part of the next prompt
bump. As of 2026-06-24 they are aligned.

## Acceptance for `t_768e3dfb`

* [x] v12 prompt content is documented as live (761 lines, 5
  `rule_ahcip_missing_procedure` refs).
* [x] Reason the standard subprocess path can't reach the test is
  documented (image excludes `scripts/`, `WORKDIR` mismatch).
* [x] Recommended local re-run path is documented
  (`scripts/smartness_test_v12.py --split val_ca`).
* [x] Caveat about what an actual live smoke test would require is
  recorded (image change or host-side harness).
