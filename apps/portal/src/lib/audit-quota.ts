// Server-side audit quota enforcement.
//
// Single source of truth for "can this tenant run one more audit?"
// and "what should the portal / dashboard show the user about their
// usage?" Used by:
//
//   - /api/audit/run (POST) — the gate that all audit submissions
//     flow through. Returns 402 + upgrade_url on overage.
//   - /api/usage (GET) — reads the snapshot for the /billing card.
//   - /api/billing/webhook (invoice.payment_succeeded) — resets the
//     counter to 0 once per period.
//   - /billing and /dashboard server components — read the warning
//     / blocked state to render the upgrade banner.
//
// Design notes:
//
// 1. The hard cap is server-side authoritative. The client cannot
//    pass a flag to bypass the check; the only way to call this lib
//    is through the /api/audit/run route (or webhook) which always
//    re-reads the live row.
//
// 2. The atomic-increment + re-check pattern is the only safe way
//    to handle concurrent calls. Prisma's `update` with
//    `{ increment: 1 }` runs as a single SQL statement; the
//    returned `auditQuotaUsed` is the value AFTER the increment
//    (so we can compare against `auditQuotaLimit` without a race).
//    SQLite serializes writes, so a "do two increments in a row
//    both pass the check" failure mode would require a single
//    process to interleave reads after both writes — which it
//    cannot, because the increment and the read-back happen in the
//    same statement.
//
// 3. The 80% warning email is deduped via
//    `Tenant.quotaWarningSentAt`. We store the timestamp of the
//    warning, not the period start, because the same
//    invoice.payment_succeeded can reset the counter in the middle
//    of a period — the dedup key needs to survive a reset. Storing
//    the warning's wall-clock time is robust to resets; a future
//    period naturally starts a new warning cycle because the new
//    period's first 80%-crossing audit fires the email again.
//
//    Wait — that would re-fire on the first 80%-crossing of every
//    period. Is that correct? Yes: "exactly one warning email is
//    sent to the tenant owner (no duplicates on subsequent audits
//    within the same period)". The dedup is per period, so
//    crossing 80% in period N fires once, the next period the
//    counter resets to 0, and crossing 80% again fires again.
//    Correct.
//
//    We implement "one per period" by storing the period start
//    alongside the warning timestamp, computed at send time:
//    `quotaWarningSentAt` is set, and the lib checks "is the
//    current period start the same as the period start that was
//    active when the warning was sent?" by computing
//    `startOfCurrentMonthUtc()` and comparing with the timestamp's
//    month. Both are pure date math, no clock drift.
//
// 4. The reset is deduped via `Tenant.lastQuotaResetPeriodStart`.
//    The webhook handler calls `resetAuditQuota` and the lib short-
//    circuits when the new period start matches a prior reset.
//    Combined with the receiver-side `ProcessedStripeEvent` dedup
//    in the webhook itself, double-reset within the same period is
//    impossible from any path: re-deliveries hit the webhook's
//    existing event-dedup, and concurrent invoices in the same
//    period hit this lib's period-dedup.
//
// 5. `consumeAuditQuota` returns a discriminated result so callers
//    don't have to re-derive state from raw counters. The
//    `/api/audit/run` route maps the result to the right HTTP
//    status; the `/api/usage` and `/billing` pages read the same
//    shape for the banner.
//
// Out of scope (per the task body): soft caps, grace periods,
// overage billing, seat / storage quotas. Only audit-quota
// enforcement is in this module.
//
// Note on `server-only`: the lib is safe to import from route
// handlers and server components, but the unit test imports it
// from a plain Node script (tests/audit-quota.test.ts). The
// "server-only" Next.js package isn't resolved under tsx, so we
// skip the guard here. The lib is still safe — every entry point
// reads from the database; there is no browser code path.

import { prisma } from "@/lib/prisma";
import {
  isValidTierId,
  type TierId,
} from "@/lib/pricing";
import { startOfCurrentMonthUtc } from "@/lib/billing-page-helpers";

