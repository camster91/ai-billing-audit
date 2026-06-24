# Documentation Review — README, RUNBOOK, security page, inline docstrings

**Date:** 2026-06-17
**Scope (per task body, nothing invented):**

1. `README.md` — quickstart / install / run / deploy presence, 5-minute readability
2. `docs/RUNBOOK.md` — coverage of four named on-call scenarios (audit_trail chain break, F1 drop, LLM outage, billing dispute) with runnable steps
3. `apps/portal/src/app/security/page.tsx` — cross-reference each marketing claim against code/configs
4. Inline docstrings — sample Python and TypeScript modules/classes/functions for missing, inaccurate, or boilerplate docstrings

This document is a review and a fix-list. It does not rewrite any source artifact and does not add features or scenarios beyond the four named.

---

## 1. README

**Artifact:** `README.md` (722 lines, 34040 bytes).

### 1.1 Checklist

| Item | Present? | Notes |
|---|---|---|
| Quickstart | **Yes** | `## Quickstart: run the dev loop on MiniMax (default)` at line 71. 27 lines. |
| Install | **Yes** | `### Install` at line 112, inside `## How to run it`. `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`. |
| Run | **Yes** | `### Run commands` at line 168. Lists `pytest`, `verify_grader_reproducibility.py`, `optimize.py`, and two supporting scripts. |
| Deploy | **Partial** | No `## Deploy` or `### Deploy` section header. The deploy recipe is embedded as **step 5** of the `## Reproducing results` block (lines 588–708) which is the only place a `python run.py` invocation appears, and it is correctly named. A reader scanning the top-level sections will not see a "Deploy" section. |
| 5-minute readability | **No** | The full recipe (lines 588–708) is ~120 lines. Required manual steps beyond the venv/install: pin verification, Python interpreter selection, picking one of five provider env-var sets, optional `.env` write, and reading "What to do if step 5 reproduces a different val F1 than the table" to know how to interpret drift. Realistic operator time: 10–20 min, not 5. |

### 1.2 Concrete deficiencies (with file:line)

| # | File:line | Problem | Suggested change |
|---|---|---|---|
| 1.1 | `README.md:172` | Test count "204/204 pass" | Stale — replaced by the value on line 583 and 654 ("388 tests as of 2026-06-16"). Pick one canonical number, update everywhere. |
| 1.2 | `README.md:316` | "The 75 tests pass locally" | Stale — same issue, different number, same week. |
| 1.3 | `README.md:583, 654` | "388 tests as of 2026-06-16" / "388 tests, ~8 s" | Currently the freshest number; verify against `pytest --collect-only -q` and freeze in one place. |
| 1.4 | `README.md:1–500` | No top-level "Deploy" section header | Add `## Deploy` between "Reproducing results" and "Grader reproducibility" (or before "Reproducing results"), with a one-liner pointing at `deploy-to-vps.sh`. The current recipe forces a reader to scroll to the bottom of the file. |
| 1.5 | `README.md:71` | Quickstart ships 5 command-blocks for 5 different providers; the 5-min test asks the operator to *set up once and run*. | Trim to the hermetic smoke path (the only path that needs no key) and link to provider-specific recipes in a sub-page. |
| 1.6 | `README.md:264–293` ("Current R/P per provider" table) | The MiniMax row says "Dev-loop wiring is in place … first real end-to-end run is the next Phase 7 deliverable" while the table is dated 2026-06-16. This is fine as a status note but the table is also referenced from the runbook on line 281 as "the only number that matters for product readiness" — the README does not say which row that is. | Add a "Last verified" column to the table; cross-link the row labels to the runbook. |
| 1.7 | `README.md:290–293` | "Reproducing these numbers" instructs re-running `python scripts/optimize.py` but the actual canonical command the README points at is `python run.py` (line 664). | State one canonical command; reference the other as a synonym. |
| 1.8 | `README.md:301` | "Phase 5 (Dashboard) and the cross-provider E2E sweep are not in `src/` yet" — true as of writing, but the sentence is buried under the limitations list. | Move to a "Status" callout above the table. |
| 1.9 | `README.md:432–484` (Layout) | Includes `billing.py`, `audit.py`, `api.py` as "placeholder — billing-domain logic lands post-MVP" but `auditor_module.py`, `auditor_signature.py`, `job_queue.py`, `worker.py`, `x12_parser.py`, `scenario_schema.py`, `messages.py`, `minimax_client.py`, `minimax_errors.py`, `demo_entries.py`, `demo_registry.py` are missing. | Re-render the layout from `ls src/ai_billing_audit/`. |
| 1.10 | `README.md:469` (Layout, `tests/`) | Lists 8 test files. Actual `tests/` directory may have grown; the new `tests/patient-hash.test.ts` in `apps/portal/tests/` is not represented. | Re-render. |
| 1.11 | `README.md:294` | "We are not there yet" relative to "R≥0.95, P≥0.80". | Add the actual gap (current R=0.813, P=0.187) in the same sentence so a reader doesn't have to look at the table. |
| 1.12 | `README.md:264–288` | The R/P table is presented as the project's "product readiness" bar. The unverified claim is on line 275: "F1=1.000 … Diagnostic only; not a production claim" — but this row is *labelled* "smoke (5 train / 3 val)" without a date stamp. Per `docs/BUGS_overfit.md` (already in the repo), the v0 prompt's F1=1.0 is "uninformative" (overfit to a degenerate oracle). The README does not reflect that. | Add a footnote pointing to `docs/BUGS_overfit.md`. |
| 1.13 | `README.md:316–323` | "The default model pin is not a long-term commitment … the first paid contract is supposed to trigger a cutover" — true but undocumented which model will be the cutover target. | Either name the target or remove the sentence. |
| 1.14 | `README.md:316–325` | "The planned `--max-budget USD` flag is not yet wired up; a runaway optimization pass can burn a meaningful amount of money." | This is a known-unmitigated cost risk. Either wire the cap or remove the loop from the quickstart until the cap exists. |
| 1.15 | `README.md:189–194` | `tests/test_minimax_integration.py` description assumes the file exists. | Verify and update the test-file path or remove the section. |

