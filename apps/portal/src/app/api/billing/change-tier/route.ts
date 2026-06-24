// POST /api/billing/change-tier
//
// Body: { tenantId: string, newTierId: "small" | "mid" | "large", currency: "CAD" | "USD" }
//
// In non-demo mode: calls stripe.subscriptions.update to swap the
// active price on the existing subscription, with
// proration_behavior = "create_prorations" so the customer gets
// credited for the unused portion of the current period. Returns
// the updated subscription summary so the page can refresh
// itself.
//
// In demo mode: returns 409 — the user should use the Stripe
// Customer Portal to make changes, which the page's "Update
// payment method" link also routes through.
//
// The route accepts tenantId in the body (not the session header)
// so it can be served under /api/billing/* which is in the
// proxy's PUBLIC_PREFIXES — that prefix short-circuits the auth
// gate that would otherwise set the x-tenant-id header. The
// page's client component knows the active tenant id and passes
// it in. We verify membership here so a signed-in user can't
// mutate another tenant's subscription.
//
// Response (200):
//   {
//     tier: "mid",
//     status: "active",
//     demo: false
//   }
//
// Errors:
//   400 — invalid body
//   401 — not signed in
//   403 — not a member of the named tenant
//   409 — demo mode / already on tier / no Stripe subscription
//   500 — DB / Stripe error

import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { auth } from "@/auth";
import { getStripe, isDemoMode } from "@/lib/stripe";
import {
  getStripePriceId,
  isValidCurrencyCode,
  isValidTierId,
  type CurrencyCode,
  type TierId,
} from "@/lib/pricing";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface ChangeTierBody {
  tenantId: unknown;
  newTierId: unknown;
  currency: unknown;
}

export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }
  if (!raw || typeof raw !== "object") {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }
  const { tenantId, newTierId, currency } = raw as ChangeTierBody;
  if (typeof tenantId !== "string" || tenantId.length === 0) {
    return NextResponse.json(
      { error: "tenantId_required" },
      { status: 400 },
    );
  }
  if (!isValidTierId(newTierId)) {
    return NextResponse.json(
      { error: "invalid_tier", message: "Expected one of: small, mid, large." },
      { status: 400 },
    );
  }
  if (!isValidCurrencyCode(currency)) {
    return NextResponse.json(
      { error: "invalid_currency", message: "Expected CAD or USD." },
      { status: 400 },
    );
  }

  // Membership check (t_23bfd49c): only OWNER | ADMIN of the
  // target tenant can change the subscription tier. Auditor
  // and viewer are rejected with 403. The previous check
  // only verified membership existence; the spec says
  // "billing actions are owner-only".
  const membership = await prisma.membership.findFirst({
    where: { userId: session.user.id, tenantId },
    select: { id: true, role: true, status: true },
  });
  if (!membership || membership.status === "inactive") {
    return NextResponse.json(
      { error: "forbidden", message: "Not a member of this tenant." },
      { status: 403 },
    );
  }
  if (membership.role !== "owner" && membership.role !== "admin") {
    return NextResponse.json(
      {
        error: "forbidden",
        message: "Only owners can change the subscription tier.",
      },
      { status: 403 },
    );
  }

  if (isDemoMode()) {
    return NextResponse.json(
      {
        error: "demo_mode",
        message:
          "Stripe is in demo mode. Tier changes go through the Stripe Customer Portal — use the 'Update payment method' link.",
      },
      { status: 409 },
    );
  }

  const fullTenant = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: {
      stripeCustomerId: true,
      stripeSubscriptionId: true,
      tier: true,
    },
  });
  if (!fullTenant?.stripeCustomerId || !fullTenant.stripeSubscriptionId) {
    return NextResponse.json(
      {
        error: "no_subscription",
        message:
          "No active Stripe subscription for this tenant. Complete a Checkout first.",
      },
      { status: 409 },
    );
  }

  const targetTier = newTierId as TierId;
  const targetCurrency = currency as CurrencyCode;
  if (fullTenant.tier === targetTier) {
    return NextResponse.json(
      { error: "already_on_tier", message: `Already on ${targetTier}.` },
      { status: 409 },
    );
  }
  const priceId = getStripePriceId(targetTier, targetCurrency);
  if (!priceId) {
    return NextResponse.json(
      {
        error: "no_price_configured",
        message: `No Stripe price for ${targetTier} ${targetCurrency}. Set PRICING_TIER_${targetTier.toUpperCase()}_STRIPE_PRICE_ID_${targetCurrency}.`,
      },
      { status: 503 },
    );
  }

  try {
    const stripe = getStripe();
    // Fetch the current subscription so we can swap the single
    // line item's price id. The spec says "update the
    // subscription's price/quantity" — we use the standard
    // subscription_items.update pattern (replaces the price on
    // the existing item) so proration is computed correctly.
    const sub = await stripe.subscriptions.retrieve(
      fullTenant.stripeSubscriptionId,
    );
    const firstItem = sub.items.data[0];
    if (!firstItem) {
      return NextResponse.json(
        { error: "subscription_has_no_items" },
        { status: 502 },
      );
    }
    const updated = await stripe.subscriptions.update(
      fullTenant.stripeSubscriptionId,
      {
        items: [{ id: firstItem.id, price: priceId }],
        proration_behavior: "create_prorations",
        metadata: {
          tierId: targetTier,
          currency: targetCurrency,
        },
      },
    );
    // Mirror the new tier onto the local tenant row so the page
    // renders correctly the next time it loads. The webhook's
    // customer.subscription.updated handler will also do this
    // when the event lands, but the page might render before
    // that — write the row eagerly so the user sees their change
    // immediately.
    const newStatus =
      typeof updated.status === "string" ? updated.status : "active";
    await prisma.tenant.update({
      where: { id: tenantId },
      data: {
        tier: targetTier,
        subscriptionStatus: newStatus,
      },
    });
    return NextResponse.json({
      tier: targetTier,
      status: newStatus,
      demo: false,
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : "unknown";
    console.error("[/api/billing/change-tier] error:", message);
    return NextResponse.json(
      { error: "stripe_error", message },
      { status: 502 },
    );
  }
}