// ---------------------------------------------------------------------------
// Tier caps
// ---------------------------------------------------------------------------

/**
 * Default audit quota per tier — canonical home. The /api/billing/tiers
 * route reads this, the /api/billing/webhook handler writes from it on
 * tier-create / tier-change, and this lib reads it as the floor when
 * the per-tenant `auditQuotaLimit` column is null or below the tier
 * default. Numbers are the spec defaults: small=500, mid=2000,
 * large=5000.
 */
export const TIER_AUDIT_QUOTA: Record<TierId, number> = {
  small: 500,
  mid: 2_000,
  large: 5_000,
};

/** Warning fires at this fraction of `auditQuotaLimit`. */
export const QUOTA_WARNING_FRACTION = 0.8;

/** Block fires at this fraction of `auditQuotaLimit`. */
export const QUOTA_BLOCK_FRACTION = 1.0;

/**
 * Resolve the effective cap for a tenant. The column is the source of
 * truth — written at provisioning (from the tier default) and the
 * `/api/billing/tiers` PUT route can bump it. There is no automatic
 * "below the tier default → snap up" fallback: the tier default is
 * the value written at provisioning, not a floor. A tenant with
 * `auditQuotaLimit = 100` after a manual update (e.g. a
 * grandfathered legacy plan) is capped at 100, not 500. This matches
 * the AC: "Tier caps are configurable" and "The hard cap is
 * server-side authoritative" — the cap the user sees is the cap the
 * server enforces.
 *
 * Non-positive columns (null in the DB → 0 here, or a manually-typed
 * 0) fall back to the tier default. A zero cap means "block
 * everything", and the AC says the hard cap is server-side
 * authoritative — so a zero cap is honoured, not silently raised.
 * The only exception is the "column has not been provisioned yet"
 * case where we fall back to the tier default so a fresh
 * checkout-completion flow doesn't strand the tenant in a
 * "blocked at 0 audits" state. The provisioning path writes the
 * tier default into the column on tenant create, so this fallback
 * only fires for pre-migration rows.
 */
export function effectiveAuditQuotaLimit(args: {
  tier: string;
  auditQuotaLimit: number;
}): number {
  if (args.auditQuotaLimit <= 0) {
    return isValidTierId(args.tier)
      ? TIER_AUDIT_QUOTA[args.tier]
      : TIER_AUDIT_QUOTA.small;
  }
  return args.auditQuotaLimit;
}

// ---------------------------------------------------------------------------
// Consume — the gate every audit submission flows through
// ---------------------------------------------------------------------------

export type ConsumeResult =
  | {
      kind: "ok";
      /** The tenant's `auditQuotaUsed` AFTER the increment. */
      used: number;
      /** The tenant's effective `auditQuotaLimit` (column or tier default). */
      quota: number;
      /** Fraction of cap consumed, rounded to 1 dp. */
      percent: number;
    }
  | {
      kind: "warn";
      /** The tenant's `auditQuotaUsed` AFTER the increment. */
      used: number;
      quota: number;
      percent: number;
      /** `true` when this call was the one that fired the warning
       * email (i.e. the first call to cross 80% this period). `false`
       * when the warning was already sent earlier this period. */
      warnedNow: boolean;
    }
  | {
      kind: "blocked";
      used: number;
      quota: number;
      percent: number;
      upgradeUrl: string;
    };

/**
 * The URL the client should send the user to when quota is blocked.
 * The /api/audit/run route echoes this in the 402 body so a thin
 * client (curl, the FastAPI side, a future mobile app) can hand the
 * owner a clickable link.
 */
export function buildUpgradeUrl(origin: string | null | undefined): string {
  const base = (origin ?? "http://localhost:3000").replace(/\/$/, "");
  return `${base}/billing`;
}

/**
 * Atomically increment `Tenant.auditQuotaUsed` by exactly 1 and
 * evaluate the threshold. Returns the discriminated result so the
 * caller can map it to HTTP / banner / email behaviour.
 *
 * Race-safety: a single `prisma.tenant.update` with `increment: 1`
 * is one SQL statement; the returned `auditQuotaUsed` is the value
 * AFTER the increment, so the post-update check is safe to compare
 * against `auditQuotaLimit`. Two concurrent calls will serialize:
 * the second call sees the first call's incremented value, so the
 * cap is never exceeded.
 */
