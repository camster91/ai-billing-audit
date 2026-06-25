# Submission Replay Guide

> **Audience:** the on-call engineer who needs to re-run a previously
> submitted batch through the auditor (typically after a prompt
> upgrade, e.g. v12 → v13) without making the customer re-upload
> anything.
>
> **Why this exists:** before this script existed, the only way to
> re-audit a prior submission was to re-POST the original 837P file
> to `/encounters/upload/submit`. That path:
> - re-passes the upload validator (different code from the auditor);
> - consumes live Ollama quota;
> - writes a new `upload_jobs.jsonl` row and a new audit_trail chain
>   entry, which violates the "append-only, evidence-of-record" model
>   for *measurement* runs;
> - depends on Caddy, the bearer token, and the customer's 837P file
>   still being available.
>
> Replay avoids all of that. It runs **offline**, against the local
> filesystem, and only writes to `audit_trail` if you pass
> `--write-audit-trail` (off by default — replay is a measurement
> tool, not a customer-facing action).

---

## 1. Where the data lives

The upload portal writes every accepted submission to:

```
/app/data/uploads/YYYY-MM-DD/<submission_id>/
    manifest.json         ← encounter_id → file mapping + SHA-256
    <encounter_id>.edi    ← the 837P claim file (ANSI X12 5010)
    <encounter_id>.txt    ← the clinical note (free-text, UTF-8)
    notes.json            ← optional: parsed/structured note metadata
```

The `manifest.json` schema (loose — the upload portal has iterated
several times):

```json
{
  "submission_id": "abc123",
  "tenant":        "north-bay-fp",
  "uploaded_at":   "2026-06-25T14:32:11Z",
  "encounters": [
    {
      "encounter_id": "nb_2026_06_25_001",
      "edi_file":     "nb_2026_06_25_001.edi",
      "note_file":    "nb_2026_06_25_001.txt"
    }
  ]
}
```

Pre-v0.4.0 submissions don't have a `manifest.json`. For those, build
one by hand from the filenames (the prefix-before-`.edi` IS the
encounter_id) and place it next to the files in a temp dir.

---

## 2. The replay script

The script lives at `scripts/replay_submission.py`. It is a pure-stdlib
Python CLI that only depends on the project's own `ai_billing_audit`
package — no third-party deps, no network calls, no Ollama round-trip
(it calls the auditor function directly).

### 2.1 Basic usage (no eval, no audit-trail writes)

```bash
# On the VPS, as the zorva user:
cd /opt/projects/ai-billing-audit
source .venv/bin/activate

python scripts/replay_submission.py \
    --submission-dir /app/data/uploads/2026-06-25/abc123 \
    --prompt prompts/v12/auditor_prompt.txt
```

Output goes to `runs/replay/<UTC-timestamp>/`:

```
runs/replay/20260625T143211Z/
    aggregate.json           ← micro P/R/F1 + per-rule breakdown
    nb_2026_06_25_001.json   ← per-encounter report
    nb_2026_06_25_002.json
    ...
```

### 2.2 With eval-set comparison

The `--eval-set` flag tells the script which encounters have gold
labels so it can compute per-bucket P/R/F1. For the canonical
regression test, use `data/val_ca.json` (10 encounters, 13 gold
findings, the same set the prompt-iteration playbook uses):

```bash
python scripts/replay_submission.py \
    --submission-dir /app/data/uploads/2026-06-25/abc123 \
    --prompt prompts/v13/auditor_prompt.txt \
    --eval-set data/val_ca.json \
    --baseline-f1 0.690 \
    --max-f1-drop 0.02 \
    --strict
```

Exit codes:

| Code | Meaning                                                              |
|------|----------------------------------------------------------------------|
| 0    | every encounter audited, aggregate F1 within ±`--max-f1-drop`        |
| 1    | one or more encounters failed (parse error, audit error, missing EDI). Per-encounter JSON explains which. |
| 2    | aggregate F1 dropped more than `--max-f1-drop` vs `--baseline-f1`, OR `--strict` was passed without a baseline. **This is the "do not ship" signal.** |
| 3    | bad arguments / missing manifest / submission dir not found.         |

### 2.3 Recording the replay in audit_trail (rare)

If you want the replay to show up in `audit_trail` (e.g., for a
customer-facing "we re-ran your batch on v13" report), pass
`--write-audit-trail`. The script then calls
`audit_actions.append()` (the live, wired hash-chain implementation —
see `prompts/MANIFEST.json` `hash_chain_implementations_note`) for each
encounter. The `model_run_id` is set to `"replay-no-llm"` so the
`audit_trail` makes it clear this was an offline measurement, not a
live audit.

```bash
python scripts/replay_submission.py \
    --submission-dir /app/data/uploads/2026-06-25/abc123 \
    --prompt prompts/v13/auditor_prompt.txt \
    --eval-set data/val_ca.json \
    --write-audit-trail
```

`--write-audit-trail` is **off** by default and should stay that way.
A measurement run that mutates the chain-of-record is harder to
explain to a privacy officer than a measurement run that doesn't.

