// POST /api/billing/webhook
//
// Receives Stripe events. Verifies the signature against
// STRIPE_WEBHOOK_SECRET, then handles the events that matter for tenant
// provisioning and lifecycle:
//
//   checkout.session.completed            → upsert tenant from session
//   customer.subscription.created         → find/create tenant; set
//                                            subscriptionStatus=active
//                                            + tier from price id
//   customer.subscription.updated         → sync tier + status
//   customer.subscription.deleted         → set canceled + schedule
//                                            30-day purge
//   invoice.payment_succeeded             → upsert Invoice row
//   invoice.payment_failed                → record failure; if the
//                                            streak is older than 3
//                                            days, transition to
//                                            past_due and email owner
//
// Next.js 16 App Router hands us the raw request body via request.text(),
// so the Stripe `constructEvent` signature check works without any
// `bodyParser` shim (unlike Pages Router or Express). Verified against
// the Next.js route.ts docs in node_modules.
//
// Idempotency: receiver-side dedup via the ProcessedStripeEvent table.
// Every accepted event inserts (eventId, type, receivedAt, tenantId);
// a duplicate delivery hits the unique index on eventId and the
// handler short-circuits with a 200 ack. Outbound writes — when this
// app eventually pushes back to Stripe (e.g. canceling a subscription
// from the owner UI) — must use Stripe's idempotency-key API. We do
// not write to Stripe from this handler today, so the
// "every outbound write uses an idempotency key" rule is vacuously
// satisfied; documented here so the next person to add an outbound
// write doesn't forget it.

import type StripeNS from "stripe";
import { prisma } from "@/lib/prisma";
import { getStripe, getWebhookSecret, isDemoMode } from "@/lib/stripe";
import { isValidTierId, type TierId } from "@/lib/pricing";
import {
  CANCELED_TENANT_RETENTION_DAYS,
  PAYMENT_FAILURE_GRACE_DAYS,
  TIER_AUDIT_QUOTA,
  mapSubscriptionStatus,
  resolveTierFromSubscription,
  shouldSendPastDueEmail,
  uniqueSlug,
} from "@/lib/billing-webhook";
import {
  isBillingEmailMockMode,
  sendPastDueEmail,
} from "@/lib/billing-email";

export const runtime = "nodejs";
// Webhooks must run on every request — no caching.
export const dynamic = "force-dynamic";

interface CheckoutSessionMetadata {
  tierId?: string;
  currency?: string;
  tenantName?: string;
}

// ---------------------------------------------------------------------------
// Tenant upsert from a customer.subscription event. The shape is shared by
// checkout.session.completed (which has a Checkout Session with customer +
// subscription ids + metadata) and customer.subscription.created (which
// has a Subscription with a customer id + line items, but no metadata).
// We pass an optional `tierHint` and `nameHint` so the checkout path can
// pass through the metadata; the subscription path falls back to
// price-id resolution for tier and the customer email for the name.
// ---------------------------------------------------------------------------

async function upsertTenantFromSubscription(args: {
  customerId: string;
  subscriptionId: string;
  subscriptionStatus: StripeNS.Subscription["status"];
  tierHint?: TierId | null;
  nameHint?: string | null;
  customerEmail?: string | null;
}): Promise<{ created: boolean; tenantId: string }> {
  const status = mapSubscriptionStatus(args.subscriptionStatus);
  const tier: TierId =
    args.tierHint && isValidTierId(args.tierHint) ? args.tierHint : "small";

  // Name resolution: explicit hint → email local-part → last-6 of customer id.
  const tenantName =
    (typeof args.nameHint === "string" && args.nameHint.trim().length > 0
      ? args.nameHint.trim()
      : null) ??
    (typeof args.customerEmail === "string"
      ? args.customerEmail.split("@")[0]
      : null) ??
    `Clinic ${args.customerId.slice(-6)}`;

  const existing = await prisma.tenant.findUnique({
    where: { stripeCustomerId: args.customerId },
  });

  // For the create path we need a unique slug. For the update path we
  // leave the slug alone — it was set on creation and a re-subscription
  // shouldn't change the URL namespace.
  if (existing) {
    const updated = await prisma.tenant.update({
      where: { id: existing.id },
      data: {
        stripeSubscriptionId: args.subscriptionId,
        subscriptionStatus: status,
        tier,
      },
    });
    return { created: false, tenantId: updated.id };
  }

  const slug = await uniqueSlug(tenantName, async (candidate) => {
    const clash = await prisma.tenant.findUnique({ where: { slug: candidate } });
    return clash !== null;
  });
  const created = await prisma.tenant.create({
    data: {
      name: tenantName,
      slug,
      tier,
      subscriptionStatus: status,
      stripeCustomerId: args.customerId,
      stripeSubscriptionId: args.subscriptionId,
      // Audit-quota cap is tier-driven; the value lives here (and not in
      // src/lib/tenant.ts) so the webhook handler is the single writer
      // of caps-from-Stripe.
      auditQuotaLimit: TIER_AUDIT_QUOTA[tier],
    },
  });
  return { created: true, tenantId: created.id };
}

