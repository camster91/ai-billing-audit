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
// Role gate (t_23bfd49c): any active member with the `read`
// capability (viewer / auditor / owner / admin) can fetch the
// subscription snapshot. The billing-snapshot data is read-only
// tenant metadata, not a billing-side mutation; non-billing roles
// that need it (e.g. a viewer dashboard) still see it. The
// mutations (change-tier, cancel) remain owner-only via the
// `billing` capability.
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
//   403 — not a member of the named tenant, or membership inactive
//   500 — unexpected error

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { loadSubscriptionSnapshot } from "@/lib/billing-page";
import { assertMembershipCapability } from "@/lib/membership-gate";
import { internalErrorResponse } from "@/lib/api-errors";

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
  // Role gate (t_23bfd49c): read capability covers every active
  // member role. The previous check (just `findFirst` on membership
  // existence) didn't catch inactive members or wrong-role
  // callers; the gate does both.
  const gate = await assertMembershipCapability(
    session.user.id,
    tenantId,
    "read",
  );
  if (!gate.ok) {
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
    return internalErrorResponse(request, e, "/api/billing/subscription");
  }
}
