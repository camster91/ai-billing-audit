# Daily Ops Checklist

> **Time budget:** 5 minutes. **Audience:** the operator on
> morning shift. **Cadence:** once per business day, before 09:00
> local time. **Failure mode of skipping this:** silent drift
> between the prompt on disk, the prompt in `MANIFEST.json`, the
> Ollama key, and the live URL — all of which produce embarrassing
> customer-visible bugs weeks later.
>
> **Pair this checklist with** `docs/RUNBOOK.md` (the deep-dive
> runbook — only consult it when this checklist's first column
> shows a red light).

---

## The checklist

Tick each box in order. The order is chosen so each step's failure
mode is visible before you spend time on the next.

### 1. Live URL status  (≤60 s)

```bash
curl -fsS --max-time 10 https://ai-billing-audit.ashbi.ca/healthz | jq .
```

Expected: `{"status": "ok", ...}` with HTTP 200.

| Result           | Action                                                                |
|------------------|-----------------------------------------------------------------------|
| 200 OK           | Tick. Continue.                                                       |
| 5xx              | **Stop.** Go to `docs/RUNBOOK.md` §3 (Availability). The 5xx-monitor (`scripts/monitor_live_url.py`) will already be paging. |
| Timeout / hang   | The monitor will page in ≤15 min. Don't wait — start the Caddy / Ollama / Postgres triage now. |
| `audit_status: ok` field present | Good. (The `/healthz` payload includes it; means the API can reach its deps.) |
| `audit_status: degraded` | **Tick with note.** Investigate within the hour but proceed with the rest of the checklist. |

### 2. 5xx-monitor heartbeat  (≤30 s)

```bash
# On the VPS, check the cron-driven monitor ran in the last 10 min.
ls -lt /var/log/monitor_live_url.log 2>/dev/null | head -1
# Then a one-shot probe to confirm the monitor itself is alive:
ZORVA_MONITOR_URL=https://ai-billing-audit.ashbi.ca/healthz \
  python /opt/projects/ai-billing-audit/scripts/monitor_live_url.py --once
```

Expected: log line within last 10 min, exit 0, no webhook fired.

If the monitor itself has crashed, restart it from the cron
entry (see `docs/MONITORING.md` §3.2). A silent monitor is worse
than no monitor.

### 3. Overnight batch jobs  (≤60 s)

```bash
# Inspect the upload-job log for the last 24h.
jq -r '"\(.uploaded_at) \(.submission_id) \(.tenant) \(.audit_status)"' \
   /app/logs/upload_jobs.jsonl | tail -50

# And the worker (background LLM queue) log.
tail -30 /app/logs/worker.log
```

Look for: any `audit_status` ≠ `"ok"`, any exception traceback, any
job that started but didn't finish (a half-row in `upload_jobs.jsonl`
with no matching `audit_trail` entry is the smoking gun).

If you see jobs that didn't finish, **do not** cancel them — let the
worker pick them up on its next cycle, then watch for completion. If
a job is stuck for >30 min, file a bug under `docs/BUGS_<date>.md`.

### 4. Prompt + MANIFEST drift  (≤60 s)

This is the highest-leverage check. Prompt drift is silent — the API
still returns 200, the auditor still emits findings, but the findings
are now from the wrong prompt and the audit_trail hash chain references
the wrong SHA-256.

```bash
# On the VPS:
cd /opt/projects/ai-billing-audit

# 4a. The active prompt's SHA-256 (as the running container sees it).
sha256sum prompts/v12/auditor_prompt.txt

# 4b. The MANIFEST.json entry for v12's version_hash.
jq -r '.entries[] | select(.status=="active") | .version_hash' \
   prompts/MANIFEST.json

# 4c. (sanity) The git-tracked version's hash.
git log -1 --format='%H' -- prompts/v12/auditor_prompt.txt
```

| Result                                                                      | Action                                                |
|-----------------------------------------------------------------------------|-------------------------------------------------------|
| 4a == 4b == 4c                                                              | Tick. Continue.                                       |
| 4a ≠ 4b                                                                     | **Stop.** Either the prompt was edited out of band (revert it: `git checkout -- prompts/v12/auditor_prompt.txt`) **or** MANIFEST.json was edited without updating `version_hash` (see `docs/research/PROMPT-ITERATION-PLAYBOOK.md` §6 for the correct procedure). |
| 4a ≠ 4c                                                                     | **Stop.** Prompt file modified without commit. Revert or commit — never leave an uncommitted prompt on a live VPS. |
| 4c ≠ latest commit                                                          | **Stop.** VPS is on a stale checkout. Pull or roll forward per the runbook. |

Do not skip this even on "nothing changed" days. The failure mode
that's hardest to debug is the one that accumulates silently across
weeks of skipped checklists.

### 5. Ollama / LLM key health  (≤60 s)