async function upsertTenantFromSession(
  session: StripeNS.Checkout.Session,
): Promise<{ created: boolean; tenantId: string }> {
  if (!session.customer || typeof session.customer !== "string") {
    throw new Error("checkout.session.completed without a string customer id");
  }
  if (!session.subscription || typeof session.subscription !== "string") {
    throw new Error("checkout.session.completed without a string subscription id");
  }
  const metadata = (session.metadata ?? {}) as CheckoutSessionMetadata;
  const tierHint = isValidTierId(metadata.tierId) ? metadata.tierId : null;
  return upsertTenantFromSubscription({
    customerId: session.customer,
    subscriptionId: session.subscription,
    subscriptionStatus: "active",
    tierHint,
    nameHint: metadata.tenantName ?? null,
    customerEmail: session.customer_details?.email ?? null,
  });
}

async function handleSubscriptionCreated(
  sub: StripeNS.Subscription,
  eventId: string,
): Promise<{ tenantId: string | null; created: boolean }> {
  const customerId = typeof sub.customer === "string" ? sub.customer : null;
  if (!customerId) {
    console.warn(
      `[/api/billing/webhook] ${eventId} subscription.created without string customer id; skipping`,
    );
    return { tenantId: null, created: false };
  }
  // Resolve tier from line items; this is the canonical "Stripe just
  // created a new sub" path so we trust the price id over any
  // previously-stored tier.
  const tierHint = resolveTierFromSubscription(sub);
  // The Subscription object doesn't carry the customer email directly.
  // We pull it from the customer on demand — fall through to the
  // last-6-of-customer-id name if Stripe's customer object has no
  // email. The cost of the extra round-trip is one HTTP call per
  // subscription lifecycle event, which Stripe limits to a handful
  // per subscription month.
  let customerEmail: string | null = null;
  try {
    const customer = await getStripe().customers.retrieve(customerId);
    if (!("deleted" in customer) || !customer.deleted) {
      customerEmail = (customer as StripeNS.Customer).email ?? null;
    }
  } catch (e) {
    console.warn(
      `[/api/billing/webhook] customer.retrieve(${customerId}) failed:`,
      e instanceof Error ? e.message : e,
    );
  }
  const result = await upsertTenantFromSubscription({
    customerId,
    subscriptionId: sub.id,
    subscriptionStatus: sub.status,
    tierHint,
    customerEmail,
  });
  return { tenantId: result.tenantId, created: result.created };
}

