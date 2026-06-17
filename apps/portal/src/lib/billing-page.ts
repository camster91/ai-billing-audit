// Server-side helpers for the client-facing /billing page.
//
// Three sections: current plan + next invoice date, monthly usage
// against quota, and invoice history. The page is server-rendered
// (faster first paint, no client fetch waterfall), but the action
// buttons (update payment, change tier, cancel) are client
// components that POST to dedicated route handlers — see
// src/app/api/billing/change-tier/route.ts and
// src/app/api/billing/cancel-subscription/route.ts.
//
// The page talks to Stripe directly from the server runtime so
// the secret key never reaches the browser. In demo mode
// (STRIPE_SECRET_KEY missing / "***") we fall back to a
// deterministic stub response shape so the UI is exercisable in
// dev without leaking test keys.
//
// The 12-month invoice window is read from the local Invoice
// table (populated by the webhook handler on
// invoice.payment_succeeded). In non-demo mode we also pull the
// live Stripe list so any recently-created invoice that hasn't
// been webhooked yet still shows up. The merge is deduplicated
// by stripeInvoiceId.
//
// All money is integer cents; formatting is the caller's job.
// The pure formatting + date helpers live in
// billing-page-helpers.ts so they're testable without dragging
// in the server-only "server-only" module guard.

import "server-only";

import type StripeNS from "stripe";
import { prisma } from "@/lib/prisma";
import { getStripe, isDemoMode } from "@/lib/stripe";
import { getPricingConfig, isValidTierId, type TierId } from "@/lib/pricing";
import {
  formatCents,
  startOfCurrentMonthUtc,
  startOfInvoiceWindowUtc,
} from "@/lib/billing-page-helpers";

// Re-export the pure helpers so the /billing page only needs to
// import from one place. They are also imported directly by
// tests/billing-page.test.ts to keep the test off the
// server-only module graph.
export { formatCents, startOfCurrentMonthUtc, startOfInvoiceWindowUtc };
export { getPricingConfig, isValidTierId };
export type { TierId };

// ---------------------------------------------------------------------------
// Quota
// ---------------------------------------------------------------------------

export interface UsageSnapshot {
  /** Audits consumed in the current billing period (lives on Tenant.auditQuotaUsed). */
  used: number;
  /** Cap for the current tier (Tenant.auditQuotaLimit, defaulted from TIER_AUDIT_QUOTA at provisioning). */
  quota: number;
  /** 0..100 (rounded to 1 dp). */
  percent: number;
  /** ISO date string (YYYY-MM-DD) for the start of the current period. */
  periodStart: string;
  /** ISO date string for the start of the next period (i.e. when the quota resets). */
  resetsAt: string;
}

export async function loadUsageSnapshot(tenantId: string): Promise<UsageSnapshot> {
  const row = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: { auditQuotaUsed: true, auditQuotaLimit: true },
  });
  const used = row?.auditQuotaUsed ?? 0;
  const quota = row?.auditQuotaLimit ?? 0;
  // Safe arithmetic: percent = 0 when quota is 0 to avoid NaN/Infinity.
  const percent =
    quota > 0 ? Math.round(((used / quota) * 100) * 10) / 10 : 0;
  const start = startOfCurrentMonthUtc();
  // Resets on the 1st of the next month.
  const resets = new Date(
    Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1),
  );
  return {
    used,
    quota,
    percent,
    periodStart: start.toISOString().slice(0, 10),
    resetsAt: resets.toISOString().slice(0, 10),
  };
}

// ---------------------------------------------------------------------------
// Subscription
// ---------------------------------------------------------------------------

export interface SubscriptionSnapshot {
  /** "small" | "mid" | "large" — null when the tenant has no Stripe linkage. */
  tier: TierId | null;
  /** Mirror of Tenant.subscriptionStatus. */
  status: string;
  /** ISO date string for the next invoice, or null when unknown. */
  nextInvoiceAt: string | null;
  /** Whether the response was served from the demo stub. */
  demo: boolean;
  /** Human-readable next-invoice amount + currency, when known. */
  nextInvoiceAmount: string | null;
  /**
   * If the tenant has no Stripe customer yet (i.e. signed up
   * manually, no Checkout ever completed), we still surface the
   * tier from the local row so the page doesn't render an empty
   * card. `hasStripeCustomer` lets the page decide whether to
   * show a "complete checkout" CTA vs. the "update payment
   * method" action.
   */
  hasStripeCustomer: boolean;
}

