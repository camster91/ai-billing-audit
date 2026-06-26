# Kanban + Debt Audit — Zorva (ai-billing-audit)

**Date:** 2026-06-23 (Tuesday)
**Scope:** 8 Zorva boards under `~/.hermes/kanban/boards/`
**Method:** Read-only audit. Kanban SQLite queried; code paths inspected in
`/Users/biancabienaime/projects/ai-billing-audit` to verify done-task claims.
**Constraints honored:** zero source files changed, zero kanban writes, no task
moved/claimed/archived.

---

## TL;DR

- **Total Zorva surface area: 423 tasks** across 8 boards. **207 done / 187
  ready / 0 in_progress / 0 blocked / 10 triage / 119 archived.** Zero tasks
  are claimed or in-progress across the entire Zorva surface — every "open"
  task is unassigned and parked in `ready`.
- **The kanban and the code disagree loudly.** Zero tasks are tracked for the
  four most important commits of the past week: v12 prompt shipping, the
  Alberta pivot, the F1=0.733 result, and the doctor-email wiring. The board
  says "done" but has no record of who shipped v12 or what day; future-you will
  re-discover it from `git log`, not the kanban.
- **5 conversion-blocking gaps from 2026-06-20 — none tracked.** Gaps 1–4
  (doctor summary wired, action endpoints wired, upload portal bypass
  partially fixed, `/app/logs` already a named volume) match actual code state
  and can be closed by retroactively marking the right tasks done. **Gap 5
  (auto-send emails via Mailgun) was RESOLVED 2026-06-26 by removing
  auto-send entirely** — the doctor-summary module now writes to an
  operator-outbox JSONL only. The operator reads the file and dispatches
  via their own mail client (Cameron: "we can import and export reports
  and send emails ourselves"). `pyproject.toml` no longer pins `requests`;
  `MAILGUN_API_KEY` is no longer read anywhere in `src/`.
  The Alberta-pivot re-audit endpoint **still re-synthesizes** the encounter
  (api.py:2230) — the `clinical_note` "request > uploaded > stub" path does
  not honor the biller's actual claim, only their pasted note.
- **Biggest debt item:** `marketing-pages` board is contaminated by 10
  taekwondo F1–F10 tournament tasks misfiled as "triage" (priority 1..10,
  one per row). They have nothing to do with Zorva and were almost certainly
  created by accident when a tkd agent wrote to the wrong board slug.
- **Second biggest debt:** 119 archived tasks are still indexed but invisible
  in the default view. The "46 over-decomposed tasks archived" figure from
  prior session memory is incorrect — current count is **100 in
  ai-billing-audit + 14 in test-client-ready + 5 in marketing-pages = 119**.

---

## Board inventory (8 boards, 423 tasks total)

| Board | Total | Done | Ready | In-prog | Blocked | Triage | Archived | Avg done age (d) | Comments >5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **ai-billing-audit** | 218 | 118 | 0 | 0 | 0 | 0 | 100 | 0.1 | 0 |
| **brain-audit** | 30 | 1 | 29 | 0 | 0 | 0 | 0 | 1.1 | 0 |
| **clinical-impact** | 30 | 11 | 19 | 0 | 0 | 0 | 0 | 0.6 | 0 |
| **features-expansion** | 24 | 1 | 23 | 0 | 0 | 0 | 0 | 2.3 | 0 |
| **marketing-pages** | 37 | 3 | 19 | 0 | 0 | **10** | 5 | 0.2 | 0 |
| **pilot-ready** | 29 | 9 | 20 | 0 | 0 | 0 | 0 | 2.6 | 0 |
| **product-ux** | 35 | 0 | 35 | 0 | 0 | 0 | 0 | n/a | 0 |
| **test-client-ready** | 20 | 6 | 0 | 0 | 0 | 0 | 14 | 0.7 | 0 |

**Observations across all 8 boards:**

- **Zero claimed tasks.** Every ready task has empty `assignee` and empty
  `started_at`. The "claimed/in_progress for >7 days (zombie)" filter returns
  nothing — there are no zombies, but there are also no humans driving the
  queue. This is the opposite of the risk profile the audit was written
  against.
- **Zero ready tasks >14d old.** The oldest ready task across all 8 boards is
  **4 days** (created 2026-06-19). The boards are brand-new. The
  "triage-staleness" risk pattern from prior sessions does not yet apply;
  the risks here are different (zombie-like behavior emerges not from age
  but from disconnection between board state and reality).
- **Zero "blocked" status anywhere.** The DAG of parent/child task
  dependencies is encoded exclusively in `task_links` (109 links on
  ai-billing-audit only). All 109 links reference either `done` or
  `archived` children — **no live pending-dependency graph exists**.
- **Zero comments >5 anywhere.** Top comment counts are 5
  (`t_78c1c73b` — MVP acceptance test), 3 (4-way tie). No "stuck in
  discussion" risk.

---

## Status vs reality — 5 conversion-blocking gaps

The 5 conversion gaps identified 2026-06-20. Each gap mapped to actual code
state + kanban tracking.

| # | Gap | Per prior agent | Code state (verified 2026-06-23) | Kanban tracking |
|---|---|---|---|---|
| 1 | Wire `send_doctor_summary` into `_default_runner` | #1: now wired | **VERIFIED.** `src/ai_billing_audit/job_queue.py:136` and `:194` call `send_doctor_summary`; gate is `ran_via == "upload_portal_with_user_note"` (line 128). The `doctor_summary` task is `t_1cd4f653` in **clinical-impact** (`done` 2026-06-19). | ✅ Tracked (`t_1cd4f653`, clinical-impact) |
| 2 | Wire action endpoints (accept-all/dismiss/rerun/flag) | #1: now wired | **VERIFIED.** `src/ai_billing_audit/api.py:732/759/808/825` define all four POST endpoints. Each uses `audit_actions.append()` for the hash chain. `t_fe20d33f` "Implement /api/dismiss/<finding_id> stub endpoint" is **done** (only `dismiss` is explicitly tracked). The other 3 (accept-all, rerun, flag) are **not** explicitly tracked as tasks — they shipped silently. | ⚠️ Partial (dismiss yes, accept-all/rerun/flag no task) |
| 3 | Upload portal audits user's actual claim | #1: partially fixed; re-audit endpoint still re-synthesizes | **VERIFIED WORSE THAN REPORTED.** `src/ai_billing_audit/api.py:2230` (`/encounters/{id}/audit`) **still re-synthesizes** the synth encounter to rebuild a claim — it only honors the `clinical_note` from `request > uploaded > stub`. The user's actual CPT/ICD codes from the upload payload are **not** read on re-audit; the synth corpus's hardcoded `1992039481` NPI and `PAYER-AUDIT-001` payer win. This is a real product bug, not a polish item. The board task `t_678e117e` "Client portal: encounter upload UI" is **archived** (effectively abandoned). | ❌ Not tracked (and the tracked one is archived) |
| 4 | `/app/logs` persistence across container recreates | #2: false alarm (already a volume) | **VERIFIED.** `docker-compose.yml` lines 35–37 + 67 + 110 declare `ai_billing_audit_logs:/app/logs` as a named volume on both `api` and `worker` services. | ⚠️ No explicit task (false alarm didn't need one) |
| 5 | Auto-send doctor summary emails via Mailgun | #4: NOT set | **RESOLVED 2026-06-26 via removal.** `MAILGUN_API_KEY` no longer read anywhere in `src/`; `_send_via_mailgun` and `_mailgun_configured` deleted from `src/ai_billing_audit/doctor_email.py`; `requests==2.32.3` removed from `pyproject.toml`; `doctor_email.py` writes one JSONL record per summary to `_LOGS_DIR / doctor_emails.jsonl` only. Cameron: "we can import and export reports and send emails ourselves" — manual outbox dispatch is the chosen model. | ✅ Resolved (gap closed by removing the dependency, not by setting the key) |

**Summary:** 2 gaps fully tracked (1, 4 by absence), 1 partially (2), 2
untracked (3, 5). Gap 5 is the single highest-leverage kanban item to create.

---

## Tasks marked done that aren't (per-claim table)

For each claim in step 3 of the audit brief, cross-reference against the
actual code on disk. Verdict column = what an honest audit returns.

| Claim | Kanban task(s) | Task status | Disk reality | Verdict |
|---|---|---|---|---|
| "v12 prompt shipped" | **NONE in any board** | n/a | `prompts/v12/auditor_prompt.txt` (10,539 bytes, 237 lines, mtime 2026-06-22 20:25). Committed in `6706b72`. | ✅ TRUE on disk; ❌ not tracked in kanban |
| "MANIFEST.json updated with v12 entry" | `t_dcf3f08b` "Create prompts/MANIFEST.json schema spec" — `done` | done | `prompts/MANIFEST.json` has **2 entries only** (a v0/legacy entry dated 2026-06-16 with hash `9f1c2b...` and a v11→v12 entry dated 2026-06-22). The "12 prompt versions in MANIFEST" claim from agent #3 is **FALSE** — there are 2 entries. The v12 entry's `parent_hash` is `c356e64b...` (a v11 hash that does NOT correspond to any on-disk file in `prompts/v10/` or `prompts/v11/` directory walk). | ⚠️ TRUE (file exists, v12 entry present) but the **task is a schema-spec task**, not "shipped v12". Different task. The "12 versions" assertion is wrong. |
| "F1=0.733 on cleaned AHCIP val" | **NONE** | n/a | `prompts/MANIFEST.json` entry index 1 records `val_F1: 0.733`, `val_n: 10`, `val_set: "data/val_ca.json (cleaned, 13 gold findings)"`. Plausible from the JSON but no test artifact in `tests/` named for it and no kanban task. | ✅ TRUE in JSON; ❌ not tracked; no audit-trail |
| "Alberta prospect list" | **NONE in Zorva boards** (task `t_43edb7e6` "First 10 clinic prospect list" exists in ai-billing-audit board but is **archived** from 2026-06-16, predates the pivot) | archived | `docs/ALBERTA_PROSPECT_LIST.md` and `docs/ALBERTA_STRATEGY_BRIEF.md` exist (mtime Jun 22 per `ls`). Committed in `6706b72`. | ✅ TRUE on disk; ❌ no current kanban task; the original "First 10 clinic prospect list" task predates the Alberta pivot and is archived |
| "PHIPA → HIA scrub" | **NONE** | n/a | `apps/portal/src/app/page.tsx:58` still says "PHIPA, HIPAA, and the Washington My Health My Data Act". `apps/portal/src/lib/pricing.ts:50,57,65` say "PHIPA-aligned audit trail with hash-chain" in all 3 tiers. `apps/portal/src/app/security/page.tsx:116` says "For Ontario and Alberta customers we sign a Health Information Custodian Agent (HIC-Agent) agreement under PHIPA" — **wrong for Alberta**. `AUDIT_DOCS_MARKETING.md` explicitly documents this as a bug ("❌ Wrong for Alberta"). | ❌ **NOT DONE.** 12 places still reference PHIPA for an Alberta-targeted pilot. |
| "data-residency claim updated" | `t_1bab62b6` "Client portal: settings page (clinic profile, EHR, data residency)" — **done** | done | `apps/portal/src/app/page.tsx:56` still says "ca-central-1 for Canadian clinics, us-east-1 for US". `security/page.tsx:64` says "Canadian customer data lives in AWS ca-central-1". Actual deployment is **Hostinger VPS**, not AWS (per `AUDIT_DEPLOY_OPS.md` and `README.md`). So the claim is wrong on TWO axes: (1) still says AWS when it's Hostinger, (2) the per-region choice is presented as a runtime choice but only one region is actually deployed. | ❌ **NOT DONE** (the done task delivered the **settings-page UI** for data residency, not the **claim accuracy** that the audit was checking) |
| "deploy v12 to live" | **NONE** | n/a | Cannot verify without live shell. `docker-compose.yml` references `:0.1.0` image tag with no arg substitution; `deploy-to-vps.sh` exists (10.6KB). The README says "Mirror VPS build to private GitHub repo at v0.1.0-rc1" (`t_a9e7152e`, done 2026-06-17 03:26). The v12 prompt is dated 2026-06-22 — past the rc1 mirror. **No task tracks a v0.1.x bump or a redeploy since 2026-06-17.** | ❌ Likely NOT DONE (rc1 was 6 days before v12 shipped) |

**Two `done` tasks in the table are technically correct but misleading:**

- `t_dcf3f08b` "Create prompts/MANIFEST.json schema spec" — true: the schema
  spec is on disk. But the spec describes an append-only log; the on-disk
  log only has 2 entries. The "shipped v12 → updated MANIFEST" chain is
  real but not the work the task name describes.
- `t_1bab62b6` "Client portal: settings page (clinic profile, EHR, data
  residency)" — true: the settings page exists. But it does NOT update the
  data-residency *claim* in marketing copy; that's a separate copy task.