async function handleSubscriptionUpdated(
  sub: StripeNS.Subscription,
): Promise<{ tenantId: string | null; status: string; tier: string | null }> {
  const customerId = typeof sub.customer === "string" ? sub.customer : null;
  if (!customerId) {
    return { tenantId: null, status: "skipped", tier: null };
  }
  const tenant = await prisma.tenant.findUnique({
    where: { stripeCustomerId: customerId },
  });
  if (!tenant) {
    console.warn(
      `[/api/billing/webhook] subscription.updated for unknown customer ${customerId}; will be picked up on next created event`,
    );
    return { tenantId: null, status: "unknown_customer", tier: null };
  }
  const status = mapSubscriptionStatus(sub.status);
  const resolvedTier = resolveTierFromSubscription(sub);
  // Only update tier when we can resolve it; an unresolved tier
  // (e.g. Stripe sent a price id we don't know about) should leave
  // the existing tier intact rather than wipe it.
  const newTier =
    resolvedTier && isValidTierId(resolvedTier) ? resolvedTier : tenant.tier;
  const capChanged = newTier !== tenant.tier;
  const updated = await prisma.tenant.update({
    where: { id: tenant.id },
    data: {
      stripeSubscriptionId: sub.id,
      subscriptionStatus: status,
      tier: newTier,
      ...(capChanged ? { auditQuotaLimit: TIER_AUDIT_QUOTA[newTier as TierId] } : {}),
      // A successful update means payment is flowing again — clear
      // any payment-failure streak.
      firstPaymentFailureAt: null,
      lastPaymentFailureAt: null,
    },
  });
  return { tenantId: updated.id, status: updated.subscriptionStatus, tier: updated.tier };
}

async function handleSubscriptionDeleted(
  sub: StripeNS.Subscription,
): Promise<{ tenantId: string | null; purgeAt: string | null }> {
  const customerId = typeof sub.customer === "string" ? sub.customer : null;
  if (!customerId) {
    return { tenantId: null, purgeAt: null };
  }
  const tenant = await prisma.tenant.findUnique({
    where: { stripeCustomerId: customerId },
  });
  if (!tenant) {
    return { tenantId: null, purgeAt: null };
  }
  const now = new Date();
  const purgeAt = new Date(
    now.getTime() + CANCELED_TENANT_RETENTION_DAYS * 24 * 60 * 60 * 1000,
  );
  const updated = await prisma.tenant.update({
    where: { id: tenant.id },
    data: {
      subscriptionStatus: "canceled",
      canceledAt: now,
    },
  });
  // We don't run the purge here — the route must return quickly so
  // Stripe doesn't retry. The actual deletion is handled by
  // scripts/purge-canceled-tenants.ts on a daily cron. Returning
  // the computed purgeAt so logs and the future /billing admin view
  // can surface "your data will be deleted on YYYY-MM-DD".
  return { tenantId: updated.id, purgeAt: purgeAt.toISOString() };
}

// ---------------------------------------------------------------------------
// Invoice.subscription accessor.
//
// In Stripe API version 2026-05-27 (dahlia) the top-level `subscription`
// field was retired; the subscription id now lives at
// `parent.subscription_details.subscription`. We centralize the
// accessor so the handler doesn't care which API version a given
// payload came from — older payloads (e.g. a queued test event from
// a previous deploy) will still resolve cleanly via the legacy
// top-level field, new payloads via the parent.* path.
// ---------------------------------------------------------------------------

function extractInvoiceSubscriptionId(
  invoice: StripeNS.Invoice,
): string | null {
  // New shape (2026-05-27+): parent.subscription_details.subscription.
  const parent = (invoice as unknown as { parent?: { subscription_details?: { subscription?: string | null } | null } | null }).parent;
  if (parent?.subscription_details?.subscription) {
    return parent.subscription_details.subscription;
  }
  // Legacy shape: top-level subscription (string or expandable object).
  const legacy = (invoice as unknown as { subscription?: string | { id: string } | null }).subscription;
  if (typeof legacy === "string" && legacy.length > 0) return legacy;
  if (legacy && typeof legacy === "object" && typeof legacy.id === "string") {
    return legacy.id;
  }
  return null;
}