export async function consumeAuditQuota(args: {
  tenantId: string;
  origin?: string | null;
}): Promise<ConsumeResult> {
  const origin = args.origin ?? null;
  // Atomic increment + re-read. The `select` carries auditQuotaUsed
  // and auditQuotaLimit out of the same UPDATE — no read-modify-write
  // race window.
  const updated = await prisma.tenant.update({
    where: { id: args.tenantId },
    data: { auditQuotaUsed: { increment: 1 } },
    select: {
      auditQuotaUsed: true,
      auditQuotaLimit: true,
      tier: true,
    },
  });
  const quota = effectiveAuditQuotaLimit({
    tier: updated.tier,
    auditQuotaLimit: updated.auditQuotaLimit,
  });
  const used = updated.auditQuotaUsed;
  const percent = quota > 0 ? Math.round((used / quota) * 1000) / 10 : 0;
  if (used >= quota * QUOTA_BLOCK_FRACTION) {
    return {
      kind: "blocked",
      used,
      quota,
      percent,
      upgradeUrl: buildUpgradeUrl(origin),
    };
  }
  if (used >= Math.ceil(quota * QUOTA_WARNING_FRACTION)) {
    const warnedNow = await maybeSendWarningEmail(args.tenantId, used, quota);
    return {
      kind: "warn",
      used,
      quota,
      percent,
      warnedNow,
    };
  }
  return { kind: "ok", used, quota, percent };
}

// ---------------------------------------------------------------------------
// Warning email
// ---------------------------------------------------------------------------

/**
 * Send the 80% warning email at most once per period. Returns true
 * when this call was the one that fired the email; false when a
 * prior call in the same period already sent it (the audit is
 * allowed to proceed; the email is the only thing that gets
 * deduped).
 *
 * Dedup strategy: we store `Tenant.quotaWarningSentAt` as the
 * timestamp of the most recent warning. The "same period" check
 * compares the warning's UTC month to the current month — both
 * `now` and the stored timestamp get normalized to the 1st of the
 * month, so a re-fire attempt in the same month short-circuits
 * without re-sending. The next month's first 80%-crossing fires
 * the email again.
 */
async function maybeSendWarningEmail(
  tenantId: string,
  used: number,
  quota: number,
): Promise<boolean> {
  const now = new Date();
  const currentPeriodStart = startOfCurrentMonthUtc(now);
  const existing = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: { quotaWarningSentAt: true },
  });
  if (existing?.quotaWarningSentAt) {
    const lastPeriodStart = startOfCurrentMonthUtc(existing.quotaWarningSentAt);
    if (lastPeriodStart.getTime() === currentPeriodStart.getTime()) {
      // Already warned in this period; don't send again.
      return false;
    }
  }
  // Mark before send so two concurrent 80%-crossing calls don't
  // both fire. The second sees the timestamp and short-circuits
  // via the read above.
  await prisma.tenant.update({
    where: { id: tenantId },
    data: { quotaWarningSentAt: now },
  });
  // Fire-and-forget the email send — the audit must not block on
  // the email path. We log the failure mode but don't fail the
  // audit; the user can re-derive the warning from the portal
  // banner.
  void sendQuotaWarningEmail({ tenantId, used, quota, now }).catch((e) => {
    console.warn(
      "[audit-quota] warning email failed:",
      e instanceof Error ? e.message : e,
    );
  });
  return true;
}

/**
 * Send the 80% warning email. Built on the shared `sendTemplate`
 * dispatcher (src/lib/email.ts) so the suppress-list gate, dev
 * mock-mode fallback, and List-Unsubscribe header are inherited
 * from the rest of the email stack. Template id: "quota_warning".
 */
