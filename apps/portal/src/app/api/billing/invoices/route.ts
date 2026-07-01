// GET /api/billing/invoices?tenantId=<id>
//
// Returns the last 12 months of invoices for the named tenant.
// Source: Tenant.invoice rows (populated by the webhook handler
// on invoice.payment_succeeded). In non-demo mode we also pull
// the live Stripe list so any invoice that's been created but
// not yet webhooked still shows up.
//
// tenantId is taken from a query param for the same reason as
// /api/billing/subscription: the route is under /api/billing/*
// which is in the proxy's PUBLIC_PREFIXES. Membership is
// verified server-side.
//
// Response shape (200):
//   {
//     invoices: Array<{
//       id: string,
//       date: "YYYY-MM-DD",
//       amount: "CA$1,499" | "$1,109" | ...,
//       status: "paid" | "open" | ...,
//       hostedUrl: string | null,
//       pdfUrl:    string | null,
//       fromCache: boolean
//     }>
//   }
//
// Errors:
//   400 — tenantId missing
//   401 — not signed in
//   403 — not a member of the named tenant
//   500 — DB error

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { loadInvoiceHistory } from "@/lib/billing-page";
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
  // Role gate (t_23bfd49c): invoice history is a read — every
  // active member role qualifies.
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
    const invoices = await loadInvoiceHistory(tenantId);
    return NextResponse.json(
      { invoices },
      {
        headers: {
          // Invoices are tenant-scoped; a private + short cache
          // is safe. The webhook handler is the canonical writer
          // — we don't want a long cache hiding new payments.
          "Cache-Control": "private, max-age=10",
        },
      },
    );
  } catch (e) {
    return internalErrorResponse(request, e, "/api/billing/invoices");
  }
}