async function loadSubscriptionFromStripe(
  stripeCustomerId: string,
  stripeSubscriptionId: string | null,
): Promise<Partial<SubscriptionSnapshot>> {
  const stripe = getStripe();
  // The Subscription object is the source of truth for next
  // invoice timing. We look it up by id
  // (Tenant.stripeSubscriptionId) and fall back to the
  // customer's first active sub when the id is missing
  // (between Checkout completion and the first
  // subscription.created event landing).
  let sub: StripeNS.Subscription | null = null;
  if (stripeSubscriptionId) {
    try {
      sub = await stripe.subscriptions.retrieve(stripeSubscriptionId);
    } catch (e) {
      console.warn(
        "[billing-page] stripe.subscriptions.retrieve failed:",
        e instanceof Error ? e.message : e,
      );
    }
  }
  if (!sub) {
    const list = await stripe.subscriptions.list({
      customer: stripeCustomerId,
      status: "all",
      limit: 1,
    });
    sub = list.data[0] ?? null;
  }
  if (!sub) return {};
  // Stripe stores the period end on the first line item in API
  // version 2026-05-27+. Older payloads expose current_period_end
  // on the subscription object itself — read both, prefer the
  // line item value.
  const firstItem = sub.items?.data?.[0];
  const periodEndUnix =
    firstItem && typeof firstItem.current_period_end === "number"
      ? firstItem.current_period_end
      : typeof (sub as unknown as { current_period_end?: number })
          .current_period_end === "number"
        ? (sub as unknown as { current_period_end: number })
            .current_period_end
        : null;
  const nextInvoiceAt =
    periodEndUnix !== null
      ? new Date(periodEndUnix * 1000).toISOString()
      : null;
  // Amount + currency for the next invoice. The first line item
  // holds the unit price in cents; we surface it as a
  // pre-formatted "$1,499" string so the page doesn't need to
  // know about currency formatting rules.
  let nextInvoiceAmount: string | null = null;
  if (firstItem?.price?.unit_amount !== null && firstItem?.price?.unit_amount !== undefined) {
    const cents = firstItem.price.unit_amount;
    const currency = (firstItem.price.currency ?? "usd").toUpperCase();
    nextInvoiceAmount = formatCents(cents, currency);
  }
  return { nextInvoiceAt, nextInvoiceAmount };
}

export async function loadSubscriptionSnapshot(
  tenantId: string,
): Promise<SubscriptionSnapshot> {
  const row = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: {
      tier: true,
      subscriptionStatus: true,
      stripeCustomerId: true,
      stripeSubscriptionId: true,
    },
  });
  const tier: TierId | null =
    row && isValidTierId(row.tier) ? row.tier : null;
  const status = row?.subscriptionStatus ?? "active";
  const hasStripeCustomer = Boolean(row?.stripeCustomerId);
  if (!hasStripeCustomer || isDemoMode()) {
    return {
      tier,
      status,
      nextInvoiceAt: null,
      nextInvoiceAmount: null,
      demo: isDemoMode(),
      hasStripeCustomer,
    };
  }
  try {
    const live = await loadSubscriptionFromStripe(
      row!.stripeCustomerId!,
      row!.stripeSubscriptionId ?? null,
    );
    return {
      tier,
      status,
      nextInvoiceAt: live.nextInvoiceAt ?? null,
      nextInvoiceAmount: live.nextInvoiceAmount ?? null,
      demo: false,
      hasStripeCustomer: true,
    };
  } catch (e) {
    console.warn(
      "[billing-page] failed to load live subscription:",
      e instanceof Error ? e.message : e,
    );
    // Fall through to the local-only view so the page is still
    // functional when Stripe is down. The status string on the
    // tenant row is the most-recent webhook snapshot — close
    // enough.
    return {
      tier,
      status,
      nextInvoiceAt: null,
      nextInvoiceAmount: null,
      demo: false,
      hasStripeCustomer: true,
    };
  }
}

// ---------------------------------------------------------------------------
// Invoices
// ---------------------------------------------------------------------------