### 1.3 5-minute readability verdict

A new operator reading the README top-to-bottom cannot complete setup in 5 minutes. The realistic path is: venv (2 min), `pip install -e ".[dev]"` (3–5 min on a cold cache), run `pytest` (8 s for 388 tests, fine), and then read the env-var matrix before they can pick a provider. The deploy path is not in any clearly labelled section. **Recommendation:** front-load a single 5-minute happy path, then move provider matrices and reproduction contracts into appendices.

---

## 2. RUNBOOK

**Artifact:** `docs/RUNBOOK.md` (171 lines, 7226 bytes).

### 2.1 Coverage of the four named scenarios

| Scenario | Section? | Runnable steps? | Verdict |
|---|---|---|---|
| `audit_trail chain break` | **Yes** — entire doc (§1, lines 7–143; §2 schema migration) | **Yes** — `psql` + Python verifier (§1.2), exit-code matrix (§1.3), repair procedure (§1.6) | **Runnable.** Single scenario; thorough. |
| `F1 drop` | **No** | n/a | **Missing.** |
| `LLM outage` | **No** | n/a | **Missing.** |
| `billing dispute` | **No** | n/a | **Missing.** |

The RUNBOOK is a single-scenario document about the audit-trail chain. The task body names four scenarios; only one is covered. The other three are absent — they do not exist as even a stub.

### 2.2 Concrete deficiencies (with file:line)

| # | File:line | Problem | Suggested change |
|---|---|---|---|
| 2.1 | `docs/RUNBOOK.md:1–171` (whole doc) | Only `audit_trail chain break` is covered. F1 drop, LLM outage, and billing dispute have no runnable response. | Add three new sections following the same shape as §1: (a) symptom, (b) one-line diagnostic, (c) remediation, (d) escalation. |
| 2.2 | `docs/RUNBOOK.md:1` | "Scope: every command here runs against the production database with the auditor's read-only role. None of them mutate state." | True for §1 only. Any new section about LLM outage or billing dispute will not be read-only. State that the read-only claim is per-section. |
| 2.3 | `docs/RUNBOOK.md:97–115` (§1.4 "first break") | Argues for the case where a break is the original edit point. The "two independent edits" counterfactual in §1.4 is fine but the §1.6 repair path does not actually exercise the verifier's "if a break is **not** the original edit point" branch. | Add a unit-test-style example trace. |
| 2.4 | `docs/RUNBOOK.md:129–143` (§1.6 Repair) | Steps say "Open an incident ticket … the chain resumes from the last verified row's `cryptographic_signature`." There is no script for the resume — only the prose. | Provide a `repair_resume_chain.py` script (or a `psql` heredoc) that takes the last verified row's signature and re-anchors the next row. |
| 2.5 | `docs/RUNBOOK.md:145–159` (§2 Schema migration) | The `audit_trail.sql` migration is referenced as the file in the project root, but the file path is not pinned to a particular release tag. | Add the SQL file's content-hash and the Git commit that introduced it. |
| 2.6 | `docs/RUNBOOK.md:163–171` (§3 References) | Mentions `tests/test_audit_log.py` and "11 tests" — verify or remove. | Run `pytest tests/test_audit_log.py --collect-only -q` and freeze the count. |
| 2.7 | `docs/RUNBOOK.md:147` | "The chain column was added by `audit_trail.sql` in the project root." | True at write time, but the file is now mounted into the postgres container at `/docker-entrypoint-initdb.d/01-audit_trail.sql` per `docker-compose.yml:114`. The runbook does not mention the docker path. | Add a docker variant of the §1.2 verifier. |