---

## 3. End-to-end example: v12 → v13 rollout to a single pilot

This is the workflow the prompt-iteration playbook (§7) calls out.
Combining the two:

```bash
# 1. Pull main, confirm clean tree.
cd /opt/projects/ai-billing-audit
git pull --ff-only
git status  # must be clean

# 2. Replay every submission from the past 7 days against the new prompt.
for d in /app/data/uploads/2026-06-1{9,20,21,22,23,24,25}/*/; do
    [ -d "$d" ] || continue
    [ -f "$d/manifest.json" ] || continue
    python scripts/replay_submission.py \
        --submission-dir "$d" \
        --prompt prompts/v13/auditor_prompt.txt \
        --eval-set data/val_ca.json \
        --baseline-f1 0.690 \
        --max-f1-drop 0.02 \
        --out-dir "runs/replay/v13_rollout/$(basename "$d")"
done

# 3. Aggregate across all replay dirs and inspect for drift.
python scripts/aggregate_metrics.py runs/replay/v13_rollout/
```

If step 2 returns exit code `2` for any submission, the v13 prompt
is regressing and **must not be promoted** to the live
`prompts/v12/auditor_prompt.txt` slot. See
`docs/research/PROMPT-ITERATION-PLAYBOOK.md` §8 for the rollback
procedure.

---

## 4. Troubleshooting

### 4.1 "no manifest.json in <dir>"

The submission predates v0.4.0 (the upload portal started writing
manifests in `0.4.0`). Reconstruct one — the file naming is stable:

```bash
cd /app/data/uploads/2026-05-31/old_submission
cat > manifest.json <<EOF
{
  "submission_id": "old_submission",
  "tenant": "unknown",
  "uploaded_at": "$(stat -c %y . | head -c 19)Z",
  "encounters": [
EOF
first=1
for edi in *.edi; do
    eid="${edi%.edi}"
    note="${eid}.txt"
    [ "$first" -eq 0 ] && echo "," >> manifest.json
    printf '    {"encounter_id": "%s", "edi_file": "%s", "note_file": "%s"}' \
        "$eid" "$edi" "$([ -f "$note" ] && echo "$note" || echo null)" \
        >> manifest.json
    first=0
done
echo "" >> manifest.json
echo "  ]" >> manifest.json
echo "}" >> manifest.json
```

### 4.2 "audit_status: parse_error" in a per-encounter report

The 837P file is malformed (truncated upload, wrong segment
terminator, ISA segment missing). The script records the exception
verbatim in `errors[]`. To diagnose:

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from ai_billing_audit import x12_parser
print(x12_parser.parse_837p(open('/app/data/uploads/.../foo.edi').read()))
"
```

If the parser raises, the file is genuinely bad. If it parses but
the per-encounter report still shows `parse_error`, open a bug in
`docs/BUGS_<date>.md` — there's likely a missing X12 code path in
the parser.

### 4.3 "audit_status: audit_validation_error"

The LLM response didn't match `RESPONSE_JSON_SCHEMA` in
`src/ai_billing_audit/auditor.py`. This is rare in replay because
the script uses the same prompt the live path uses. If it happens
across multiple encounters with the same prompt, the prompt
content is suspect — re-check the SHA-256 of the prompt file
against `prompts/MANIFEST.json` `version_hash`.

### 4.4 The aggregate F1 looks "too good"

If `--eval-set` is set but the encounter_ids in the submission
don't overlap with `data/val_ca.json`, the aggregate row is empty
(micro row reads `{"tp": 0, "fp": 0, "fn": 0}`). That's correct —
replay only computes gold-based metrics for encounters that have
gold labels. To get a v12-vs-v13 comparison you need the
submission to include at least one encounter from `data/val_ca.json`
(usually only the dev / pilot test batches do; production batches
do not).

---

## 5. What this script is NOT

- **Not** a customer-facing tool. Customers cannot trigger replays;
  the operator does, after a prompt change.
- **Not** a way to "redo" a real audit. The replay's findings carry
  a `model_run_id = "replay-no-llm"` so they cannot be confused
  with the live audit in `audit_trail`. Any retroactive correction
  must go through the standard `dismiss / modify / comment / upload`
  flow on the operator dashboard.
- **Not** a substitute for the live rollout test in
  `docs/research/PROMPT-ITERATION-PLAYBOOK.md` §5.4. Replay catches
  prompt regressions on past data; the live e2e catches Caddy /
  Ollama / schema drift the offline tests miss.

---

## 6. Further reading

- `docs/research/PROMPT-ITERATION-PLAYBOOK.md` §5.1 — the eval
  decision rule (`±0.02 F1`).
- `docs/RUNBOOK.md` §1 — `audit_actions.append()` and the
  hash-chain invariants.
- `prompts/MANIFEST.json` `notes` and `hash_chain_implementations_note`
  fields — why `audit_actions` is the live module to cite.
- `src/ai_billing_audit/auditor.py` — `RESPONSE_JSON_SCHEMA` (the
  schema `audit_validation_error` means the response violated).