export interface InvoiceView {
  /** Stripe invoice id (in_xxx) or a synthetic demo id for fixtures. */
  id: string;
  /** ISO date string for the invoice's created/period-start timestamp. */
  date: string;
  /** Pre-formatted "$1,499 CAD" / "$1,109 USD" string. */
  amount: string;
  /** "paid" | "open" | "void" | "uncollectible" | "draft" | "past_due" ... */
  status: string;
  /** External URL the user can click to view / download the PDF. */
  hostedUrl: string | null;
  /** PDF download URL (Stripe-hosted). Same as hostedUrl on Stripe. */
  pdfUrl: string | null;
  /** True for invoices served from the local DB; false for live Stripe-only rows. */
  fromCache: boolean;
}

function normalizeInvoice(
  raw: StripeNS.Invoice,
  fromCache: boolean,
): InvoiceView {
  const cents =
    typeof raw.amount_paid === "number" && raw.amount_paid > 0
      ? raw.amount_paid
      : typeof raw.amount_due === "number"
        ? raw.amount_due
        : 0;
  const currency = raw.currency ?? "usd";
  // Stripe exposes three timestamp candidates — created (when
  // the invoice was created), period_start, and effective_at.
  // The billing page shows the invoice date (when the bill was
  // issued), so prefer created.
  const unix =
    typeof raw.created === "number"
      ? raw.created
      : typeof raw.period_start === "number"
        ? raw.period_start
        : Math.floor(Date.now() / 1000);
  return {
    id: raw.id ?? `unknown_${unix}`,
    date: new Date(unix * 1000).toISOString().slice(0, 10),
    amount: formatCents(cents, currency),
    status: raw.status ?? "unknown",
    hostedUrl: raw.hosted_invoice_url ?? null,
    pdfUrl: raw.invoice_pdf ?? null,
    fromCache,
  };
}

function cachedInvoiceToView(row: {
  stripeInvoiceId: string;
  amountCents: number;
  currency: string;
  status: string;
  createdAt: Date;
  payloadJson: string;
}): InvoiceView {
  let hostedUrl: string | null = null;
  let pdfUrl: string | null = null;
  // The webhook stored the full payload — try to surface the
  // hosted URLs. If the parse fails (e.g. a row was written
  // with a truncated payload in an old run), the row still
  // renders as a date + amount + status, just without a link.
  try {
    const payload = JSON.parse(row.payloadJson);
    hostedUrl = payload.hosted_invoice_url ?? null;
    pdfUrl = payload.invoice_pdf ?? null;
  } catch {
    // ignore — render without link
  }
  return {
    id: row.stripeInvoiceId,
    date: row.createdAt.toISOString().slice(0, 10),
    amount: formatCents(row.amountCents, row.currency),
    status: row.status,
    hostedUrl,
    pdfUrl,
    fromCache: true,
  };
}

/**
 * Returns the last 12 months of invoices for a tenant. The
 * local DB is the source of truth (it's been kept up-to-date by
 * the webhook handler since the first invoice paid). In
 * non-demo mode we top up with the live Stripe list so a
 * recently-created invoice that's still in flight also shows
 * up.
 */
export async function loadInvoiceHistory(
  tenantId: string,
): Promise<InvoiceView[]> {
  const tenant = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: { stripeCustomerId: true },
  });
  if (!tenant?.stripeCustomerId) return [];
  const windowStart = startOfInvoiceWindowUtc();
  // Local DB rows.
  const cached = await prisma.invoice.findMany({
    where: {
      tenantId,
      createdAt: { gte: windowStart },
    },
    orderBy: { createdAt: "desc" },
  });
  const views = cached.map(cachedInvoiceToView);
  const seenIds = new Set(views.map((v) => v.id));
  if (isDemoMode()) {
    return views;
  }
  // Live Stripe top-up: any invoice Stripe knows about that
  // hasn't been written to our DB yet (e.g. created within the
  // last few seconds, before the webhook lands). Capped at 24
  // rows so a tenant with a long history doesn't pay for an
  // unbounded list call.
  try {
    const stripe = getStripe();
    const list = await stripe.invoices.list({
      customer: tenant.stripeCustomerId,
      limit: 24,
    });
    for (const inv of list.data) {
      if (!inv.id || seenIds.has(inv.id)) continue;
      views.push(normalizeInvoice(inv, false));
    }
  } catch (e) {
    console.warn(
      "[billing-page] stripe.invoices.list failed:",
      e instanceof Error ? e.message : e,
    );
    // Swallow — the cached list is still useful on its own.
  }
  // Sort newest-first by ISO date (good enough for YYYY-MM-DD).
  views.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
  return views;
}
