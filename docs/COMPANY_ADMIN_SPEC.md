# Zorva HQ company admin specification

**Status:** roadmap-approved; platform foundation and lead workflow implemented locally
**Owner:** Cameron Ashley  
**Last reconciled:** 2026-08-28  
**Authority:** detailed specification supporting `docs/MASTER_PLAN.md`

## Purpose

Zorva HQ is the private operating workspace for running the company from first
marketing touch through sales, pilot delivery, client success, support, and
renewal. It is distinct from a clinic's tenant administration experience.

The first release should replace fragile spreadsheet/database inspection for a
single founder-operator. It is not an ERP, accounting system, bulk-email tool,
autonomous sales agent, or unrestricted production-data console.

## Users and access boundary

- Initial user: the accountable Zorva owner/operator.
- Future roles: platform owner, sales, client success, support, and read-only
  analyst, added only when a real staffing need exists.
- Access must fail closed through a server-verified platform role. A session
  cookie, tenant `owner`/legacy `admin` role, hidden navigation item, or email
  allowlist alone is insufficient authorization for company-wide data.
- Every read and mutation of lead, client, subscription, and support records is
  auditable with actor, action, target, timestamp, and request correlation.
- Clinic PHI is excluded from HQ by default. Support sees record identifiers and
  operational metadata, not clinical notes, claim content, or findings. Any
  exceptional support access requires explicit clinic request, least privilege,
  reason, expiry, and an audit record.

## First complete operating journey

1. A qualified visitor submits the reviewed public contact form with source
   attribution and consent state.
2. HQ creates or deduplicates the lead, assigns an owner, records a due next
   action, and alerts on delivery or routing failure.
3. The owner records discovery notes, qualification, stage changes, objections,
   and the next action; outbound messages remain human-approved and are logged.
4. An approved pilot creates a linked organization/client record and onboarding
   checklist without copying PHI into the commercial record.
5. HQ shows onboarding progress, first-value status, product usage aggregates,
   billing state, open support work, account risks, and next success action.
6. A support request is triaged, owned, responded to through an approved channel,
   resolved, and connected to product feedback without exposing unnecessary PHI.
7. The pilot closes with an evidence-backed paid, extend, or stop decision.

## MVP modules and acceptance criteria

### Today

- Counts requiring action: new/unowned leads, overdue next actions, onboarding
  blockers, open/high-priority support cases, failed notifications, billing risk,
  and pilots awaiting a decision.
- Every number links to the filtered underlying records and declares its source
  and freshness. Empty, error, permission, and stale-data states are explicit.

### Leads and sales

- Search, deduplication, owner, source/campaign, qualification, stage history,
  next action/due date, loss reason, notes, and conversion linkage.
- Validated transitions and append-only activity history prevent silent stage
  rewriting. No automated external message is sent without separate approval.
- Funnel and stage-age reporting uses stored event timestamps rather than the
  current stage alone.

**Implemented local increment (2026-08-28):** authorized platform owners and
sales operators can open a lead detail view, assign an active owner/sales user,
move through validated stages, set or clear a dated next action, record a loss
reason, and log contact. Mutations use optimistic version checks and UUID
idempotency keys, append field-level `LeadActivity` records, and write one
correlated `PlatformAuditEvent`. The form and API reject common clinical-content
terms in commercial next actions and never send an external message. Lead
deduplication, qualification notes, conversion linkage, stage-age reporting,
and production-like accessibility remain outstanding.

### Clients and delivery

- Links a converted lead to tenant, contacts, approved offer, pilot dates,
  onboarding checklist, data/privacy approvals, first-value milestone, client
  owner, health status, and renewal decision.
- Client work uses tasks with owner, due date, status, priority, and evidence.
  It does not duplicate clinical encounters or store clinical free text.

**Implemented increments (2026-08-31 through 2026-09-01):** an authorized platform owner or
client-success operator can convert one `pilot_signed` lead into one idempotent,
audited `ClientEngagement`. Conversion creates four no-PHI onboarding tasks but
does not create a tenant, charge, or message anyone. Authorized operators can
version and audit task status, priority, owner, due date, and business-evidence
reference. Stale writes fail; clinical-content terms are rejected. Authorized
operators can also version and audit engagement status, privacy approval,
first-value, and health milestones, and create retry-safe custom company tasks
with controlled ownership, priority, and due dates. Tenant linkage remains a
separate approved customer action.

### Support

- Case intake, category, severity, status, owner, due/response timestamps,
  affected tenant, safe description, linked product issue, and resolution.
- Defines acknowledgement and resolution targets as internal operating goals
  until a customer-visible SLA is explicitly approved.
- Supports escalation, duplicate linking, reopen, and post-incident follow-up.

**Implemented local increment (2026-09-01):** owner, client-success, and support
operators have separate support read/write capabilities. They can open and
version internal no-PHI cases linked to an existing client engagement, assign
an eligible operator, classify category and severity, move status, set an
internal target, and link a no-PHI product issue. Creation and updates are
UUID-idempotent and write both a case activity and platform audit event.
Acknowledgement/resolution timestamps are derived from status. No action sends
a reply or publishes a customer-visible SLA. Duplicate linking, reopen policy,
post-incident follow-up, and inbound customer intake remain follow-on work.

