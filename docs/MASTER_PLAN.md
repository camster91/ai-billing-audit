# Zorva product control

**Status:** authoritative repository plan  
**Last reconciled:** 2026-08-28  
**Owner:** Cameron Ashley  
**Review cadence:** before every release and at least weekly while launch work is active

This is the repository source of truth for product status and priority. Dated
files under `research/`, `audits/`, and `docs/daily_report_*` are evidence and
history, not current commitments. GitHub issues hold implementation detail;
this document decides their order and release consequence.

## Product charter

Zorva is an Alberta-first, pre-submit medical-claim auditor for clinics using
AHCIP. Its initial job is to help a biller find defensible claim problems before
submission, review every finding, and retain a traceable decision record.

The initial customer is an Alberta primary-care clinic with enough claim volume
to feel denial and underbilling costs but without a dedicated enterprise
revenue-integrity team. The focused promise is faster, reviewable AHCIP claim
checking; it is not autonomous billing, legal advice, a certified compliance
system, or a multi-jurisdiction payer engine.

## Verified current state

- Repository: `camster91/ai-billing-audit`, private, default branch `main`.
- Product surfaces: Python/FastAPI audit service and a separate Next.js portal.
- Code versions: Python package `0.4.0`; Next.js `15.5.21`; React `19.2.4`.
- Canonical development runtimes: Python 3.11, Node 20.19.x, pnpm 9.15.9.
- Current evaluated engine claim in the README: v12 AHCIP, micro F1 0.690 on
  10 cleaned encounters / 13 gold findings. This is repository evidence, not
  customer validation or production performance.
- Automated verification on 2026-08-28: 1,868 Python tests passed and one
  credential-gated MiniMax integration test skipped; portal unit suites, ESLint,
  TypeScript, and the Next.js production build passed locally.
- GitHub Actions workflows exist, but repository Actions were disabled during
  the 2026-08-28 reconciliation. They were re-enabled for PR #88; green local
  checks are not CI proof until those runs complete.
- Read-only production probes on 2026-08-28 confirmed the API root, `/healthz`,
  and `/readyz` return HTTP 200. The API reports version 0.4.0 and configured
  readiness dependencies. The portal root and `/contact` return HTTP 200, while
  the portal `/readyz` route returns HTTP 404. Deployment identity, backups,
  monitoring, data residency, and real transaction paths remain unverified.
- Customer usage, retention, conversion, willingness to pay, and paid-pilot
  evidence were not found. Product-market fit and market leadership are
  unvalidated hypotheses.

## Primary objective

**Release truth and reproducibility — verified locally.** A clean checkout must have
one documented setup path and pass the same blocking checks locally and in CI.

Acceptance criteria:

1. Python, Node, and pnpm versions are explicit and consistent with CI.
2. Dependency installation, unit tests, lint, type checking, and production
   builds have documented commands that exist and succeed.
3. This plan contains current verification evidence and supersedes conflicting
   dated roadmaps.
4. No release claim relies on stale audit documents or unverified production
   state.

## Authoritative roadmap

| Priority | Outcome | Status | Evidence / dependency | Release consequence |
| --- | --- | --- | --- | --- |
| P0 | Restore reproducible green release gates | Implemented and locally verified; CI proof pending | Issues #8, #25, #27, #31; 2026-08-28 local baseline | Blocks release until CI is green |
| P0 | Verify production identity, tenant isolation, PHI storage/retention, database migrations, backup/restore, and credential rotation | Blocked on operator/live access and accountable approval | Issues #5, #6, #10, #11, #12, #14 | Blocks any real-clinic data |
| P0 | Verify pricing-to-checkout-to-onboarding-to-first-audit journey | Proposed | Issues #7, #9; needs production-like Stripe and audit-provider configuration | Blocks paid pilot |
| P0 | Verify production contact delivery and assign a lead owner | Blocked on operator confirmation | Issue #74 | Blocks public acquisition |
| P1 | Make all public product and compliance claims evidence-backed | In progress | Issues #14, #22, #77 | Blocks broad public launch |
| P1 | Run a controlled Alberta clinic pilot with approved offer and privacy terms | Decision-dependent | Issues #76, #78; requires owner, legal/privacy, and customer approval | Required for customer validation |
| P1 | Establish readiness monitoring, accessibility, performance, rollback, and release qualification | Proposed | Issues #23, #24, #25, #30 | Blocks launch-ready claim |
| P2 | Improve differentiated AHCIP audit quality using a representative, leakage-controlled evaluation set | Proposed | v13 draft exists; real-customer data use requires approval and governance | Does not precede P0 trust gates |