The LLM provider API key rotates on the provider's policy, not ours.
If it rotates and we don't notice, every audit returns 401 and the
5xx-monitor only catches the *application's* view, not the
*provider's* view (because the API will return a wrapped 401 → the
application converts to 200 with `audit_status: "ok"` and an empty
findings list, which is the **most dangerous failure mode** because
nothing pages).

```bash
# Probe the provider directly.
curl -fsS --max-time 10 \
  -H "Authorization: Bearer $LLM_API_KEY" \
  "$LLM_BASE_URL/models" | jq '.data[0].id'

# Confirm the key in the .env is the key the container is using.
docker exec zorva-api env | grep -E 'LLM_(API_KEY|BASE_URL|PROVIDER)'
```

| Result                                            | Action                                                          |
|---------------------------------------------------|-----------------------------------------------------------------|
| Returns the expected model id (e.g., `minimax-m2`) | Tick. Continue.                                                |
| 401 / 403                                         | Key rotated. Update `.env`, restart the container, re-run step 1. **File a `BUGS_<date>.md` entry** — silent key rotation is a privacy incident in waiting (findings are silently empty). |
| Network error                                     | Provider outage. Step 1 will catch it; skip to step 6.           |
| `LLM_API_KEY` in `.env` is empty or "***"         | **Stop.** The `deploy-to-vps.sh` script's safety check is being bypassed. Pull the key from the secrets manager and restart. |

### 6. (Only if anything failed) Open the right runbook

| Failed step | Go to                                                            |
|-------------|------------------------------------------------------------------|
| 1 (live URL)| `docs/RUNBOOK.md` §3                                             |
| 2 (monitor) | `docs/MONITORING.md` §3.2 (cron entry) and §4 (webhook config)    |
| 3 (jobs)    | `docs/RUNBOOK.md` §3                                             |
| 4 (prompt)  | `docs/research/PROMPT-ITERATION-PLAYBOOK.md` §8 (rollback)        |
| 5 (LLM key) | `SECURITY.md` (treat as S4 if no PHI exposure) / `docs/RUNBOOK.md` §3 |

If the failure touches PHI or `audit_trail`, jump to
`docs/operations/INCIDENT-RESPONSE.md` §1.2 — that's a privacy
incident, not an ops one.

---

## What "5 minutes" means

| Step | Wall budget |
|------|-------------|
| 1. Live URL                   | 60 s |
| 2. 5xx-monitor               | 30 s |
| 3. Overnight batch jobs      | 60 s |
| 4. Prompt + MANIFEST drift   | 60 s |
| 5. Ollama / LLM key health   | 60 s |
| **Total**                    | **~5 min** |

If any single step exceeds its budget, stop and write a
`BUGS_<date>.md` entry. A slow step is usually a precursor to a
failed step.

---

## Things this checklist does NOT cover

These are *not* "every-morning" checks. Each has its own cadence:

| Item                                                | Cadence        | Where                       |
|-----------------------------------------------------|----------------|-----------------------------|
| `audit_trail` chain verification                   | Monthly        | `docs/RUNBOOK.md` §1.2      |
| Disaster recovery (DB restore from backup)          | Quarterly      | `docs/RUNBOOK.md` §5 (TODO) |
| VPS snapshot / Monarx scan                          | Weekly         | Hostinger dashboard         |
| Privacy incident drill                              | Quarterly      | `docs/operations/INCIDENT-RESPONSE.md` §11 |
| `MANIFEST.json` archive integrity                  | On every prompt bump | `docs/research/PROMPT-ITERATION-PLAYBOOK.md` §6 |
| Ollama usage / quota                                | Weekly         | Provider dashboard          |
| Customer billing reconciliation                    | Monthly        | Per BAA §6 (see `docs/BAA_TEMPLATE_*.md`) |

If a task appears in the table above but not on the daily list,
that's intentional — daily would mean operator fatigue and the
checklist stops being done at all.

---

## When the checklist itself drifts

This document is in git. If you find yourself skipping a step
because it's "always green," propose removing the step (PR + a
short note in `CHANGELOG.md`). If you find yourself doing an
unscripted check, propose adding it here (same process). The
checklist should be the union of "always useful" — neither more
nor less.

If you change this checklist, bump the version footer below.

---

## Further reading

- `docs/RUNBOOK.md` — the deep-dive runbook (consult when this
  checklist shows a red light).
- `docs/operations/INCIDENT-RESPONSE.md` §1.2 — when a red light
  is actually a privacy incident.
- `docs/MONITORING.md` — the 5xx-monitor design + cron entry.
- `docs/research/PROMPT-ITERATION-PLAYBOOK.md` §4 / §6 — why step
  4 is the highest-leverage check on this list.
- `SECURITY.md` — what to do if the LLM key rotation looks
  suspicious (could be a credential-leak indicator, not a routine
  rotation).

---

*Checklist version: 1.0 — 2026-06-25.*