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

Zorva is managed as four connected surfaces with separate release evidence:

1. **Customer product:** the tenant-scoped audit workflow used by clinic teams.
2. **Public marketing website:** evidence-backed discovery, trust, qualification,
   and pilot-request journeys on `zorva.ashbi.ca`.
3. **Company admin application (Zorva HQ):** a private operator workspace for
   marketing operations, lead and sales management, client onboarding and work,
   account health, support, and company reporting. It is not a tenant admin page
   and must not expose clinic PHI by default.
4. **Brand and growth system:** the positioning, claims, identity, content,
   campaigns, measurement, and governance used consistently across product,
   website, sales, onboarding, and support.

## Verified current state

- Repository: `camster91/ai-billing-audit`, private, default branch `main`.
- Product surfaces: Python/FastAPI audit service and a separate Next.js portal.
- The portal already contains a broad public marketing site, but the approved
  indexable production surface is intentionally limited to `/`,
  `/how-it-works`, and `/contact`; deferred routes remain claim-gated under
  `docs/MARKETING_PUBLIC_LAUNCH_GATES.md`.
- Brand foundations and production rules exist in `docs/BRAND_BOOK.md` and its
  linked discipline files. They have not yet been fully reconciled with this
  plan's current Alberta-first position and proof standard.
- Company-operation foundations exist in the `Lead` pipeline fields, lead
  notifications, tenant/account data, billing records, and a narrow
  `PLATFORM_ADMIN_EMAILS` control. No complete operator-facing Zorva HQ route,
  platform-admin authorization model, support case system, or unified company
  workflow is implemented.
- Code versions: Python package `0.4.0`; Next.js `15.5.21`; React `19.2.4`.
- Canonical development runtimes: Python 3.11, Node 20.19.x, pnpm 9.15.9.
- Current evaluated engine claim in the README: v12 AHCIP, micro F1 0.690 on
  10 cleaned encounters / 13 gold findings. This is repository evidence, not
  customer validation or production performance.
- Automated verification on 2026-08-28: 1,868 Python tests passed and one
  credential-gated MiniMax integration test skipped; portal unit suites, ESLint,
  TypeScript, and the Next.js production build passed locally.
- GitHub Actions workflows exist, but repository Actions were disabled during
  the 2026-08-28 reconciliation. They were re-enabled for PR #88. Both PR
  workflows then triggered, but GitHub refused to start every job because of
  failed account payments or an insufficient Actions spending limit. CI proof
  is blocked on an owner billing decision, not a reported code/test failure.
- Read-only production probes on 2026-08-28 confirmed the API root, `/healthz`,
  and `/readyz` return HTTP 200. The API reports version 0.4.0 and configured
  readiness dependencies. The portal root and `/contact` return HTTP 200, while
  the portal `/readyz` route returns HTTP 404. That route reached `main` in
  commit `f2dea7f` on 2026-08-26, so production is likely serving an older build
  or an untracked source. GitHub reports no deployments or environments for the
  repository, so exact release identity is unproven. Backups, monitoring, data
  residency, and real transaction paths remain unverified.
- Customer usage, retention, conversion, willingness to pay, and paid-pilot
  evidence were not found. Product-market fit and market leadership are
  unvalidated hypotheses.

## Primary objective

**Commercial operating foundation — in progress.** Establish one evidence-backed
system connecting acquisition, lead ownership, pilot sales, onboarding, customer
delivery, support, and product outcomes without weakening tenant or PHI controls.

Acceptance criteria:

1. The public website has a defined audience, offer, primary conversion, claim
   register, content ownership, and end-to-end lead routing evidence.
2. Zorva HQ has a reviewed specification, deny-by-default platform-admin access,
   auditable sales/client/support workflows, and no default PHI access.
3. The customer product, public website, and operator system share stable brand,
   terminology, account identity, funnel stages, and measurable outcomes.
4. The first controlled Alberta clinic pilot can be managed from qualified lead
   through onboarding, first reviewed audit, support, and renewal decision.
5. Existing release-reproducibility work remains green locally and passes CI
   after the GitHub billing blocker is resolved.

## Commercial and marketing plan

**Primary audience:** Alberta primary-care clinic owners, practice managers, and
billing leads with meaningful AHCIP claim volume and no enterprise revenue-
integrity team. Privacy officers and IT reviewers are a required trust audience.

**Focused offer:** a controlled, human-reviewed AHCIP pre-submit audit pilot. The
current primary conversion is a qualified contact/pilot request, not an
unassisted production purchase. Pricing, duration, inclusions, and guarantees
remain decision-gated until owner approval and supporting evidence exist.

**Acquisition sequence:** founder-led qualified outreach and referrals first;
billing-consultant/channel relationships second; evidence-backed high-intent
search and educational content third; paid acquisition only after conversion,
unit economics, consent, and attribution are measurable.

**Funnel:** qualified visit or outreach response -> contact request -> owner
assigned -> discovery -> demo -> pilot approval -> privacy/onboarding complete ->
first reviewed audit -> recurring use -> paid/renewal decision. Zorva HQ owns the
record, next action, evidence, and stage timestamps for every step.

**Marketing governance:** `docs/BRAND_BOOK.md` remains the brand reference and
`docs/MARKETING_PUBLIC_LAUNCH_GATES.md` remains the route-promotion checklist;
both are supporting evidence subordinate to this plan. Claims require source,
owner, approval state, expiry/review date, and public-use permission. No invented
testimonials, customer results, certifications, urgency, or performance claims.

**Commercial measurements:** qualified conversion rate, lead response time,
stage conversion and age, demo-to-pilot rate, onboarding completion, time to
first reviewed audit, weekly active clinics, support burden, pilot-to-paid rate,
retention, revenue attribution, gross margin, and AI cost per active clinic.