### 2.3 F1-drop scenario: what it would need

The F1-drop scenario is not in scope to author (per task: "No invented requirements, features, or scenarios beyond the four named ones"). But the fix-list should record that **no runnable F1-drop response exists**, and the likely inputs are: `prompts/MANIFEST.json` (the append-only log of optimization runs), `artifacts/miprov2_summary.json` (latest run summary), and `scripts/eval_final_test.py` (which exists in the scripts directory but is not referenced by the runbook).

### 2.4 LLM-outage scenario: what it would need

No `LLM outage` response exists. The retry policy lives in `src/ai_billing_audit/minimax_errors.py` (constants `MINIMAX_MAX_ATTEMPTS=3`, exponential backoff base 0.5 s / factor 2.0 / cap 8.0 s — confirmed against the README at lines 559–568). A runbook section would need to: (a) recognize the 429 vs 5xx vs auth split, (b) cap the wait, (c) escalate to a fallback provider, (d) record the outage in the audit trail.

### 2.5 Billing-dispute scenario: what it would need

No `billing dispute` response exists. Likely inputs: `apps/portal/src/lib/billing-page-helpers.ts`, `apps/portal/src/lib/stripe.ts`, `apps/portal/prisma/schema.prisma` (`Invoice`, `EncounterClaim`). The "audit_trail" verifier chain is a partial answer (PHIPA evidence-of-record), but the dispute shape (chargeback / refund / customer escalation) is not covered.

---

## 3. Security page

**Artifact:** `apps/portal/src/app/security/page.tsx` (357 lines, 15522 bytes).

Each claim below was cross-referenced against the live code/configs. Tag legend:

- `confirmed` — the claim is supported by a code/config artifact in the repo.
- `aspirational/unsupported` — the claim is either contradicted by the code or has no implementation evidence in the repo.
- `partial` — partially supported but the page's wording overstates the actual behavior.

### 3.1 Claim-by-claim matrix