### Marketing operations

- Campaign/source registry, approved content/asset status, target segment,
  channel, owner, launch and review dates, cost only when approved, and outcome
  attribution.
- Claim register tracks exact claim, source, allowed surfaces, approver, approval
  status, review/expiry date, and replacement/withdrawal history.
- Content calendar and campaign execution do not send or publish externally from
  HQ until separately authorized.

**Implemented local increment (2026-09-01):** a distinct marketing role can
draft and manage exact claims and content assets; owner, sales, client-success,
and analyst roles receive bounded claim-registry visibility. Only the accountable
owner can approve a claim. Approval requires an evidence reference and allowed
surfaces, with written-permission references required for customer-derived
claims. Claim-bearing assets cannot be approved unless their linked claim is
currently approved for the asset channel. Records are versioned, retry-safe,
operator-audited, and have append-only marketing activity. The registry cannot
publish, send, spend, or alter pricing.

**Implemented local campaign increment (2026-09-01):** campaigns record a stable
source key, objective, segment, channel, approved content, owner, landing/UTM
attribution, planned dates, reviews, external-activation approval, and approved
budget/spend evidence. Marketers can plan and prepare; only the accountable
owner can record an externally activated campaign, and an approval reference is
mandatory. Append-only attribution snapshots preserve null as unknown and zero
as measured zero, require a source reference, validate funnel ordering, and use
explicit CAD cents. HQ cannot launch, message, publish, or spend.

### Company reporting

- Acquisition, sales, activation, client success, support, revenue attribution,
  and cost-to-serve definitions match `docs/MASTER_PLAN.md`.
- Metrics distinguish unknown, zero, delayed, and unavailable. No fabricated
  baselines, customer results, or vanity success states.

## Data model direction

Extend the existing `Lead` model through related records rather than adding more
nullable fields indefinitely. Candidate entities are `PlatformUserRole`,
`LeadActivity`, `LeadAssignment`, `Organization`, `ClientEngagement`,
`OnboardingTask`, `CompanyTask`, `SupportCase`, `SupportActivity`, `Campaign`,
`ContentAsset`, and `ClaimApproval`.

Names are proposed until schema review. Each entity needs retention, deletion,
export, tenant linkage, audit, and sensitive-data classification before migration.

## Delivery sequence

1. Platform-admin authorization, audit trail, safe navigation, and denial tests.
2. Read-only Today dashboard backed by current lead/account/billing records.
3. Lead pipeline with activity history, assignment, next action, and conversion.
   Assignment, next action, stage history, and loss reason are implemented
   locally; pilot conversion is implemented through the client handoff;
   deduplication and qualification remain.
4. Client/pilot onboarding and company task management. Conversion, default and
   custom tasks, and engagement-level milestones are implemented locally;
   tenant linkage remains approval-gated.
5. Support case workflow and product-feedback linkage. Core internal case
   creation, assignment, status, targets, activity, and issue linkage are
   implemented locally; inbound intake and advanced escalation remain.
6. Marketing claims/content/campaign operations and attribution. Claim/content
   governance plus campaign/source planning and evidence attribution are
   implemented locally; automated execution remains absent and approval-gated.
7. Reporting, retention/export/deletion, accessibility, performance, backup,
   monitoring, and operator runbook verification.

Each increment requires responsive and keyboard-accessible behavior, tenant and
platform authorization tests, audit evidence, migration and rollback steps,
failure/recovery states, and no high-severity privacy or security finding.

### Platform-role bootstrap

The initial role is provisioned only after the user has completed normal Auth.js
sign-in. From `apps/portal`, the operator can run `pnpm hq:manage-role` with
`--action`, `--email`, `--role`, `--granted-by`, and
`--confirm-role-change`. Production additionally requires
`--confirm-production`. The command never creates users, masks the email in its
output, and records grants/revocations in `PlatformAuditEvent`. Running it
against production remains an approval-gated privileged action.

`PlatformAuditEvent` and `LeadActivity` are database-append-only: SQLite and
PostgreSQL migration triggers reject every update and delete while allowing new
events. There is no application bypass. `docs/HQ_HISTORY_OPERATIONS.md` defines
the approval-gated policy decision and future purge procedure. Retention-period
approval, export implementation, and production verification remain required;
the tenant clinical hash chain is not reused or represented as proof for
company-operator events.

## Explicitly deferred

- Autonomous outreach, support replies, or campaign publishing.
- Bulk cold-email delivery and purchased contact lists.
- Payroll, bookkeeping, tax filing, legal case management, or full ERP features.
- Direct browsing of raw clinical records from the company admin surface.
- Customer-visible pricing or SLA changes.
- Multi-company white-labelling or non-Alberta market expansion.

## Release gate

Zorva HQ is not operationally verified until the platform-owner login, lead-to-
client journey, support workflow, audit log, access-denial cases, backup/restore,
and representative mobile/desktop accessibility checks pass in a production-like
environment. Production publication requires named owner approval.