async function handleInvoicePaymentSucceeded(
  invoice: StripeNS.Invoice,
  eventId: string,
): Promise<{ tenantId: string | null; invoiceId: string }> {
  const customerId =
    typeof invoice.customer === "string"
      ? invoice.customer
      : invoice.customer && typeof invoice.customer === "object"
        ? invoice.customer.id
        : null;
  if (!customerId) {
    return { tenantId: null, invoiceId: invoice.id ?? "unknown" };
  }
  const tenant = await prisma.tenant.findUnique({
    where: { stripeCustomerId: customerId },
  });
  if (!tenant) {
    console.warn(
      `[/api/billing/webhook] invoice.payment_succeeded for unknown customer ${customerId}; skipping`,
    );
    return { tenantId: null, invoiceId: invoice.id ?? "unknown" };
  }
  // The Subscription id on an Invoice is at parent.subscription_details.subscription
  // in API version 2026-05-27 (dahlia). The top-level `subscription` field
  // was retired when the new parent object was introduced.
  const stripeSubscriptionId = extractInvoiceSubscriptionId(invoice);
  const amountCents =
    typeof invoice.amount_paid === "number"
      ? invoice.amount_paid
      : typeof invoice.amount_due === "number"
        ? invoice.amount_due
        : 0;
  // upsert by stripeInvoiceId — the unique index dedupes re-deliveries
  // even when the dedup-row check above has somehow been bypassed
  // (e.g. a row was manually deleted from ProcessedStripeEvent).
  await prisma.invoice.upsert({
    where: { stripeInvoiceId: invoice.id ?? `unknown_${eventId}` },
    create: {
      stripeInvoiceId: invoice.id ?? `unknown_${eventId}`,
      stripeCustomerId: customerId,
      tenantId: tenant.id,
      stripeSubscriptionId,
      status: invoice.status ?? "paid",
      amountCents,
      currency: (invoice.currency ?? "usd").toLowerCase(),
      payloadJson: JSON.stringify(invoice),
      createdFromEventId: eventId,
    },
    update: {
      // If Stripe re-sends the same event with a status update (e.g.
      // paid → paid), overwrite the snapshot. The createdFromEventId
      // intentionally stays at the original creator so forensics can
      // see which event produced the row.
      status: invoice.status ?? "paid",
      amountCents,
      payloadJson: JSON.stringify(invoice),
    },
  });
  // A successful payment clears any in-flight payment-failure
  // streak. We do this on the invoice event (not on the subscription
  // updated event) so a subscription that's "active" because of a
  // retry still flips back to "active" if the eventual payment
  // succeeds.
  await prisma.tenant.update({
    where: { id: tenant.id },
    data: {
      firstPaymentFailureAt: null,
      lastPaymentFailureAt: null,
      // Also ensure the status is active — a successful payment means
      // we're not past_due any more, even if Stripe's next
      // subscription.updated event hasn't landed yet.
      ...(tenant.subscriptionStatus === "past_due"
        ? { subscriptionStatus: "active" }
        : {}),
    },
  });
  return { tenantId: tenant.id, invoiceId: invoice.id ?? "unknown" };
}