| # | Page line(s) | Claim (paraphrased) | Tag | Code/config evidence |
|---|---|---|---|---|
| 3.1.1 | 56–61 | "Canadian customer data lives in AWS ca-central-1 (Montréal). US customer data lives in AWS us-east-1 (N. Virginia). Pick the region at sign-up." | **aspirational/unsupported** | No AWS config exists in the repo (no `*.tf`, no AWS provider block in any compose or k8s file). The only mention of `ca-central-1` is in `apps/portal/.env.example:7` as a comment, and `us-east-1` appears only in `deploy/scripts/backup.env.template:14–15` as a generic S3 example. The actual deployment is to a single VPS at `187.77.26.99` (deploy-to-vps.sh:50, deploy-to-vps.sh:28). The page is selling a multi-region AWS architecture that does not exist. |
| 3.1.2 | 79–80 | "AES-256 on every volume, snapshot, and backup." | **aspirational/unsupported** | The database is `pgvector/pgvector:pg16` in a docker volume `ai_billing_audit_pgdata` (`docker-compose.yml:99–113`). No AES-256 configuration exists for the docker volume, the snapshot, or the backup stream. `deploy/scripts/audit-backup.sh` exists but no in-repo evidence of "AES-256" — only that backups are `age`-encrypted (which is a separate primitive, not a guarantee on every volume/snapshot/backup). |
| 3.1.3 | 80 | "Customer-managed keys are available on Enterprise." | **aspirational/unsupported** | The pricing config in `apps/portal/src/lib/pricing.ts` defines three tiers (`small`, `mid`, `large`) — no `enterprise` tier. No code references customer-managed keys, KMS, or BYOK. |
| 3.1.4 | 83–85 | "In transit: TLS 1.3 only. Older protocol versions are disabled at the load balancer. Certificate rotation is automated." | **partial** | TLS is terminated by host-side Traefik (`deploy-to-vps.sh:11, 165–197`) using `certResolver: letsencrypt`. There is no in-repo artifact pinning `minVersion: TLSv1.3` on Traefik; the actual config lives at `/opt/traefik/traefik.yml` and `/opt/traefik/dynamic/routers.yml` on the host, not in this repo. The in-stack Caddy (`Caddyfile:14`) explicitly states "TLS termination is intentionally NOT configured here." The `certs: ["letsencrypt"]` rotation relies on Let's Encrypt defaults; the page's claim that "older protocol versions are disabled at the load balancer" cannot be verified from the repo alone. |
| 3.1.5 | 87–89 | "Internal: service-to-service calls use mTLS inside the VPC. No plaintext hops." | **aspirational/unsupported** | The internal network is a docker bridge network (`docker-compose.yml:153`, `ai_billing_audit_net`). Caddy → api is plain HTTP (`Caddyfile:18` `reverse_proxy api:8000` — no `transport http` block, no `tls` directive). Postgres is plain TCP on the bridge. There is no mTLS configuration. The "VPC" claim is also wrong — the network is a single-host docker bridge, not a VPC. |
| 3.1.6 | 105–110 | "For US customers we sign a Business Associate Agreement (BAA) under HIPAA. For Ontario and Alberta customers we sign a Health Information Custodian Agent (HIC-Agent) agreement under PHIPA." | **aspirational/unsupported** (operationally), **partial** (terminology) | No BAA / HIC-Agent / Affiliate template exists in the repo. The "we sign the contract" claim is operational, not code — but no `/legal/baa` route, no `legal@ai-billing-audit.ashbi.ca` mail handler, no `legal.md`, and no `apps/portal/public/baa.pdf`. The "two business days" SLA is unsourced. The terminology mix-up: the page lumps Ontario and Alberta under "HIC-Agent agreement under PHIPA" but PHIPA is Ontario-only; Alberta's HIA uses an "Affiliate agreement" model. The compliance matrix (§7) at line 244 correctly distinguishes them ("Affiliate agreement model mirrored from HIC-Agent") — so the section 3 prose contradicts the section 7 matrix. |
| 3.1.7 | 130–134 | "Our AI flags issues on draft claims. Your billing team reviews every flag in a split-screen view … The biller accepts, modifies, or dismisses each finding with one click." | **aspirational/unsupported** (the "modify" verb) | The only finding actions are `accept` and `dismiss`: `AUDIT_ACTIONS = ["accept", "dismiss"]` in `apps/portal/src/lib/encounter-types.ts`. `apps/portal/src/lib/audit-write.ts` references `newFindingStatus: "accepted" | "dismissed"` only. No "modify" action is implemented. The page's claim that a biller can "modify" a finding is contradicted by the only data path that exists. |
| 3.1.8 | 137–141 | "Federal False Claims Act shield … the AI is a decision-support tool, not the decision-maker. Liability for the claim stays with the provider, with full documentary evidence of who approved what and when." | **confirmed (architectural) / aspirational (legal)** | The HITL gate exists at the data level (accept/dismiss). The "full documentary evidence" half is supported by the audit_trail chain (per §3.1.10). The legal claim ("FCA shield") is a position the company takes, not a code artifact — flag as marketing/legal copy, not technical. |
| 3.1.9 | 156–160 | "Our pricing is a flat monthly fee per provider. There is no percentage-of-revenue model, no per-claim bonus, no 'success fee' tied to the dollars we help you recover." | **confirmed** | `apps/portal/src/app/pricing/page.tsx:106–121` and `apps/portal/src/lib/pricing.ts` define three flat-fee tiers. Tier names are "Small practice", "Mid clinic", "Large practice". No commission, no per-claim charge, no revenue share. The pricing config rejects "percentage-of-revenue" models explicitly (`pricing.ts` mentions "rejectedModels"). |
| 3.1.10 | 178–193 | "Every AI flag, accept, modify, and dismiss is written to an append-only `audit_trail` table. Each row carries a SHA-256 hash-chain cryptographic signature … `verify_chain()` walks the chain in timestamp order." | **confirmed (the chain itself) / aspirational/unsupported (the "modify" action, again)** | The chain is real: `src/audit_log.py` (`compute_signature`, `verify_chain`, `walk_chain`), `audit_trail.sql` (the schema with `cryptographic_signature` CHECK constraint, append-only trigger, bulk-action id), `apps/portal/src/lib/audit-write.ts` (server-side helper that writes one row per state change inside a Prisma transaction), `apps/portal/src/lib/audit-chain.ts` (TypeScript port for the portal). The implementation matches the page's description. The "modify" verb in the page's prose is still wrong — see 3.1.7. |
| 3.1.11 | 232–234 | PHIPA control: "HIC-Agent agreement signed before any data is accepted; AES-256 + TLS 1.3; region-pinned storage in ca-central-1; hash-chain audit log." | **aspirational/unsupported** | The "AES-256", "TLS 1.3" (in-repo evidence is partial — see 3.1.4), and "ca-central-1" claims all share the same gap as 3.1.1–3.1.2. The HIC-Agent and hash-chain portions are partial/operational/confirmed respectively. |
| 3.1.12 | 239–247 | HIA (Alberta) control: "Affiliate agreement model mirrored from HIC-Agent; same encryption and residency controls as PHIPA." | **aspirational/unsupported** | Same gap as 3.1.11. The "Affiliate agreement" terminology is correct. |
| 3.1.13 | 252–260 | HIPAA control: "BAA signed before any data is accepted; AES-256 + TLS 1.3; region-pinned storage in us-east-1; hash-chain audit log; HITL approval flow." | **aspirational/unsupported** | Same gap as 3.1.1–3.1.2. The hash-chain and HITL portions are confirmed. |
| 3.1.14 | 263–273 | PIPEDA control: "patient-identifying fields are hashed (salted SHA-256) before storage, never stored in plaintext." | **confirmed (slight wording) ** | `apps/portal/src/lib/patient-hash.ts:75–89` — peppered SHA-256, with the pepper required in production (`assertProductionPepper()` throws on boot if env var missing). The page says "salted" — the actual scheme is **peppered** (server-side secret mixed into the hash before the input, no per-record salt). "Salted SHA-256" is a technically different primitive and overstates the design. The audit_trail column constraint (`audit_trail.sql` line 67) is `~ '^[0-9a-f]{64}$'` — that matches. |
| 3.1.15 | 275–284 | AIDA control: "HITL approval on every flag means a human, not the AI, makes the final call; explainability data attached to every recommendation." | **partial** | HITL is implemented (accept/dismiss). "Explainability data" — the schema carries `data_elements JSONB` and the finding has a `quote` and `rule_ids`, but there is no `explainability_data` column or first-class explainability payload. The chain hash commits the action, not the LLM's reasoning. The page's claim that "explainability data attached to every recommendation" is **aspirational/unsupported** as written. |
| 3.1.16 | 287–301 | US state privacy laws: "No sale or sharing of customer data; minimum-necessary access controls inside the app; data residency in us-east-1; deletion on contract end." | **aspirational/unsupported** | "us-east-1" is the same gap as 3.1.1. "Minimum-necessary access controls" — the authn/authz layer is NextAuth (per `apps/portal/src/app/api/auth/[...nextauth]/route.ts`) but no role-based claim of "minimum-necessary" is enforced anywhere in the surface. "Deletion on contract end" — no `DELETE /api/tenant/{id}` or scheduled-deletion job is referenced in the runbook or the app. |
| 3.1.17 | 303–311 | AKS: "Flat monthly fee per provider. No percentage of revenue, no per-claim bonus, no recovery-linked compensation." | **confirmed** | See 3.1.9. |
| 3.1.18 | 22 (`metadata.description`) | "PHIPA, HIPAA, PIPEDA, AIDA, AKS." | partial | "AKS" appears in the metadata description, the matrix, and the pricing copy. The other five (PHIPA, HIPAA, PIPEDA, AIDA, plus the implicit HITL/FCA) are the surface coverage. The metadata omits HIA. |