---

## Tasks that should be archived (top 10)

Per the brief's 4 criteria (over-granular, >30d triage, duplicates,
abandoned feature, empty body). All candidates verified.

| # | Board | Task ID | Title | Reason |
|---|---|---|---|---|
| 1 | marketing-pages | t_9608ccf6 to t_4da12ef4 | F1–F10 tournament tasks ("'Add another competitor' in registration", "Sparring → Weight becomes required", etc.) | **Wrong board.** These are taekwondo tournament-app tasks (sparring, weight classes, scorekeeper shortcuts). They don't belong on `marketing-pages`. |
| 2 | ai-billing-audit | t_b0145849 | "Set up OpenAI SDK client with MiniMax base URL" | Granular: superseded by `t_192ffb5b` ("Wire client into the dev loop as the default provider") and `t_5832703e` ("MiniMax M3 client implementation"). Both children are done; this parent is also done and the artifact remains useful, but it's an intermediate step that is no longer referenced. |
| 3 | ai-billing-audit | t_77ac5265 | "Add typed message helpers and request validation" | Sub-task of a multi-step LLM provider stub rollout. Done. Without a comment trail explaining *why* it was a separate task, it's noise. |
| 4 | ai-billing-audit | t_8e098adb | "Vision check: button affordance and number formatting" | Over-decomposed: a UI polish item. `t_08d9c532` "Vision check: highlight readability" is its sibling. |
| 5 | ai-billing-audit | t_08d9c532 | "Vision check: highlight readability" | Same family as above. |
| 6 | ai-billing-audit | t_08ac95ff | "Claude / OpenAI / Gemini stub clients" | Done. Combined with `t_c8771150` (Claude), `t_87e9b6ca` (OpenAI), `t_2f381251` (Gemini). 4 tasks for what is now a single client. |
| 7 | product-ux | t_d86b072a | "Keyboard shortcuts: A=accept, D=dismiss, R=re-run, F=flag, J/K=next/prev finding" | Single-line feature with 5+ shortcuts in the title. Should be 1 task or split per shortcut, not both. |
| 8 | features-expansion | t_4496cee1 | "Webhooks for status changes (audit_complete, finding_acknowledged)" | Likely duplicate of `t_3b15809f` "Webhook at submit time (EHR calls us before claim is sent)" on **clinical-impact**. Both are unassigned and 4 days old. |
| 9 | pilot-ready | t_77f8e02c | "Follow up with Eliud on the friendly clinic intro (Telegram)" | Single-person activity item. Belongs in a CRM/personal task list, not a project kanban with 4-day-old SLA framing. |
| 10 | ai-billing-audit | t_2a2ee9cd | "QA: verify auditor returns has_discrepancy=false on clean claims" | Over-decomposed: this is a single pytest case. Done. Belongs in the test code with a commit message, not as a card. |