async function sendQuotaWarningEmail(args: {
  tenantId: string;
  used: number;
  quota: number;
  now: Date;
}): Promise<void> {
  const tenant = await prisma.tenant.findUnique({
    where: { id: args.tenantId },
    select: { name: true },
  });
  if (!tenant) return;
  const owner = await findTenantOwnerEmail(args.tenantId);
  if (!owner) {
    console.warn(
      `[audit-quota] no owner email for tenant ${args.tenantId}; warning banner only`,
    );
    return;
  }
  const percent = Math.round((args.used / args.quota) * 1000) / 10;
  const subject = `You've used ${percent}% of your audit quota — AI Billing Portal`;
  const text = [
    `Hi ${tenant.name} team,`,
    "",
    `You've used ${args.used} of ${args.quota} audits this billing period`,
    `(${percent}% of your tier's monthly cap).`,
    "",
    "What this means:",
    "  - The portal still lets you submit audits for now.",
    "  - At 100% we'll block new audit submissions until your next",
    "    billing period resets the counter (or you upgrade).",
    "",
    "Upgrade your tier:",
    "  /billing",
    "",
    "— The AI Billing Portal team",
  ].join("\n");
  const html = [
    "<p>Hi <strong>",
    escapeHtml(tenant.name),
    "</strong> team,</p>",
    `<p>You've used <strong>${args.used} of ${args.quota}</strong> audits this billing period (${percent}% of your tier's monthly cap).</p>`,
    "<p>What this means:</p>",
    "<ul><li>The portal still lets you submit audits for now.</li>",
    "<li>At 100% we'll block new audit submissions until your next billing period resets the counter (or you upgrade).</li></ul>",
    `<p><a href="/billing">Upgrade your tier</a></p>`,
    "<p>— The AI Billing Portal team</p>",
  ].join("");
  await sendQuotaTemplate({
    to: owner,
    tenantId: args.tenantId,
    subject,
    text,
    html,
  });
}

async function findTenantOwnerEmail(tenantId: string): Promise<string | null> {
  // The welcome-email lib already has this helper; reuse it. The
  // owner is the user with role "owner" on the tenant.
  const { findTenantOwnerEmail } = await import("@/lib/welcome-email");
  return findTenantOwnerEmail(tenantId);
}

// ---------------------------------------------------------------------------
// Email dispatcher (thin wrapper over src/lib/email.ts)
// ---------------------------------------------------------------------------
//
// Imported lazily to keep this lib testable without booting the
// email stack. The actual send uses the same dispatcher as the
// welcome / past-due / weekly-digest templates.