### 3.2 Summary

- **Confirmed claims:** flat-fee pricing (§3.1.9, 3.1.17); hash-chain audit log mechanics (§3.1.10); the architectural HITL shape (§3.1.7 / 3.1.8 — minus the "modify" verb).
- **Aspirational / unsupported claims (high priority to fix before this page goes back to a paying customer):**
  - AWS ca-central-1 / us-east-1 region-pinning (§3.1.1, 3.1.11–3.1.13, 3.1.16). The actual stack is a single VPS.
  - AES-256 on every volume, snapshot, and backup (§3.1.2, 3.1.11–3.1.13). No in-repo evidence.
  - "Customer-managed keys are available on Enterprise" (§3.1.3). No Enterprise tier; no BYOK code.
  - mTLS inside the VPC; no plaintext hops (§3.1.5). Caddy → api is plain HTTP.
  - BAA / HIC-Agent contracts (§3.1.6, 3.1.11–3.1.13). No templates, no mail route, no PDF.
  - "Accept, modify, or dismiss" (§3.1.7, 3.1.10). Only `accept` and `dismiss` exist.
  - "Deletion on contract end" / "minimum-necessary access controls" (§3.1.16). No implementation evidence.
- **Wording bugs (low priority but worth fixing in the same pass):**
  - "Salted SHA-256" → should be "peppered SHA-256" (§3.1.14).
  - "HIC-Agent under PHIPA" for Alberta (§3.1.6) — Alberta is HIA, with Affiliate agreements; the §7 matrix gets this right but the section 3 prose does not.
  - "TLS 1.3 only" — only partially supported; the in-stack Caddy explicitly does no TLS termination and the page's claim is on the load balancer, which is host-side Traefik not in this repo.