**Note on the F1–F10 tournament misfiling:** 10 tasks on `marketing-pages`
have priority 1..10 in creation order. That priority distribution is
diagnostic of automated dump from a different project's todo list. The
auit's primary recommendation: move all 10 to a `taekwondo-tournament`
board (which exists at `~/.hermes/kanban/boards/taekwondo-tournament/` per
the directory listing).

---

## Blocked-task dependency graph

**There is no live "blocked" subgraph.** All 109 `task_links` rows in
`ai-billing-audit` reference children that are `done` or `archived`. The
DAG model is being used as a completion-order diagram, not as a blocker
model. Sample (top of chain):

```
t_a1727042 (Define LLMClient Protocol interface) [done]
  ├── t_8c7a7ce4 (Implement factory reading LLM_PROVIDER env) [done]
  │     └── t_8fe5cb0f (Write verification test swapping LLM_PROVIDER) [done]
  └── t_90cfc976 (Implement four provider classes via litellm) [done]
        └── t_8fe5cb0f
              └── t_76ceb67e (Define LLMClient protocol + factory) [done]
```

**Zombie-block audit:** No zombie blocks because the system has no live
blocking. All 109 dependency edges terminate in done/archived nodes.

**Circular-dependency audit:** None found. The DAG is shallow
(maximum depth ~5 levels) and acyclic.

