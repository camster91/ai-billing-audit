// GET /api/billing/subscription?tenantId=<id>
//
// Returns the current plan tier, subscription status, and (when
// known) the next invoice date + amount for the named tenant.
// Mirrors what the /billing page renders in the "Current plan"
// card. Source of truth: Tenant row for the static fields, live
// Stripe for the dynamic next-invoice data.
//
// tenantId is taken from a query param (not the session header)
// because the route lives under /api/billing/* which is in the
// proxy's PUBLIC_PREFIXES — that prefix short-circuits the
// x-tenant-id header injection. Membership is verified server-side
// so a signed-in user can't peek at another tenant's subscription.
//
// Response shape (200):
//   {
//     tier: "small" | "mid" | "large" | null,
//     status: "active" | "past_due" | "canceled" | ...,
//     nextInvoiceAt: ISO date string | null,
//     nextInvoiceAmount: "CA$1,499" | null,
//     hasStripeCustomer: boolean,
//     demo: boolean
//   }
//
// Errors:
//   400 — tenantId missing
//   401 — not signed in
//   403 — not a member of the named tenant
//   500 — unexpected error

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { loadSubscriptionSnapshot } from "@/lib/billing-page";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const url = new URL(request.url);
  const tenantId = url.searchParams.get("tenantId");
  if (!tenantId) {
    return NextResponse.json(
      { error: "tenantId_required" },
      { status: 400 },
    );
  }
  // Membership check.
  const membership = await prisma.membership.findFirst({
    where: { userId: session.user.id, tenantId },
    select: { id: true },
  });
  if (!membership) {
    return NextResponse.json(
      { error: "forbidden", message: "Not a member of this tenant." },
      { status: 403 },
    );
  }
  try {
    const snapshot = await loadSubscriptionSnapshot(tenantId);
    return NextResponse.json(snapshot, {
      headers: {
        "Cache-Control": "private, no-store",
      },
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : "unknown";
    console.error("[/api/billing/subscription] error:", message);
    return NextResponse.json(
      { error: "internal_error", message },
      { status: 500 },
    );
  }
}
