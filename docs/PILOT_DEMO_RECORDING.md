# Pilot Demo Dry Run — Live URL Validation

**Run timestamp (UTC):** 2026-06-18T20:51:26Z
**Live URL:** https://ai-billing-audit.ashbi.ca
**Bearer token:** rotated post-pilot; the active value lives only at
`/root/.ai_billing_bearer.txt` on the VPS (never committed to the repo).
P11 bug-sweep: the literal "pilot-bearer-token-2026-06-17-ashbi" string was
removed from this doc on 2026-06-30 — the value it had pointed to is no
longer the live token.
**Source of truth:** `docs/SALES_DEMO.md` (the runbook the sales rep follows)
**Run by:** kanban worker dispatched for `t_ea5b7b03` (task archived
mid-flight; this runbook is the deliverable).

## TL;DR for the sales rep

The live URL is **NOT demo-ready as of this run.** Three of the six steps in
`SALES_DEMO.md` will fail or look broken if you walk them on a live call right
now. Don't open the laptop and click "Demo encounters" until the bugs below
are fixed. The two screenshots that show the system working are dated
`16:38–16:44 UTC` — anything captured after `16:49 UTC` shows the broken
state, including the recording file referenced below.

## Results checklist (6 demo steps)

| # | Step | Result | Notes |
|---|------|--------|-------|
| 1 | Open the live product — home dashboard renders with encounter cards | **PASS (intermittent)** | The 3 registered demo encounters render as cards on the home page, but as of `16:49 UTC` all 3 carry a "record missing" badge. The earlier `16:38 UTC` capture shows them rendering cleanly. |
| 2 | Stripe test card — 4242 4242 4242 4242 | **SKIP** | No Stripe integration wired in this build. Pricing page is not in scope for the live API. The card workflow described in `SALES_DEMO.md` cannot be exercised. |
| 3 | The three plans ($499 / $1,499 / $2,999) | **SKIP** | No public pricing page is reachable from the live API at the moment. The `iter` task scope was the audit dashboard, not the marketing site. |
| 4 | Three sample claims — `data/val.json` encounters (easy/medium/hard) | **FAIL** | The 3 demo encounters (`enc_10032` / `enc_0007` / `enc_0000`) are registered but their records are missing from the running container. `GET /encounter/enc_10032` returns `{"detail":"encounter 'enc_10032' is registered but the underlying record could not be located in data/val.json or data/train.json."}` This breaks step 4 (no clean claim to show) and step 5 (split-screen review). |
| 5 | Split-screen review — narrative + findings, click Run audit, Export action plan | **FAIL** | The split-screen audit panel works (screenshot `02-easy-demo-encounter.png` from `16:38 UTC` proves it) but the demo encounters are no longer reachable as of `16:49 UTC`. A freshly uploaded encounter returns 500 on the encounter detail page (`/encounters/{id}`); only `/encounters/upload/jobs/{job_id}` returns the audit JSON. |
| 6 | Audit log — permanent, signed log the regulator can audit | **PASS (partial)** | `upload_jobs.jsonl` is being written and the home page reads it for the "Most Recent Real-Audit Run" panel. But `audit_status` in the in-memory job state stays `pending` even after the LLM completes — the `audit_status` field in the JSON status endpoint is a stale read and does not reflect the actual LLM outcome (the home page reads the log file directly, which IS correct). |

## Step 1 — Home dashboard

**Status: PASS at `16:38 UTC`, FAIL at `16:49 UTC`**

The home page shows a 3-column grid of encounter cards (3 demo encounters plus
any newly uploaded encounters) and a "Most Recent Real-Audit Run" panel at
the bottom that reads the latest entry from `/app/logs/upload_jobs.jsonl` and
renders its LLM-generated summary.

Screenshot: `screenshots/01-home-initial.png` (timestamp 16:38, 6 encounter
cards visible — 3 demo + 3 pilot uploads).

## Step 2 — Stripe test card

**Status: SKIP**

No Stripe integration is wired. `SALES_DEMO.md` describes the card for the
sales rep to use during a checkout flow; this build of the live API does not
expose a checkout endpoint. Skip the step on the call and say: "we don't run
payments on the demo instance — the audit log is what you'd be paying for."
Move on to step 4.