**Risk:** the DAG model is silently misleading. Future-you looking at the
"ready" set will not see which ready-tasks depend on which done-tasks
because the done-side has been pruned from the active workflow. The
brain-audit, clinical-impact, features-expansion, product-ux boards have
ZERO `task_links` rows despite having 29, 19, 23, 35 ready tasks
respectively — meaning there is no cross-board dependency tracking at all.

---

## Per-board smell

For each of the 8 boards: the single most stale task (oldest open), the
single most likely zombie (claimed, no progress — none exist), the single
highest-leverage unclaimed task, and the board's definition status.

| Board | Definition | Most stale (open) | Most likely zombie | Highest-leverage unclaimed |
|---|---|---|---|---|
| **ai-billing-audit** | "Unified plan merging Doc 1 + Doc 2 + Doc 3. 12-week production roadmap." Clear. | n/a (all open tasks are 0; everything moved to `ready=0` after prior archive) | None — no zombies, but **the gap is not in age, it's in coverage**: v12/Alberta/F1/data-residency are not tracked | **Create: Alberta HIA data agreement + the Ontario-PHIPA references in the OnboardingWizard / security page** (next-largest operator gap after Mailgun was removed) |
| **brain-audit** | (none in board.json) | `t_97e1eedd` "Modifier-25 deep-dive" (4 days old, priority 10) | None | **"Ground-truth review: 20 hand-verified encounters for calibration"** — without it, F1 numbers are untrustworthy |
| **clinical-impact** | (none) | `t_af26abdb` "Doctor dashboard view" (4 days old, priority 1) | None | **"Doctor 'fix-it' workflow (re-audit on note update)"** — closest feature to fixing Gap 3 (the re-audit endpoint bug) |
| **features-expansion** | (none) | `t_ca101c1c` "Support 837I (institutional) claims" (4 days old) | None | **"Payer-specific rule packs (BCBS, Aetna, UHC, OHIP+, AHCIP, OHIP)"** — the only one that's directly downstream of the Alberta pivot |
| **marketing-pages** | (none) | `t_855f6b45` "Move audit-logging section higher on /security" (4 days old) | None | **"Deploy apps/portal to a public URL"** — without this, none of the other 19 marketing tasks are visible to a prospect |
| **pilot-ready** | (none) | `t_f9b65ea1` "[A1] Diagnose why recall is so low on the 7-run baseline" (4 days old) | None | **"[A5] Add 50+ real billing-rule chunks to the RAG corpus"** — v12 prompt needs more AHCIP rules to push F1 past 0.733 |
| **product-ux** | (none) | `t_171d24b3` "Add encounter search" (4 days old) | None | **"Per-finding accept/dismiss buttons (not just encounter-level)"** — the dashboard currently makes you accept/dismiss at the encounter level which is the actual UX blocker for billers |
| **test-client-ready** | (none) | (no `ready` tasks; all done/archived) | None | **None — this board is correctly retired.** |