### 3.3 Fix-list

| # | File:line | Problem | Suggested change |
|---|---|---|---|
| 3.3.1 | `apps/portal/src/app/security/page.tsx:54–67` (Section 1) | "AWS ca-central-1" / "AWS us-east-1" claims. | Either ship the AWS architecture (Terraform / multi-region compose) or rewrite Section 1 to describe the actual deployment (single VPS at `coolify`, docker bridge network, Traefik-terminated public TLS). |
| 3.3.2 | `apps/portal/src/app/security/page.tsx:77–93` (Section 2) | "AES-256 on every volume, snapshot, and backup" / "mTLS inside the VPC" / "Older protocol versions are disabled at the load balancer." | Mark each as **conditional on the deployment tier** (or remove). For a single-VPS deployment, "AES-256 at rest" applies to disk encryption (LUKS / ZFS), not to "every volume." If the intent is "the production cloud build has these controls," say so. |
| 3.3.3 | `apps/portal/src/app/security/page.tsx:80` | "Customer-managed keys are available on Enterprise." | Remove. No Enterprise tier; no BYOK code. |
| 3.3.4 | `apps/portal/src/app/security/page.tsx:88–89` | "service-to-service calls use mTLS inside the VPC. No plaintext hops." | Remove. Caddy → api is plain HTTP. |
| 3.3.5 | `apps/portal/src/app/security/page.tsx:104–111` (Section 3) | "BAA under HIPAA / HIC-Agent under PHIPA for Ontario and Alberta" | Split: "BAA under HIPAA" for US, "HIC-Agent under PHIPA" for Ontario, "Affiliate agreement under HIA" for Alberta. Then describe how to request each. |
| 3.3.6 | `apps/portal/src/app/security/page.tsx:130–134` (Section 4) | "accept, modify, or dismiss" | Replace with "accept or dismiss" — matches `AUDIT_ACTIONS = ["accept", "dismiss"]`. |
| 3.3.7 | `apps/portal/src/app/security/page.tsx:178–184` (Section 6) | "Every AI flag, accept, modify, and dismiss" | Replace with "Every AI flag, accept, and dismiss". |
| 3.3.8 | `apps/portal/src/app/security/page.tsx:268–271` (PIPEDA row) | "hashed (salted SHA-256) before storage" | Replace with "hashed (peppered SHA-256) before storage" — the implementation in `patient-hash.ts` is peppered, not salted. |
| 3.3.9 | `apps/portal/src/app/security/page.tsx:281–284` (AIDA row) | "explainability data attached to every recommendation" | Either ship explainability data (record the LLM prompt, the response, the parsed findings) or remove the claim. |
| 3.3.10 | `apps/portal/src/app/security/page.tsx:295–299` (US state row) | "minimum-necessary access controls" / "deletion on contract end" | Either add role-based access to the auth layer and a tenant-deletion API/route, or remove these claims. |
| 3.3.11 | `apps/portal/src/app/security/page.tsx:1–16` (file header) | "Server component. No client hooks, no fetch." | True, but the file does have `AnalyticsClick` imported on line 21 — verify whether that introduces a client island. |
| 3.3.12 | `apps/portal/src/app/security/page.tsx:296` | "deletion on contract end" | Add an SLA (e.g. "within 30 days of contract end") and link to the runbook. |
| 3.3.13 | `apps/portal/src/app/security/page.tsx` (whole page) | The page's tone reads as a buyer's-guide for healthcare procurement. The claims that have no implementation backing (3.1.1, 3.1.2, 3.1.5, 3.1.6) are the ones a privacy officer will check first. | Tag each control with its **evidence** (file:line) on the page, or link to a `docs/CONTROLS.md` that does. Today a privacy officer has nothing to verify against. |

---

