# Zorva API Reference

Public REST API for Zorva — pre-submission billing-audit platform.
This document is the authoritative reference for every endpoint a
third-party integrator is allowed to call. Endpoints not listed
here are internal.

## Conventions

- **Base URL:** `https://portal.zorva.health` (production) /
  `http://localhost:3000` (local dev).
- **Authentication:** every endpoint except `/api/leads`,
  `/api/billing/webhook`, `/api/email/webhook`, and `/api/auth/*`
  requires a signed-in session cookie **and** an active tenant.
  Programmatic access uses a bearer token issued per tenant via
  `POST /api/team/invite` (role `integrator`); pass it as
  `Authorization: Bearer <token>`.
- **Content-Type:** `application/json` for all POST/PATCH bodies.
- **Versioning:** breaking changes bump the path prefix to
  `/api/v2/...`. Current endpoints are implicitly v1.
- **Error shape:** `{ error: string, detail?: string }` with HTTP
  status codes from the standard 4xx / 5xx set. `402 Payment
  Required` is used for quota exhaustion (see `/api/audit/run`).
- **Idempotency:** write endpoints either accept an `Idempotency-Key`
  header (billing) or are naturally idempotent via terminal-state
  checks (findings). A retry on an already-terminal inbox returns
  `409 Conflict` with `already_terminal: [...]`.

## Auth & tenant

### `GET /api/auth/[...nextauth]`

NextAuth handler. Login is magic-link only. **External callers
should not call this directly** — sign in via the dashboard, then
use the issued session cookie on subsequent calls.

### `POST /api/leads`

Public lead capture from the marketing site. No auth.

**Body**

```json
{ "email": "string", "name": "string", "clinicSize": "solo|group|enterprise", "note": "string?" }
```

**Response 200:** `{ ok: true }`

### `POST /api/usage`

Authenticated. Returns the caller's per-tenant usage counter for
the current billing period.

**Response 200**

```json
{ "tenantId": "string", "auditsUsed": 42, "auditQuota": 1000, "periodEnd": "2026-07-31" }
```

## Audit

### `POST /api/audit/run`

Server-side quota gate for running an audit. Atomically increments
`Tenant.auditQuotaUsed`. At 80% emits a one-time warning email; at
100% rejects with HTTP 402.

**Auth:** session cookie or bearer token. Caller must have the
`write` capability (viewers blocked).

**Body**

```json
{ "encounterId": "string?" }
```

`encounterId` is currently informational — the quota gate is
per-tenant, not per-encounter.

**Response 200**

```json
{
  "allowed": true,
  "state": "ok" | "warn",
  "used": 42,
  "quota": 1000,
  "percent": 4.2,
  "warnedNow": false,
  "upgradeUrl": "/billing/change-tier"
}
```

**Response 402**

```json
{ "allowed": false, "state": "blocked", "used": 1000, "quota": 1000, "percent": 100, "upgradeUrl": "..." }
```

### `POST /api/audit/export`

Authenticated. Streams the tenant's audit trail (findings +
accept/dismiss decisions) as a JSON Lines response.

**Body**

```json
{ "since": "2026-01-01"?, "until": "2026-06-30"?, "format": "jsonl|csv" }
```

**Response 200:** `text/plain` stream. **403** if caller is a
viewer.

## Encounters

### `POST /api/encounters/search`

Search the tenant's encounter inbox.

**Body**

```json
{ "query": "string?", "flagged": "all|yes|no", "limit": 50, "cursor": "string?" }
```

**Response 200**

```json
{ "items": [{ "id": "string", "patientRef": "string", "date": "ISO8601", "flagged": true, "findingCount": 3 }], "nextCursor": "string?" }
```

### `POST /api/encounters/export`

Bulk export of encounters (de-identified) for offline review.

**Body:** same as `/api/audit/export`.

### `POST /api/encounters/{id}/findings/{findingId}/accept`

Accept a single finding. Writes a row to the audit chain.

**Body:** none.

**Response 200:** `{ ok: true, auditEventId: "string", signature: "string" }`

**Errors:** `404` (id not found), `409` (already terminal),
`403` (viewer).

### `POST /api/encounters/{id}/findings/{findingId}/dismiss`

Same as accept, but the new audit-trail entry is `dismissed` with
the supplied reason.

**Body**

```json
{ "reason": "string", "note": "string?" }
```

## Findings (bulk)

### `POST /api/findings/bulk/accept`

Accept many findings atomically.

**Body**

```json
{ "findingIds": ["string", "..."] }
```

**Response 200**

```json
{
  "ok": true,
  "bulkActionId": "string",
  "acceptedFindingIds": ["string", "..."],
  "perFinding": [{ "findingId": "string", "auditEventId": "string", "signature": "string" }]
}
```

**Errors:** `404` (any id not in tenant), `409` (any id already
terminal, with `already_terminal: [...]` listing the offenders).

### `POST /api/findings/bulk/dismiss`

Same shape, with reason + note per finding.

**Body**

```json
{ "findingIds": ["string", "..."], "reason": "string", "note": "string?" }
```

### `POST /api/findings/export`

Export findings across the tenant. Same body as
`/api/audit/export`.