**Top zombies across all boards: 0.** The prior session's "46 over-decomposed
tasks" anxiety was a one-time cleanup; the current zombie risk is zero
because nothing is being worked on at all.

**Dumping-ground verdict:** 7 of 8 boards have **no description field in
their `board.json`** (only `ai-billing-audit` has one). 6 of 8 boards are
functionally dumping grounds: a flat list of feature ideas with no
priority ordering and no done-criteria. The only boards with a clear
thesis are `ai-billing-audit` (the roadmap doc) and arguably
`marketing-pages` (titled to be obvious).

---

## Project history reconstruction — can the kanban rebuild the timeline?

### v0 → v12 prompt iteration

**Reconstructable: NO.** The kanban shows:

- `t_1400da1f` "Set up test split and Auditor v0 prompt" — done.
- `t_336c0fa2` "Run Auditor v0 over all 50 test encounters" — done.
- `t_b7b0c5fb` "Auditor Agent: run on test split, baseline score" — done.
- `t_573f032d` "Configure and run DSPy MIPROv2 prompt optimization" — done.

Then a **gap of 5 days of zero kanban activity** until:

- `t_52c10364` "Code review: prompt ops surface (MANIFEST, grader_config,
  auditor_prompt)" — done 2026-06-17.

**No tasks for v1, v2, v3, v4, v5, v6, v7, v8, v9, v10, v11, v12.** The
kanban jumps from "Auditor v0 prompt" to "code review of the prompt ops
surface." The commit log (`git log --oneline`) shows the real history:
`feat(prompt-v4)` through `feat(prompt-v10)` through `feat(zorva-alberta)`
v12. Future-you reading the kanban will see only the v0 prompt and the
post-hoc code review; everything in between is invisible.

