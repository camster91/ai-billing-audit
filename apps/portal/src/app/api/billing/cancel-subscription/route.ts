// POST /api/billing/cancel-subscription
//
// Body: { tenantId: string, confirm: true }
//
// The grace-period warning is rendered by the client BEFORE this
// call. The endpoint enforces the confirm flag — a missing or
// false confirm returns 400 so an accidental click can't kill
// the subscription.
//
// In non-demo mode: calls stripe.subscriptions.update with
// cancel_at_period_end = true. The subscription stays active
// until the end of the current billing period, Stripe sends a
// final invoice, and the customer.subscription.deleted webhook
// flips the tenant's subscriptionStatus to "canceled" (the
// existing handler in src/app/api/billing/webhook/route.ts
// already does this; we just mirror the change to the local row
// eagerly so the page reflects the user's choice immediately).
//
// In demo mode: returns 409 — the page's "Cancel subscription"
// button is hidden in demo mode, but the API still defends
// against direct hits.
//
// Auth: signed-in user with a membership in the named tenant.
// The route accepts tenantId in the body (not the session
// header) for the same reason as /api/billing/change-tier —
// the proxy's PUBLIC_PREFIXES for /api/billing short-circuits
// the x-tenant-id header injection.
//
// Response (200):
//   { cancelAt: ISO date string (period end), demo: false }
//
// Errors:
//   400 — confirm missing/false
//   401 — not signed in
//   403 — not a member of the named tenant
//   409 — demo mode / no Stripe subscription
//   500 — DB / Stripe error

import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { auth } from "@/auth";
import { getStripe, isDemoMode } from "@/lib/stripe";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface CancelBody {
  tenantId: unknown;
  confirm: unknown;
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
  const { tenantId, confirm } = raw as CancelBody;
  if (typeof tenantId !== "string" || tenantId.length === 0) {
    return NextResponse.json(
      { error: "tenantId_required" },
      { status: 400 },
    );
  }
  if (confirm !== true) {
    return NextResponse.json(
      {
        error: "confirm_required",
        message:
          "Cancellation requires explicit confirmation. Set { confirm: true } in the request body.",
      },
      { status: 400 },
    );
  }

  // Membership check (t_23bfd49c): only OWNER | ADMIN of the
  // target tenant can cancel the subscription. Auditor and
  // viewer are rejected with 403.
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
        message: "Only owners can cancel the subscription.",
      },
      { status: 403 },
    );
  }

  if (isDemoMode()) {
    return NextResponse.json(
      {
        error: "demo_mode",
        message:
          "Stripe is in demo mode. The Cancel button is disabled on the page in demo mode.",
      },
      { status: 409 },
    );
  }

  const fullTenant = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: { stripeSubscriptionId: true },
  });
  if (!fullTenant?.stripeSubscriptionId) {
    return NextResponse.json(
      {
        error: "no_subscription",
        message: "No active Stripe subscription for this tenant.",
      },
      { status: 409 },
    );
  }

  try {
    const stripe = getStripe();
    const updated = await stripe.subscriptions.update(
      fullTenant.stripeSubscriptionId,
      { cancel_at_period_end: true },
    );
    // cancel_at_period_end = true means Stripe will end the
    // subscription at the period close. The cancel_at field on
    // the response is the timestamp. The customer.subscription.deleted
    // webhook will fire later, but we update the local row now
    // so the UI shows the canceled status immediately.
    const cancelAt =
      typeof updated.cancel_at === "number" && updated.cancel_at > 0
        ? new Date(updated.cancel_at * 1000).toISOString()
        : null;
    await prisma.tenant.update({
      where: { id: tenantId },
      data: {
        subscriptionStatus: "canceled",
        canceledAt: cancelAt ? new Date(cancelAt) : new Date(),
      },
    });
    return NextResponse.json({
      cancelAt,
      demo: false,
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : "unknown";
    console.error("[/api/billing/cancel-subscription] error:", message);
    return NextResponse.json(
      { error: "stripe_error", message },
      { status: 502 },
    );
  }
}
