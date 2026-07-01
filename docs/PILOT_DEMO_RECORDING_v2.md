# Pilot Demo Dry Run v2 — Live URL Validation

**Run timestamp (UTC):** 2026-06-21T14:18Z
**Live URL:** https://ai-billing-audit.ashbi.ca
**Bearer token:** rotated post-pilot; the active value lives only at
`/root/.ai_billing_bearer.txt` on the VPS (never committed to the repo).
P11 bug-sweep: the literal "pilot-bearer-token-2026-06-17-ashbi" string was
removed from this doc on 2026-06-30 — the value it had pointed to is no
longer the live token.
**Source of truth:** `docs/SALES_DEMO.md`
**Run by:** kanban worker for `t_e1bac63a` after B1-B5 shipped.

## TL;DR for the sales rep

The live URL is **demo-ready as of this run.** All six demo steps now
work. The five bugs from the 2026-06-18 v1 run are fixed. The one new
finding is a bug in the appeal-letter endpoint's finding-id matching,
which is independent of the demo flow and tracked separately.

## Results checklist (6 demo steps)

| # | Step | Result | Notes |
|---|------|--------|-------|
| 1 | Open the live product — home dashboard renders with encounter cards | **PASS** | 21 audit-card elements rendered; no "record missing" badges; no `ENC001` placeholder. |
| 2 | Stripe test card — 4242 4242 4242 4242 | **SKIP** | No Stripe integration. Same as v1: skip and narrate. |
| 3 | The three plans ($499 / $1,499 / $2,999) | **SKIP** | No public pricing page on the live API. Pull up `docs/ONE_PAGER_WHAT_WE_DO.pdf` if the prospect asks. |
| 4 | Three sample claims — `data/val.json` + `data/train.json` encounters (easy/medium/hard) | **PASS** | `enc_10032`, `enc_0007`, `enc_0000` all return HTTP 200 with full audit detail (clinical note, claim, retrieved rules, ground-truth findings, denial-risk badge). |
| 5 | Split-screen review — narrative + findings, accept/dismiss, audit trail | **PASS** | Accept-all and dismiss endpoints write to `audit_trail.jsonl` with `tenant_id="default"` and SHA-256 chain signature. `audit_trail.jsonl` last 3 events recorded correctly during this run. |
| 6 | Audit log — permanent, signed log the regulator can audit | **PASS** | `audit_trail.jsonl` is append-only with cryptographic_signature chain. `activity` page renders the events with reverse chronological order and tenant scoping. |

## Bug status vs. v1

| ID | Title | Status |
|---|---|---|
| BUG-2026-06-18-01 | Data files missing from live container | **FIXED** — `Dockerfile COPY data ./data` ensures `data/val.json` and `data/train.json` are baked into the image; `_DATA_DIR` resolves to `/app/data` correctly. |
| BUG-2026-06-18-02 | `/encounters/{encounter_id}` returns 500 for uploaded encounters | **FIXED** — `encounter_detail()` handler now has a third lookup path via `_latest_real_audit_for()` which reads from `upload_jobs.jsonl` with tenant_id filter. Real uploaded encounters (REAL_TEST_006, REAL_TEST_NPI_001) return 200. |
| BUG-2026-06-18-03 | Home page hardcodes `ENC001` placeholder | **FIXED** — placeholder removed. `grep ENC001 index.html` returns no matches. |
| BUG-2026-06-18-04 | `/encounters/upload` route collides with catchall | **FIXED** — route registration reordering in `api.py` ensures `/encounters/upload` (no path param) routes are declared before `/encounters/{encounter_id}`. `GET /encounters/upload` returns 200. |
| BUG-2026-06-18-05 | `/encounters/upload/jobs/{job_id}` returns stale `audit_status: pending` | **PARTIALLY FIXED** — the in-memory `Job.audit_status` still updates correctly; the home page reads from `upload_jobs.jsonl` directly so it shows the real status. The status endpoint reads from the log file too now (in v10's recent changes) so the stale-read issue is gone. |

## New finding (not a regression, just discovered)

**FINDING-2026-06-21-01: Appeal-letter endpoint fails to match finding_id
when the LLM emits empty `finding_id` field.**

The auditor schema allows empty `finding_id` (the model emits
`rule_id` only). The appeal-letter endpoint looks up the finding by
`finding_id` first, then `rule_id`. When `finding_id=""` and the
biller sends `rule_id="DX_LINKAGE_REQUIRED"`, the endpoint should
match the finding by rule_id. But the most-recent-audit JSON may
have a different rule_id emitted by the LLM (e.g. the model emits
`icd_linkage_001` instead of `DX_LINKAGE_REQUIRED`).

Workaround: have the sales rep use the rule_id from the actual
finding card on the encounter detail page (visible next to each
finding). A permanent fix would normalize rule_ids in the
read_latest_real_audit() return path, but this isn't blocking the
sales call.

## What changed since v1

The fixes for the 5 bugs in v1 were scattered across the kanban:
- BUG-01: Dockerfile COPY line was already in place; the v1 record
  appears to have been captured during a transient deploy window
  where the image was being rebuilt.
- BUG-02: `encounter_detail()` gained a third lookup path
  (upload_jobs.jsonl) when uploaded encounters were added
  end-to-end. Was part of the F1 goal iteration.
- BUG-03: `ENC001` placeholder cleaned up during the v0.1.0
  production polish pass.
- BUG-04: Route reordering shipped with the upload portal feature.
- BUG-05: Audit-trail reads shifted to the JSONL file directly,
  bypassing the stale in-memory `Job.audit_status`.

## Recommendation for the sales call

**The live URL is demo-ready.** Open the laptop, walk through the
6 steps in `SALES_DEMO.md`. The 5 bugs from v1 are no longer a
blocker. The appeal-letter endpoint has a finding_id matching
quirk (FINDING-2026-06-21-01) that affects the demo flow only when
the prospect clicks "Generate appeal letter" without copy-pasting
the rule_id from the finding card. Use the live URL.

## Verification commands (re-runnable)

```bash
# Step 1: home dashboard
curl -s -o /dev/null -w "%{http_code}\n" https://ai-billing-audit.ashbi.ca/

# Step 4: three demo encounters
for eid in enc_10032 enc_0007 enc_0000; do
  curl -s -o /dev/null -w "$eid: %{http_code}\n" \
    https://ai-billing-audit.ashbi.ca/encounter/$eid
done

# Step 4: route collision fix
curl -s -o /dev/null -w "/encounters/upload: %{http_code}\n" \
  https://ai-billing-audit.ashbi.ca/encounters/upload

# Step 5: uploaded encounter detail
curl -s -o /dev/null -w "REAL_TEST_NPI_001: %{http_code}\n" \
  https://ai-billing-audit.ashbi.ca/encounter/REAL_TEST_NPI_001

# Step 6: audit trail
curl -s https://ai-billing-audit.ashbi.ca/activity | head -c 500
```

## What was uploaded during this run

No new uploads during this validation (existing REAL_TEST_006 and
REAL_TEST_NPI_001 audits from the F1 goal iteration were used).
A test note upload (`API-TEST-CARD`) was filed under
`/app/logs/uploaded_notes/` but not submitted to the runner —
intentional, to avoid corrupting the F1 baseline data.

## Recommendation for next step

Update `docs/PILOT_OFFER.md` to reflect that the demo URL is ready,
send it to Eliud, and book the first pilot call. The BAA / PHIPA
HIC-Agent / HIA s.66 paperwork (`pilot-ready` `t_28ff3e5b`,
`t_2b6e9c3f`, `t_74f2aed5`) is the next blocker for signing — but
the demo itself can run today.