## 4. Inline docstrings

**Method.** Spot-checked 27 Python modules (`src/ai_billing_audit/`, `src/audit_log.py`) and 19 TypeScript modules (`apps/portal/src/lib/`). For each file, counted top-level classes/functions and the subset that carry a docstring / JSDoc / `///` header. Crude boilerplate heuristic: a docstring that is <50 characters and only rephrases the function name with a verb like "Initialize", "Save", "Get", "Set", "Return", "Build", "Compute", "Process", "Handle", "Helper", "Add", "Remove", "Update", "Delete", "Create", "Find", "Format", "Render", "Parse", "Load", "Store", "Write", "Read", "Send", "Fetch".

### 4.1 Python (27 files, 183 classes/functions)

| Stat | Value |
|---|---|
| Total classes/functions | 183 |
| With docstring | 114 (62%) |
| Module-level docstring present | 27/27 (100%) |
| Crude boilerplate suspects | 1 (in `messages.py`) |

Worst offenders (no docstring on at least one top-level def/class):

- `src/ai_billing_audit/synth_agent.py:103, 115, 157, 183` — at least four private helpers (`_validate_tier_variant`, internal tier helpers) without a docstring. Module docstring is fine.
- `src/ai_billing_audit/auditor_module.py:194` — one missing.
- `src/ai_billing_audit/grader.py:134, 222, 244, 291, 372` — five missing.
- `src/ai_billing_audit/grading.py:118, 124, 130, 137, 207` — five missing.
- `src/ai_billing_audit/llm.py:96, 117, 128` — three missing.
- `src/ai_billing_audit/judge.py:203, 271, 300, 304, 308` — five missing.
- `src/ai_billing_audit/messages.py:118, 170` — two missing.
- `src/ai_billing_audit/ground_truth.py` — only 1 of 10 top-level symbols has a docstring. The module docstring is good; the public API in `__all__` is undocumented at the function level.
- `src/ai_billing_audit/api.py:16 functions, 8 docstrings` — half undocumented.
- `src/ai_billing_audit/job_queue.py:15 functions, 7 docstrings`.
- `src/ai_billing_audit/minimax_client.py:5 functions, 2 docstrings` — three undocumented, one of them is the chat method.
- `src/ai_billing_audit/worker.py:3 functions, 1 docstring` — two undocumented, including the entry-point.

Notable **good** Python docstrings (use as templates for missing):

- `src/audit_log.py:1–67` — the module docstring is 67 lines, includes the chain shape, public surface, and migration. `compute_signature` and `verify_chain` carry full `Parameters`/`Returns` blocks.
- `src/ai_billing_audit/minimax_errors.py:1–10` (module) + every public function has a docstring.
- `src/ai_billing_audit/x12_parser.py` — 11/11.

### 4.2 TypeScript (19 files, 298 classes/functions/methods)

| Stat | Value |
|---|---|
| Total classes/functions | 298 |
| With JSDoc / `///` header | 63 (21%) |
| File-level header (top-of-file comment) | 19/19 (100%) |

Worst offenders (high function count, near-zero docstrings):

- `apps/portal/src/lib/onboarding.ts` — 61 functions, 13 with docstrings (21%).
- `apps/portal/src/lib/encounter-list.ts` — 30 functions, **1 with docstring (3%)**.
- `apps/portal/src/lib/email.ts` — 27 functions, 5 with docstrings (19%).
- `apps/portal/src/lib/encounter-types.ts` — 26 functions, 4 with docstrings (15%).
- `apps/portal/src/lib/audit-write.ts` — 24 functions, 8 with docstrings (33%). The writer is security-relevant (it writes to the hash chain); the helpers at lines 65, 98, 114, 121, 149, 187, 278, 282 are undocumented.
- `apps/portal/src/lib/billing-page.ts` — 13 functions, **1 with docstring**.
- `apps/portal/src/lib/encounter-list-client.ts` — 14 functions, **0 with docstring**.
- `apps/portal/src/lib/tenant.ts` — 8 functions, **0 with docstring**.
- `apps/portal/src/lib/prisma.ts` — 3 functions, **0 with docstring**.

Notable **good** TypeScript docstrings (use as templates):

- `apps/portal/src/lib/patient-hash.ts` — module header (40 lines) + `hashPatientId` and `assertProductionPepper` documented. The two private helpers (`resolvePepper`, `DEV_FALLBACK_PEPPER` const) are undocumented but short.
- `apps/portal/src/lib/audit-write.ts` — top-of-file comment + 8 well-shaped JSDoc blocks on the public surface.
- `apps/portal/src/lib/active-tenant.ts` — 3/6 documented.