## Settings

### `POST /api/settings/clinic-profile`

Update tenant clinic name, specialty, contact email.

**Body**

```json
{ "name": "string", "specialty": "string", "contactEmail": "email" }
```

### `POST /api/settings/region`

Change the tenant's data-residency region. **Triggers a tenant
re-provisioning job** — the change is not instant. Returns 202.

### `POST /api/settings/phi-redaction`

Toggle the PHI redaction layer (Tier 3 only). When on, all model
prompts pass through the redaction filter.

## Team

### `POST /api/team`

List the tenant's members.

**Response 200:** `[{ id, email, role: "owner|auditor|biller|viewer|integrator", addedAt }]`

### `POST /api/team/invite`

Invite a new member by email.

**Body**

```json
{ "email": "email", "role": "owner|auditor|biller|viewer|integrator" }
```

For `integrator` role, the response includes a one-time
`bearerToken` to use for API access.

### `POST /api/team/{membershipId}`

Update a member's role or revoke access.

### `POST /api/team/accept`

Accept a pending invitation token (from email link).

**Body:** `{ "token": "string" }`

## Billing

### `GET /api/billing/tiers`

Public. Returns the canonical tier definitions.

### `POST /api/billing/checkout`

Start a Stripe Checkout session for an upgrade.

**Body:** `{ "tier": "tier1|tier2|tier3", "billingCycle": "monthly|annual" }`

### `POST /api/billing/portal`

Returns a Stripe billing-portal URL for the active tenant.

### `POST /api/billing/portal-redirect`

Server-side redirect (302) to the Stripe portal.

### `GET /api/billing/subscription`

Returns the tenant's current subscription state.

### `POST /api/billing/change-tier`

Change tier with prorated billing. Requires `Idempotency-Key`.

### `POST /api/billing/cancel-subscription`

Cancel at end of period. Requires `Idempotency-Key`.

### `GET /api/billing/invoices`

List past invoices.

### `POST /api/billing/webhook`

**Stripe webhook receiver.** Authenticated via Stripe signing
secret, not a session. Configure in Stripe Dashboard with the
endpoint URL `https://portal.zorva.health/api/billing/webhook`.

Handled events: `checkout.session.completed`,
`customer.subscription.updated`,
`customer.subscription.deleted`, `invoice.paid`,
`invoice.payment_failed`.

## Webhooks (outbound)

Zorva emits the following outbound webhooks to URLs you configure
in Settings → Integrations:

- `audit.completed` — fired when an audit run finishes; payload
  includes `tenantId`, `encounterId`, `findingCount`.
- `billing.invoice.paid` — fired when Stripe confirms payment.

Payloads are signed with HMAC-SHA256 in the `X-Zorva-Signature`
header. Retries: 5 attempts with exponential backoff. See
[`WEBHOOK-EVENTS.md`](./WEBHOOK-EVENTS.md) for the full schema.

## Maintenance & cron

### `POST /api/maintenance`

Internal. Protected by a shared secret in the `X-Maintenance-Token`
header. Used by the weekly-digest cron job to flush stale data.
**Do not call from external integrations.**

### `POST /api/cron/weekly-digest`

Internal. Triggered by Vercel Cron. Sends the weekly summary
email to each tenant owner.

## Email

### `POST /api/email/webhook`

**Resend webhook receiver.** Handles delivery events. Configured
in Resend Dashboard.

### `POST /api/email/unsubscribe`

Public. One-click unsubscribe per RFC 8058.

## Onboarding

These endpoints are called by the `/onboarding` wizard and are not
generally useful for third-party integrators. They are documented
here for completeness:

- `POST /api/onboarding/state` — get the caller's onboarding progress.
- `POST /api/onboarding/clinic-profile` — step 1.
- `POST /api/onboarding/region` — step 2.
- `POST /api/onboarding/ehr` — step 3.
- `POST /api/onboarding/upload` — step 4 (file upload).
- `POST /api/onboarding/first-encounter` — step 5.
- `POST /api/onboarding/redeem` — apply an invite/referral code.
- `POST /api/onboarding/complete` — finalize.

## Status codes

| Code | Meaning |
|------|---------|
| 200 | Success. |
| 202 | Accepted, processing async (e.g. region change). |
| 400 | Malformed body / Zod validation failure. |
| 401 | Not signed in / no bearer token. |
| 402 | Quota exhausted. See `/api/audit/run`. |
| 403 | Signed in but missing capability (e.g. viewer hitting write). |
| 404 | Resource not found in active tenant. |
| 409 | Conflict — already-terminal state, or duplicate idempotency key. |
| 429 | Rate-limited. `Retry-After` header present. |
| 5xx | Server error. Safe to retry with backoff. |

## Rate limits

- 60 requests/minute per bearer token (tier 1).
- 300 requests/minute per bearer token (tier 2/3).
- `/api/audit/run` additionally throttled to 10/minute per tenant.

## Changelog

- **2026-06-25** — initial public reference, hand-curated from route
  files (no OpenAPI auto-gen yet).
- Future: an `openapi.json` will be auto-emitted at
  `/api/openapi.json` and linked from here.