async function handleInvoicePaymentFailed(
  invoice: StripeNS.Invoice,
): Promise<{
  tenantId: string | null;
  transitioned: boolean;
  emailed: boolean;
  reason: string;
}> {
  const customerId =
    typeof invoice.customer === "string"
      ? invoice.customer
      : invoice.customer && typeof invoice.customer === "object"
        ? invoice.customer.id
        : null;
  if (!customerId) {
    return {
      tenantId: null,
      transitioned: false,
      emailed: false,
      reason: "no_customer",
    };
  }
  const tenant = await prisma.tenant.findUnique({
    where: { stripeCustomerId: customerId },
  });
  if (!tenant) {
    return {
      tenantId: null,
      transitioned: false,
      emailed: false,
      reason: "unknown_customer",
    };
  }
  const now = new Date();
  const wasFirstFailure = tenant.firstPaymentFailureAt === null;
  // Set first failure timestamp on the first failure in the streak;
  // otherwise leave it alone (it's the anchor for the 3-day window).
  const firstPaymentFailureAt = wasFirstFailure
    ? now
    : tenant.firstPaymentFailureAt;
  // Always update last-failure timestamp so the email + dashboard
  // can show "we last tried X".
  await prisma.tenant.update({
    where: { id: tenant.id },
    data: {
      firstPaymentFailureAt,
      lastPaymentFailureAt: now,
    },
  });
  // Decide whether to transition + email. Both are gated on the 3-day
  // window AND the tenant not already being past_due (idempotent: a
  // second failure in the same past_due window doesn't re-send the
  // email).
  const transitionedAlready = tenant.subscriptionStatus === "past_due";
  const shouldTransition =
    !transitionedAlready &&
    firstPaymentFailureAt !== null &&
    shouldSendPastDueEmail({
      firstFailureAt: firstPaymentFailureAt,
      alreadyNotified: transitionedAlready,
      now,
    });
  if (!shouldTransition) {
    return {
      tenantId: tenant.id,
      transitioned: false,
      emailed: false,
      reason: "within_grace_window",
    };
  }
  await prisma.tenant.update({
    where: { id: tenant.id },
    data: { subscriptionStatus: "past_due" },
  });
  // Look up the owner email. The welcome-email lib already has the
  // helper; reuse it.
  const { findTenantOwnerEmail } = await import("@/lib/welcome-email");
  const ownerEmail = await findTenantOwnerEmail(tenant.id);
  if (!ownerEmail) {
    console.warn(
      `[/api/billing/webhook] past_due transition for tenant ${tenant.id} but no owner email; status flipped without notification`,
    );
    return {
      tenantId: tenant.id,
      transitioned: true,
      emailed: false,
      reason: "no_owner_email",
    };
  }
  // Failure count is the time span between first and last — a
  // reasonable proxy for "how many times did we retry". Stripe
  // doesn't include a count on the invoice event itself.
  const failureCountMs = now.getTime() - firstPaymentFailureAt.getTime();
  const failureCount = Math.max(
    1,
    Math.min(8, Math.ceil(failureCountMs / (12 * 60 * 60 * 1000))),
  );
  const amountCents =
    typeof invoice.amount_due === "number"
      ? invoice.amount_due
      : typeof invoice.amount_paid === "number"
        ? invoice.amount_paid
        : 0;
  const result = await sendPastDueEmail({
    to: ownerEmail,
    tenantName: tenant.name,
    firstFailureAt: firstPaymentFailureAt,
    lastFailureAt: now,
    failureCount,
    currency: invoice.currency ?? "usd",
    amountCents,
  });
  return {
    tenantId: tenant.id,
    transitioned: true,
    emailed: result.sent,
    reason: result.sent
      ? "notified"
      : isBillingEmailMockMode()
        ? "notified_mock"
        : (result.error ?? "email_failed"),
  };
}

// ---------------------------------------------------------------------------
// Receiver-side dedup.
//
// Try to insert a ProcessedStripeEvent row; on a unique-constraint
// violation (P2002), return null to signal "duplicate, ack-and-skip".
// We do this before the handler runs so a retried event doesn't
// re-execute the side effect (another tenant write, another email).
// ---------------------------------------------------------------------------

async function markEventSeen(
  event: StripeNS.Event,
  tenantId: string | null,
): Promise<{ alreadySeen: boolean; processedId: string | null }> {
  try {
    const row = await prisma.processedStripeEvent.create({
      data: {
        eventId: event.id,
        type: event.type,
        tenantId,
      },
      select: { id: true },
    });
    return { alreadySeen: false, processedId: row.id };
  } catch (e) {
    // P2002 = unique-constraint violation on the eventId unique index.
    // Anything else is a real DB error and should propagate.
    if (e && typeof e === "object" && "code" in e && (e as { code?: string }).code === "P2002") {
      return { alreadySeen: true, processedId: null };
    }
    throw e;
  }
}