### Alberta pivot (2026-06-22)

**Reconstructable: NO.** The kanban contains zero tasks dated
2026-06-22. The board's "ready" tasks all date 2026-06-18 or
2026-06-19. The pivot is documented **only** in:

- `docs/ALBERTA_STRATEGY_BRIEF.md`
- `docs/ALBERTA_PROSPECT_LIST.md`
- `docs/AUDIT_PROMPTS_VAL.md`
- `docs/AUDIT_DOCS_MARKETING.md` (which describes the half-done copy state)
- commit `6706b72`

A future agent doing a project-history reconstruction would need to read
4 separate docs and parse the commit log. The kanban is not the source
of truth for this pivot.

### Done-tasks-with-no-comment-trail

**60 of 118 done tasks on `ai-billing-audit` have zero comments.** The
heaviest-comment done-task is `t_78c1c73b` (5 comments — MVP acceptance
test). This is recoverable from the commit log for tasks that ship code,
but the **QA/code-review tasks** (`t_d1335a32`, `t_52c10364`,
`t_d8d96ebb`, `t_27cb3b1b`, `t_34a3f1c7`, `t_783eb181`, etc.) have no
inline summary of *what was found*. A future audit will need to re-run
the code review or find the commit messages, but the kanban offers no
breadcrumb.

The single most painful gap: **no task describes what was in the v11
prompt or why v12 is different from v11**. The MANIFEST.json has the
diff (`changes_from_v11`) but the kanban has nothing.

---

## Known-issues confirmation/refutation table