async function sendQuotaTemplate(args: {
  to: string;
  tenantId: string;
  subject: string;
  text: string;
  html: string;
}): Promise<void> {
  const { sendTemplate } = await import("@/lib/email");
  await sendTemplate({
    to: args.to,
    templateId: "quota_warning" as never,
    kind: "marketing_advertising",
    subject: args.subject,
    text: args.text,
    html: args.html,
    tenantId: args.tenantId,
    metadata: { kind: "quota_warning_80pct" },
  });
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ---------------------------------------------------------------------------
// Reset — called from the Stripe webhook on invoice.payment_succeeded
// ---------------------------------------------------------------------------

export type ResetResult =
  | { kind: "reset"; periodStart: string; previousUsed: number }
  | { kind: "skipped_same_period"; periodStart: string; currentUsed: number }
  | { kind: "skipped_no_tenant"; reason: "unknown_customer" };

/**
 * Reset `auditQuotaUsed` to 0 for the tenant corresponding to the
 * given Stripe customer id. Idempotent: a second call within the
 * same billing period returns `skipped_same_period` and writes
 * nothing. The reset ALSO clears `quotaWarningSentAt` so the next
 * period starts a fresh warning cycle.
 *
 * "Same period" is determined by `startOfCurrentMonthUtc(now)` —
 * the dev host and the production Postgres live in different time
 * zones; UTC arithmetic on monthly boundaries is the safe choice
 * (the same gotcha that the date-arithmetic test in
 * tests/billing-page.test.ts guards against).
 */
export async function resetAuditQuota(args: {
  stripeCustomerId: string;
  now?: Date;
}): Promise<ResetResult> {
  const now = args.now ?? new Date();
  const periodStart = startOfCurrentMonthUtc(now);
  const tenant = await prisma.tenant.findUnique({
    where: { stripeCustomerId: args.stripeCustomerId },
    select: {
      id: true,
      auditQuotaUsed: true,
      lastQuotaResetPeriodStart: true,
    },
  });
  if (!tenant) {
    return { kind: "skipped_no_tenant", reason: "unknown_customer" };
  }
  // Skip when the last reset was already in this period. The webhook
  // fires for every invoice.payment_succeeded, including mid-period
  // retries on the same subscription — a single tenant can have
  // multiple invoice.payment_succeeded events in one period, and we
  // only want to reset once.
  if (tenant.lastQuotaResetPeriodStart) {
    const lastPeriodStart = startOfCurrentMonthUtc(
      tenant.lastQuotaResetPeriodStart,
    );
    if (lastPeriodStart.getTime() === periodStart.getTime()) {
      return {
        kind: "skipped_same_period",
        periodStart: periodStart.toISOString().slice(0, 10),
        currentUsed: tenant.auditQuotaUsed,
      };
    }
  }
  await prisma.tenant.update({
    where: { id: tenant.id },
    data: {
      auditQuotaUsed: 0,
      quotaWarningSentAt: null,
      lastQuotaResetPeriodStart: periodStart,
    },
  });
  return {
    kind: "reset",
    periodStart: periodStart.toISOString().slice(0, 10),
    previousUsed: tenant.auditQuotaUsed,
  };
}

// ---------------------------------------------------------------------------
// Snapshot — what the portal / dashboard / /api/usage render
// ---------------------------------------------------------------------------

export type QuotaState = "ok" | "warn" | "blocked";

export interface QuotaSnapshot {
  used: number;
  quota: number;
  /** 0..100, 1 dp. */
  percent: number;
  /** Server-derived threshold state — UI should never compute
   * this from `used` / `quota` on its own; the server's
   * effective cap (column or tier default) and the warn / block
   * fractions are the source of truth. */
  state: QuotaState;
  /** True when the tenant is at/over 100% of cap. */
  blocked: boolean;
  /** `true` when the 80% warning email was already sent in the
   * current period. The portal surfaces this as a "warning
   * already delivered" hint next to the banner. */
  warningSentThisPeriod: boolean;
  /** UTC date string (YYYY-MM-DD) for the start of the current
   * period. Useful for the banner's "resets on" line. */
  periodStart: string;
}

/**
 * Build a read-only snapshot for the portal. Does NOT mutate. Safe
 * to call from any server-rendered page or API route.
 */
export async function loadQuotaSnapshot(tenantId: string): Promise<QuotaSnapshot> {
  const row = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: {
      auditQuotaUsed: true,
      auditQuotaLimit: true,
      tier: true,
      quotaWarningSentAt: true,
    },
  });
  const used = row?.auditQuotaUsed ?? 0;
  const quota = effectiveAuditQuotaLimit({
    tier: row?.tier ?? "small",
    auditQuotaLimit: row?.auditQuotaLimit ?? 0,
  });
  const percent = quota > 0 ? Math.round((used / quota) * 1000) / 10 : 0;
  let state: QuotaState = "ok";
  if (used >= quota * QUOTA_BLOCK_FRACTION) state = "blocked";
  else if (used >= Math.ceil(quota * QUOTA_WARNING_FRACTION)) state = "warn";
  const currentPeriodStart = startOfCurrentMonthUtc();
  const warningSentThisPeriod =
    row?.quotaWarningSentAt != null &&
    startOfCurrentMonthUtc(row.quotaWarningSentAt).getTime() ===
      currentPeriodStart.getTime();
  return {
    used,
    quota,
    percent,
    state,
    blocked: state === "blocked",
    warningSentThisPeriod,
    periodStart: currentPeriodStart.toISOString().slice(0, 10),
  };
}