export async function POST(request: Request) {
  if (isDemoMode()) {
    return new Response(
      "Stripe is in demo mode. Webhook refuses to process events without STRIPE_WEBHOOK_SECRET configured.",
      { status: 503 },
    );
  }

  const signature = request.headers.get("stripe-signature");
  if (!signature) {
    return new Response("Missing stripe-signature header", { status: 400 });
  }

  // CRITICAL: read the body as RAW text. App Router hands us the
  // untouched request body when we use request.text() — unlike
  // Pages Router, there's no global bodyParser consuming it first.
  // The signature is computed over these exact bytes.
  const body = await request.text();

  const stripe = getStripe();
  let event: StripeNS.Event;
  try {
    event = stripe.webhooks.constructEvent(body, signature, getWebhookSecret());
  } catch (e) {
    const message = e instanceof Error ? e.message : "unknown";
    console.warn("[/api/billing/webhook] signature verification failed:", message);
    return new Response(`Webhook signature verification failed: ${message}`, {
      status: 400,
    });
  }

  // Mark-seen BEFORE the handler runs. The handler will tell us the
  // tenantId once it knows; for the dedup insert we pass null and
  // accept the slight denormalization (the row's tenantId column is
  // nullable). A future cleanup pass can rejoin events to their
  // tenants via the JSON payload if needed.
  const dedup = await markEventSeen(event, null);
  if (dedup.alreadySeen) {
    console.log(
      `[/api/billing/webhook] duplicate event ${event.id} (${event.type}); ack-and-skip`,
    );
    return Response.json({ received: true, duplicate: true });
  }

  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const session = event.data.object as StripeNS.Checkout.Session;
        const result = await upsertTenantFromSession(session);
        console.log(
          `[/api/billing/webhook] tenant ${result.created ? "created" : "updated"}: ${result.tenantId}`,
        );
        break;
      }
      case "customer.subscription.created": {
        const sub = event.data.object as StripeNS.Subscription;
        const result = await handleSubscriptionCreated(sub, event.id);
        if (result.tenantId) {
          console.log(
            `[/api/billing/webhook] subscription.created ${sub.id} → tenant ${result.tenantId} (${result.created ? "new" : "updated"})`,
          );
        }
        break;
      }
      case "customer.subscription.updated": {
        const sub = event.data.object as StripeNS.Subscription;
        const result = await handleSubscriptionUpdated(sub);
        if (result.tenantId) {
          console.log(
            `[/api/billing/webhook] subscription.updated ${sub.id} → tenant ${result.tenantId} status=${result.status} tier=${result.tier ?? "(unchanged)"}`,
          );
        }
        break;
      }
      case "customer.subscription.deleted": {
        const sub = event.data.object as StripeNS.Subscription;
        const result = await handleSubscriptionDeleted(sub);
        if (result.tenantId && result.purgeAt) {
          console.log(
            `[/api/billing/webhook] subscription.deleted ${sub.id} → tenant ${result.tenantId} canceled; purge scheduled for ${result.purgeAt}`,
          );
        }
        break;
      }
      case "invoice.payment_succeeded": {
        const invoice = event.data.object as StripeNS.Invoice;
        const result = await handleInvoicePaymentSucceeded(invoice, event.id);
        if (result.tenantId) {
          console.log(
            `[/api/billing/webhook] invoice.payment_succeeded ${result.invoiceId} → tenant ${result.tenantId}`,
          );
        }
        break;
      }
      case "invoice.payment_failed": {
        const invoice = event.data.object as StripeNS.Invoice;
        const result = await handleInvoicePaymentFailed(invoice);
        if (result.tenantId) {
          console.log(
            `[/api/billing/webhook] invoice.payment_failed → tenant ${result.tenantId} transitioned=${result.transitioned} emailed=${result.emailed} reason=${result.reason}`,
          );
        }
        break;
      }
      default:
        // Ignore other events — we'll add handlers as needed.
        break;
    }
  } catch (e) {
    const message = e instanceof Error ? e.message : "unknown";
    console.error("[/api/billing/webhook] handler error:", message);
    // 500 makes Stripe retry, which is fine for transient errors but
    // punishing for permanent ones (bad data). The dedup row is
    // already in place — on retry, markEventSeen will see the
    // existing row and return alreadySeen=true, short-circuiting the
    // retry. To allow a real retry, the operator can manually delete
    // the ProcessedStripeEvent row.
    return new Response(`Handler error: ${message}`, { status: 500 });
  }

  return Response.json({ received: true });
}

// Surface the constants so the smoke test + purge script can read
// the same numbers without re-defining them. This is a deliberate
// "re-export" — re-imports of these names from this module are
// allowed but discouraged (import from @/lib/billing-webhook).
export { PAYMENT_FAILURE_GRACE_DAYS, CANCELED_TENANT_RETENTION_DAYS };