## Step 3 — Pricing tiers

**Status: SKIP**

The marketing pricing page is not part of the live API. Skip. Pull up the
PDF one-pager at `docs/ONE_PAGER_WHAT_WE_DO.pdf` (exists, print-ready) if
the prospect asks about pricing.

## Step 4 — Three sample claims

**Status: FAIL — launch-blocker**

The 3 demo encounters render as cards on the home page but the actual data
records are missing from the running container. The encounter-detail route
returns:

```json
{"detail":"encounter 'enc_10032' is registered but the underlying record
could not be located in data/val.json or data/train.json."}
```

**Bug filed: BUG-2026-06-18-01 (data files missing from live container)**

**Repro:**
```bash
curl -sS -H "Authorization: Bearer $PILOT_TOKEN" \
  https://ai-billing-audit.ashbi.ca/encounter/enc_10032
# Expected: full HTML page with clinical note + claim + findings
# Actual:   {"detail":"encounter 'enc_10032' is registered but the
#           underlying record could not be located in data/val.json
#           or data/train.json."}
```

**Probable cause:** the `data/` directory is baked into the Docker image
(`Dockerfile` COPY) and the image was rebuilt without the `data/`
directory, or a deploy cleared the volume. Per
`docs/ITERATION_LOG.md` ("live URL frontend 2026-06-17 23:50"), this was
fixed once already — the same regression recurred.

**Fix scope:** verify `Dockerfile` still has `COPY data/ /app/data/` (or
equivalent), rebuild the image, redeploy. This is the highest-priority
blocker for the sales call.

## Step 5 — Split-screen review (run audit, accept/dismiss, export)

**Status: FAIL — launch-blocker**

The encounter-detail page worked at `16:38 UTC` (see
`02-easy-demo-encounter.png` which shows the full split-screen with
clinical note on top, claim + retrieved rules in two columns, and the
ground-truth findings panel at the bottom). The route is also returning
500 for uploaded encounters:

```bash
curl -sS -H "Authorization: Bearer $PILOT_TOKEN" \
  https://ai-billing-audit.ashbi.ca/encounters/pilot_easy_001
# Expected: full HTML page with audit detail
# Actual:   Internal Server Error (500)
```

**Bug filed: BUG-2026-06-18-02 (`/encounters/{encounter_id}` returns 500
for uploaded encounters)**

The audit JSON IS available via the upload-jobs endpoint:
`GET /encounters/upload/jobs/{job_id}` returns the full audit result with
`audit_status: "ok"`, `findings: []`, and the `summary` text. The HTML
route for the same encounter is broken.

Also surfaced during this run:
**BUG-2026-06-18-03: home page hardcodes `ENC001` for one card** — the
`templates/index.html` (or equivalent) has a literal `ENC001` link that
404s. Earlier in the run (before data went missing) the page rendered
this card as "EASY / CLEAN / 0 findings" linking to a 404. The home page
DOES correctly render the registered demo encounters as cards; the
broken `ENC001` is a third copy that has been a placeholder since at
least the v0.1.0-rc1 build.