All other open issues are backlog until they support one of these outcomes.
Older sequences in `research/00-ROADMAP.md` and
`research/P0-PRODUCT-ROADMAP.md` are **superseded** by this ordering.

## Decisions

| Date | Decision | Basis | Reversal condition |
| --- | --- | --- | --- |
| 2026-08-28 | Position Zorva as Alberta-first AHCIP pre-submit review, not generic LLM billing audit or multi-market automation | Current README, code, evaluation artifacts, and issue backlog | Verified customer and product evidence supports expansion |
| 2026-08-28 | Treat production status as unknown until live verification | Repository deployment documentation is not runtime evidence | Operator-backed live checks and release report are recorded |
| 2026-08-28 | Use Python 3.11, Node 20.19.x, and pnpm 9.15.9 as the development baseline | Existing CI workflow and dependency support ranges | CI/toolchain migration is implemented and verified |
| 2026-08-28 | Re-enable repository GitHub Actions for PR verification | Actions were disabled and PR #88 received no repository CI runs | Owner intentionally disables CI with a documented replacement gate |

## Risk and access register

| Area | State | Risk / required action | Owner |
| --- | --- | --- | --- |
| Repository | Available with admin/push access | Actions restored for PR #88; current green checks and branch-protection evidence still pending | Cameron |
| Local development | Available | Default host runtimes differ from CI; use pinned versions | Engineering |
| Production hosts and secrets | Not inspected | Cannot verify release, residency, credentials, backups, or monitoring | Operator / Cameron |
| Billing | Code present, live state unverified | Requires test-mode journey, approved pricing, then production approval | Cameron |
| Legal/privacy | Draft artifacts only | HIA/privacy representations require accountable professional review | Cameron / counsel |
| Analytics and customers | No current evidence found | Cannot claim activation, retention, ROI, or product-market fit | Product owner |

## Metrics required before launch claims

- Activation: percent of qualified clinics reaching a first reviewed audit.
- Time to first value: signup/import to first accepted or corrected finding.
- Core-task success: successful uploads and completed audits, including recovery.
- Quality: precision, recall, F1, acceptance, correction, and false-negative review
  on a representative, governed evaluation set.
- Reliability: availability, audit latency, queue failure rate, and recovery time.
- Economics: AI/infrastructure cost per audited claim and per active clinic.
- Commercial: pilot-to-paid conversion, retention, churn, and support burden.

Baselines are unknown unless explicitly backed by current evidence.

## Work log

### 2026-08-28

- Cloned and reconciled current `main` at `4c08e5d`.
- Confirmed the repository identity differs from its generic GitHub description.
- Confirmed `docs/MASTER_PLAN.md` was linked but missing and created this source
  of truth.
- Confirmed the host default Python 3.9 and pnpm 11 do not match CI; pinned the
  supported development baseline.
- Portal frozen install succeeds with pnpm 9.15.9 but fails with pnpm 11 because
  pnpm 11 ignores the package-level override configuration.
- Found and fixed a blocking ESLint error in the Plausible preload queue;
  focused analytics tests pass (19/19).
- Fixed configured log-path handling for encrypted doctor opt-outs and appeal
  outcomes. The prior code attempted to create `/app/logs` even when a safe
  test or operator path was supplied.
- Moved lead rate limiting after structural and disposable-address validation,
  so form corrections no longer consume a visitor's valid-submission quota.
- Fixed the portal readiness result type and added a self-initializing,
  sequential unit-test command that avoids shared SQLite and in-memory limiter
  interference. Server/seed-dependent tests remain explicitly separate.
- Verification: Python `1868 passed, 1 skipped`; portal unit suites passed;
  ESLint passed; TypeScript passed; Next.js 15.5.21 production build passed;
  Ruff passed; formatting passed; mypy passed across 71 source files.
- The production build initially hit a full local disk after compiling. Only
  this checkout's disposable `.next` output was removed; the retry completed.
- Opened PR #88 from `codex/release-truth-reproducibility`; GitGuardian passed.
  Repository GitHub Actions were disabled, so they were re-enabled to restore
  independent PR verification.
- Read-only live probes returned HTTP 200 for the API root, API `/healthz`, API
  `/readyz`, portal root, and portal `/contact`. Portal `/readyz` returned HTTP
  404, so portal readiness monitoring is not proven on the deployed release.

## Next action

Obtain green CI evidence on PR #88 and repair any in-scope failures. Then verify
the remaining production readiness gates with the smallest required operator
access, beginning with portal readiness routing and release identity. Do not
deploy, change customer-visible pricing, contact clinics, or access real clinic
data without explicit approval.