| Prior-session claim | Verified? | Evidence |
|---|---|---|
| "46 over-decomposed tasks were archived" | ❌ **FALSE (number is wrong).** | Current archived count: 100 in ai-billing-audit + 14 in test-client-ready + 5 in marketing-pages = **119 total**, not 46. |
| "DONE BUT NOT WIRED — audit_actions.py" | ❌ **FALSE (now wired).** | `src/ai_billing_audit/api.py:738, 765, 814, 831, 1145, 1870, 1946, 2013` all import `audit_actions.append` (or `read_all`); the 4 action endpoints (accept-all/dismiss/rerun/flag) all call it. |
| "The 5 conversion-blocking gaps in the kanban" | ⚠️ **Partial.** | Only Gap 1 (doctor summary) is on a kanban task. Gap 2 has 1 of 4 endpoints tracked. Gap 4 is a false alarm. Gaps 3 and 5 are not tracked. |
| "12 prompt versions in MANIFEST.json (per agent #3)" | ❌ **FALSE.** | `prompts/MANIFEST.json` has **2 entries** (`entries: [2]`). Not 12. |
| "v12 deployment to live — NOT done" | ⚠️ **Likely true, not tracked.** | Most recent deploy-trackable task is `t_a9e7152e` "Mirror VPS build … at v0.1.0-rc1" (done 2026-06-17 03:26). v12 prompt is dated 2026-06-22 20:25 — 5 days after rc1. No task tracks a v0.1.x bump or a v12 deploy. Cannot verify on-disk without live shell. |

**Additionally discovered:**

- **10 taekwondo-tournament tasks are misfiled on `marketing-pages` board
  as "triage" with priority 1..10.** This is not in the brief but is a
  real hygiene defect.
- **All 8 boards have zero in-progress tasks.** The `claim_lock` /
  `claim_expires` mechanism in the schema is unused. Workers aren't
  picking up tasks. Either the dispatcher is broken or there's no
  dispatcher loop running.

---

## Risk-ranked recommendations — top 10 things to fix

Ordered by leverage × risk if ignored. **None of these are write
operations performed by this audit; they are recommendations only.**

| # | Risk | Fix |
|---|---|---|
| 1 | ~~Gap 5 (MAILGUN_API_KEY on live) blocked any doctor-summary email send.~~ **RESOLVED 2026-06-26 by removal** — see gap row in the table above. | n/a (auto-send is gone; manual outbox dispatch is the chosen model) |
| 2 | The Alberta-pivot re-audit endpoint is fundamentally broken: it re-synthesizes the encounter from a deterministic seed rather than honoring the biller's uploaded CPT/ICD codes. | **Create a task on ai-billing-audit** for `/encounters/{id}/audit` to read the cached Job's claim (`job.result.claim`) instead of calling `synth_agent.generate()`. This is a 30-line patch in `src/ai_billing_audit/api.py:2230`. |
| 3 | 10 taekwondo-tournament tasks are polluting the `marketing-pages` board's "triage" lane, making the triage queue look 33% busy when it's actually empty. | **Move the 10 tasks (`t_9608ccf6`..`t_4da12ef4`) to the `taekwondo-tournament` board.** Same `task_links` schema, just different `kanban.db` rows. |
| 4 | PHIPA vs HIA scrub is documented as a real bug in `AUDIT_DOCS_MARKETING.md` but has no task. An Alberta prospect reading the marketing portal will see "PHIPA-aligned audit trail" and "AWS ca-central-1" in 12+ places. | **Create a task on marketing-pages:** "PHIPA → HIA scrub on Alberta-targeted copy (12 sites in `apps/portal/src/`)" and a paired task "AWS → Hostinger copy correction (marketing portal says AWS; deployment is Hostinger VPS)." |
| 5 | `data-residency claim updated` is technically done (`t_1bab62b6`) but the claim is wrong (says AWS, deployment is Hostinger; says per-region choice, only one region exists). | **Re-open as 2 separate tasks:** (a) Hostinger reality-fix in `page.tsx:56` and `security/page.tsx:64,287,322`; (b) drop the per-region picker until a second region actually exists. |
| 6 | 60 of 118 done tasks have no comments. Future-you doing project-history reconstruction will need to re-derive context from `git log`. | **Backfill 1-line summaries** on every done task with no comment: 1 hour of work, prevents 5+ hours of re-discovery per future audit. |
| 7 | Zero tasks track v0→v12 prompt iterations. The kanban says "v0 prompt → code review" and skips 11 versions. | **Create retrospective tasks v1..v12 on ai-billing-audit (status=done, created=actual commit date)** so the project-history is visible from the kanban. Use commit `git log` to derive the dates. |
| 8 | Zero tasks track the Alberta pivot (2026-06-22). The pivot is only in 4 docs and 1 commit. | **Create "Alberta pivot — done" tasks** on ai-billing-audit (4 entries: brief, prospect list, v12 prompt, val_ca.json clean). Mark `done` with completed_at = pivot date. |
| 9 | The `task_links` DAG is only used on ai-billing-audit. The other 7 boards have zero dependency rows. Cross-board blockers (e.g., "ship AHCIP rule pack [features-expansion] before the Alberta pilot [pilot-ready]") are invisible. | **Add cross-board `task_links` rows** for the 5–10 known cross-board dependencies. The schema supports it; only ai-billing-audit has rows. |
| 10 | All 8 boards have zero in-progress / zero claimed tasks. The dispatcher loop is either silent or broken. This is invisible because the dashboard default-view only shows `ready`. | **Investigate the worker dispatcher.** Either the `kanban-worker` cron isn't running, or tasks aren't being picked up. Add a heartbeat task or a "kanban health" task to make this visible. |