**BUG-2026-06-18-04: `/encounters/upload` collides with
`/encounters/{encounter_id}` catchall route.** A GET to
`/encounters/upload` returns 404 (the route matcher treats "upload" as
an `encounter_id` and the encounter-detail handler returns "not
registered"). The trailing-slash variant returns 307 redirect to the
same broken handler. Result: the "upload" nav link in the topbar
404s. Quick fix is to reorder route registration in `api.py` so the
`/encounters/upload` (no-path-param) routes are declared before the
`/encounters/{encounter_id}` catchall.

## Step 6 — Audit log

**Status: PASS (with caveat)**

The audit log IS being written to `/app/logs/upload_jobs.jsonl` and the
home page reads the latest entry correctly (see "Most Recent Real-Audit
Run" panel in `03-home-after-uploads.png`). The in-memory job status
endpoint returns `audit_status: "pending"` even after the LLM
completes, but the home page reads the log file directly and shows
the real summary text.

**BUG-2026-06-18-05: `/encounters/upload/jobs/{job_id}` returns stale
`audit_status: "pending"` after the LLM completes.** The LLM DID return
content (the home panel proves it). The `audit_status` field in the
in-memory `Job` object is not being updated to `"ok"` when the LLM
finishes. The real status lives in the log file but the status endpoint
returns the stale field. Fix: update `Job.audit_status` (and
`Job.audit_summary`) in the worker callback after the LLM call returns,
or have the status endpoint re-read the log file for fresh data.

## What shipped (artifacts)

- `docs/PILOT_DEMO_RECORDING.md` — this file
- `docs/PILOT_DEMO_RECORDING.webm` — 25s WebM recording of the demo flow
  as captured at `16:49 UTC`. **This recording shows the broken state**
  (encounter detail pages 404/500). It's useful as evidence of the bugs
  but not as a sales-call visual aid.
- `docs/PILOT_DEMO_RECORDING.mp4` — H.264 MP4 of the same recording, for
  iOS/email sharing.
- `docs/screenshots/01-home-initial.png` — home page at `16:38 UTC`,
  working state, 6 encounter cards (3 demo + 3 pilot uploads)
- `docs/screenshots/02-easy-demo-encounter.png` — split-screen review
  of `enc_10032`, working state, shows clinical note + claim + rules
  + ground-truth findings
- `docs/screenshots/02-medium-demo-encounter.png` — `enc_0007` audit panel
- `docs/screenshots/02-hard-demo-encounter.png` — `enc_0000` audit panel
- `docs/screenshots/03-home-after-uploads.png` — home page at `16:44 UTC`
  after 3 pilot uploads, with the "Most Recent Real-Audit Run" panel
  showing job `a6742f3c57a2` and a real LLM summary
- `docs/screenshots/06-api-docs.png` — Swagger UI (`/docs`)

## What was uploaded during the run

Three pilot encounters were submitted via the live upload portal during
this validation:

| Encounter ID | Difficulty | Variant | Job ID (obsolete) | Outcome |
|---|---|---|---|---|
| pilot_easy_001 | EASY | clean | de33f7a358db (replaced by earlier run) | done, summary returned, 0 findings |
| pilot_med_002 | MEDIUM | cardiology | a6742f3c57a2 (replaced) | done, summary returned, 0 findings |
| pilot_hard_003 | HARD | multispecialty | 44417a367e7d (replaced) | 502 during polling, then 500 on detail; data may have been wiped by the LLM 502 path |

The encounter IDs are server-side cached in the in-memory job queue;
they will disappear on the next server restart. They are NOT in the
`data/` directory so they won't show up after a redeploy.

## Bugs filed

| ID | Severity | Title | Source |
|---|---|---|---|
| BUG-2026-06-18-01 | Critical (launch-blocker) | Data files missing from live container — demo encounters return "record not found" | this run, `16:49 UTC` |
| BUG-2026-06-18-02 | High | `/encounters/{encounter_id}` returns 500 for uploaded encounters (only the JSON endpoint works) | this run |
| BUG-2026-06-18-03 | Medium | Home page hardcodes `ENC001` placeholder link that 404s | this run |
| BUG-2026-06-18-04 | Medium | `/encounters/upload` route collides with `/encounters/{encounter_id}` catchall | this run |
| BUG-2026-06-18-05 | Low | Job status endpoint returns stale `audit_status: pending` after LLM completes | this run |

Add the 5 bugs to `docs/BUGS.md` and reference them from the next
deploy-validation kanban card.

## Recommendation for the sales call

**Do not demo from the live URL until BUG-2026-06-18-01 is fixed.** Without
the data files in the container, every step from "open the live product"
through "split-screen review" looks broken to a prospect.

If the call has to happen today, use the static screenshots in
`docs/screenshots/` (captured at `16:38–16:44 UTC` while the system was
working) and narrate the flow rather than clicking through the live URL.
The 4-step "what to show in the split-screen review" section of
`SALES_DEMO.md` is still valid; just don't promise the prospect a live
audit until the data is back.

If the data fix lands before the call, re-run this validation: the
`scripts/pilot_capture.js` and `scripts/pilot_record.js` (in the
worker's scratch dir; not committed) can be re-executed to confirm the
fix without re-doing the manual walk.