### 4.3 Auto-generated / template boilerplate

I did not find auto-generated `Args:` / `Returns:` blocks with no real content. The TypeScript files are plain JSDoc-style or uncommented; the Python files use `Parameters` / `Returns` (numpy-style) consistently. The one crude boilerplate hit was in `src/ai_billing_audit/messages.py` (likely a small wrapper). No copies of an obvious template string were found.

### 4.4 Fix-list

| # | File:line | Problem | Suggested change |
|---|---|---|---|
| 4.4.1 | `src/ai_billing_audit/ground_truth.py:35` onward (10 top-level symbols, 1 with docstring) | Public API in `__all__` is undocumented at the function level. `ground_truth_for`, `generate_train_split`, `generate_val_split` are referenced by `scripts/optimize.py` and the runbook. | Add a one-paragraph docstring to each public symbol stating the contract, side effects, and return shape. |
| 4.4.2 | `src/ai_billing_audit/api.py` (16 functions, 8 docstrings) | `FastAPI` surface is half-uncommented. The route handlers are documented; the helpers are not. | Add docstrings to the 8 helpers (line numbers need a fresh `grep -nE "^def \|^async def " src/ai_billing_audit/api.py`). |
| 4.4.3 | `src/ai_billing_audit/minimax_client.py:chat` (and 2 others) | The HTTP client is the project's primary backend for non-dev loops. Three methods undocumented. | Add a docstring to `chat` explaining the retry interaction with `minimax_errors` and the exception tree. |
| 4.4.4 | `src/ai_billing_audit/worker.py:1, 2` (entry-point + 1 helper) | Two of three top-level symbols undocumented; this is the heartbeat loop. | Add a 3-line docstring. |
| 4.4.5 | `apps/portal/src/lib/encounter-list.ts` (30 functions, 1 docstring) | Largest file by symbol count, lowest coverage. | Either document the public surface (top 5–10 functions by call frequency) or split the file. |
| 4.4.6 | `apps/portal/src/lib/encounter-list-client.ts` (14 functions, 0 docstrings) | Client component counterpart to encounter-list. | Document the data-fetching entry points. |
| 4.4.7 | `apps/portal/src/lib/tenant.ts` (8 functions, 0 docstrings) | Tenant scoping is security-relevant (it gates which rows a request can see). | Document each helper with the scoping rule it implements. |
| 4.4.8 | `apps/portal/src/lib/audit-write.ts:65, 98, 114, 121, 149, 187, 278, 282` | Hash-chain writer has 8 undocumented helpers. | Add a one-liner to each, especially the ones that compute the chain field. |
| 4.4.9 | `apps/portal/src/lib/billing-page.ts` (13 functions, 1 docstring) | Stripe-driven billing page. | Document the public surface. |
| 4.4.10 | `apps/portal/src/lib/email.ts` (27 functions, 5 docstrings) | Email helpers — one missing is fine; ten is not. | Document the 5–10 most-called helpers. |
| 4.4.11 | `apps/portal/src/lib/onboarding.ts` (61 functions, 13 docstrings) | Onboarding wizard. | Document the public surface. |
| 4.4.12 | All sampled files | No `///` doc-comment blocks on the 19 TS files outside of `patient-hash.ts` and the route handlers. | Encourage `///` style (TypeDoc-compatible) for the 4–6 most-imported modules: `audit-write.ts`, `audit-chain.ts`, `patient-hash.ts`, `tenant.ts`, `encounter-types.ts`, `billing-page-helpers.ts`. |
| 4.4.13 | `src/ai_billing_audit/grader.py:134, 222, 244, 291, 372` | Five private helpers undocumented in the deterministic grader. | Add a one-line docstring each — the grader is the source of truth for the R/P numbers in the README and the MANIFEST. |
| 4.4.14 | `src/ai_billing_audit/grading.py:118, 124, 130, 137, 207` | Five private TP/FP/FN helpers undocumented. | Same as 4.4.13 — the TP/FP/FN matcher is the project's correctness contract. |

---

## 5. Out-of-scope confirmation

Per the task body, this review does **not**:

- Rewrite the README, RUNBOOK, or security page.
- Edit code, config, or security-relevant behavior to match aspirational claims.
- Add new on-call scenarios beyond the four named (F1 drop, LLM outage, billing dispute are flagged as missing; the runbook sections for them are not authored here).
- Review other docs (API reference, changelog, contributing guide, `docs/auditor.md`).