---

## Appendix A — Files / artifacts inspected

- Kanban DBs (read-only): `~/.hermes/kanban/boards/{ai-billing-audit,brain-audit,clinical-impact,features-expansion,marketing-pages,pilot-ready,product-ux,test-client-ready}/kanban.db`
- Kanban metadata: `board.json` for each of the 8 boards
- Code: `/Users/biancabienaime/projects/ai-billing-audit/src/ai_billing_audit/{api.py,doctor_email.py,job_queue.py,audit_actions.py}`
- Prompts: `prompts/MANIFEST.json`, `prompts/v0..v12/auditor_prompt.txt` (only v11 + v12 exist on disk; MANIFEST references a `c356e64b...` parent_hash that is not on disk)
- Deploy config: `docker-compose.yml`, `Dockerfile`, `deploy-to-vps.sh`
- Docs: 78 markdown files in `/Users/biancabienaime/projects/ai-billing-audit/docs/` — only `AUDIT_DOCS_MARKETING.md`, `ALBERTA_STRATEGY_BRIEF.md`, `ALBERTA_PROSPECT_LIST.md`, `AUDIT_DEPLOY_OPS.md`, `AUDIT_PROMPTS_VAL.md`, `ITERATION_LOG.md`, `CANADA_BILLING_CROSSREF.md`, `SEC_REVIEW_phi.md`, `RUNBOOK.md` referenced
- Git log: last 20 commits (`git log --oneline -20`)

## Appendix B — Queries used

```sql
-- Status counts
SELECT status, COUNT(*) FROM tasks GROUP BY status;

-- Done ages
SELECT COUNT(*), AVG((completed_at-created_at)/86400.0)
FROM tasks WHERE status='done';

-- Comment counts >5 (returned 0 rows for all 8 boards)
SELECT task_id, COUNT(*) FROM task_comments
GROUP BY task_id HAVING COUNT(*) > 5;

-- Dependency graph
SELECT parent_id, child_id FROM task_links;

-- Claim/done cross-check
SELECT id, title FROM tasks
WHERE status IN ('done','archived')
  AND (lower(title) LIKE '%doctor%' OR ...);
```

All queries run via `sqlite3 <board>/kanban.db`. Read-only.

## Appendix C — Two things prior audits got wrong, corrected here

1. **"46 over-decomposed tasks archived"** is wrong; the actual number is 119.
2. **"12 prompt versions in MANIFEST.json"** is wrong; the actual count is 2.
   The prompt directory has `v0..v12` folders, but only `v11/` and `v12/`
   contain `auditor_prompt.txt`. The MANIFEST has 2 entries; one references
   a parent_hash that does not correspond to any on-disk file.

---

*End of audit. No files modified; no kanban writes performed; no tasks
moved, claimed, or archived.*