## Authoritative roadmap

| Priority | Outcome | Status | Evidence / dependency | Release consequence |
| --- | --- | --- | --- | --- |
| P0 | Restore reproducible green release gates | Implemented and locally verified; CI blocked by GitHub billing | Issues #8, #25, #27, #31; PR #88 and 2026-08-28 local baseline | Blocks release until CI jobs can run and pass |
| P0 | Verify production identity, tenant isolation, PHI storage/retention, database migrations, backup/restore, and credential rotation | Blocked on operator/live access and accountable approval | Issues #5, #6, #10, #11, #12, #14 | Blocks any real-clinic data |
| P0 | Verify pricing-to-checkout-to-onboarding-to-first-audit journey | Proposed | Issues #7, #9; needs production-like Stripe and audit-provider configuration | Blocks paid pilot |
| P0 | Verify production contact delivery and assign a lead owner | Blocked on operator confirmation | Issue #74 | Blocks public acquisition |
| P0 | Specify and build Zorva HQ platform-admin foundation | Specified; implementation proposed | Issue #89; `docs/COMPANY_ADMIN_SPEC.md`; existing Lead and tenant/billing models | Blocks operating a pilot safely at company level |
| P0 | Reconcile brand promise, public claims, and approved offer | In progress | `docs/BRAND_BOOK.md`, `docs/BRAND_NARRATIVE.md`, `docs/MARKETING_PUBLIC_LAUNCH_GATES.md` | Blocks promotion of deferred marketing routes |
| P0 | Verify qualified-lead journey from source attribution through owner response | Partially implemented; not live-verified | Contact form, Lead model, notifications; issue #74 | Blocks measurable acquisition |
| P1 | Make all public product and compliance claims evidence-backed | In progress | Issues #14, #22, #77 | Blocks broad public launch |
| P1 | Promote the smallest complete marketing website journey | Core routes released; broader site gated | Homepage, how-it-works, contact, deferred route register | Blocks broad public marketing |
| P1 | Add sales pipeline, client onboarding/work, account health, and support workflows to Zorva HQ | Proposed | Zorva HQ foundation and approved operating process | Required before scaling beyond a founder-managed pilot |
| P1 | Establish content, campaign, SEO/AI-search, attribution, and review cadence | Proposed | Brand/claims reconciliation and analytics consent | Required for repeatable acquisition |
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
| 2026-08-28 | Treat product, marketing website, Zorva HQ, and brand/growth as one commercial system with separate gates | A customer journey cannot be operated safely from acquisition through support using the current tenant portal alone | Evidence supports a different operating model |
| 2026-08-28 | Build the internal operator system inside the existing portal codebase under a distinct platform-admin boundary | Reuses account, lead, billing, and design foundations while avoiding a second deployment initially | Security review or operating scale requires physical separation |

## Risk and access register

| Area | State | Risk / required action | Owner |
| --- | --- | --- | --- |
| Repository | Available with admin/push access | Actions restored for PR #88, but account billing prevents runners from starting; `main` has no branch protection | Cameron |
| Local development | Available | Default host runtimes differ from CI; use pinned versions | Engineering |
| Production hosts and secrets | Not inspected | Cannot verify release, residency, credentials, backups, or monitoring | Operator / Cameron |
| Billing | Code present, live state unverified | Requires test-mode journey, approved pricing, then production approval | Cameron |
| Legal/privacy | Draft artifacts only | HIA/privacy representations require accountable professional review | Cameron / counsel |
| Analytics and customers | No current evidence found | Cannot claim activation, retention, ROI, or product-market fit | Product owner |
| Brand and claims | Existing system, partially stale | Reconcile anchor claims, market scope, proof, and dark-only implementation before broader use | Product / brand owner |
| Company administration | Data foundations only | No complete operator UI; platform-admin authorization and PHI separation require implementation and security tests | Cameron / Engineering |
| Marketing operations | Core site released, broader routes gated | Lead delivery, ownership, attribution, consent, and content governance need live proof | Cameron / Marketing |

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
- Reopened PR #88 to trigger the configured `e2e` and `test-on-pr` workflows.
  Every job was rejected before its first step because of failed GitHub account
  payments or an insufficient Actions spending limit. No CI test executed.
- Confirmed through the GitHub API that `main` has no branch-protection rule.
- Read-only live probes returned HTTP 200 for the API root, API `/healthz`, API
  `/readyz`, portal root, and portal `/contact`. Portal `/readyz` returned HTTP
  404, so portal readiness monitoring is not proven on the deployed release.
- Traced portal `/readyz` to main-branch commit `f2dea7f` from 2026-08-26 and
  confirmed GitHub has no deployment or environment records for this repository.
  The production 404 therefore indicates probable release drift, but the exact
  deployed commit cannot be established from available read-only evidence.
- Expanded the product model into four connected surfaces: customer product,
  public marketing website, private Zorva HQ company administration, and the
  shared brand/growth system.
- Added `docs/COMPANY_ADMIN_SPEC.md` with a deny-by-default, no-PHI-by-default
  operator journey across leads, sales, onboarding, client work, support,
  marketing operations, and company reporting.
- Added `docs/MARKETING_PLAN.md` with the initial Alberta audience, pilot-led
  offer hypothesis, channel sequence, website promotion order, funnel ownership,
  measurement, brand reconciliation, and approval gates.

## Next action

Implement the Zorva HQ platform-admin authorization and read-only Today/lead
foundation locally while the owner resolves or explicitly declines the GitHub
Actions billing requirement. Then rerun PR #88, repair in-scope failures, and
verify contact routing and production release identity. Do not deploy, change
customer-visible pricing, contact clinics, or access real clinic data without
explicit approval.
