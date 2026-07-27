// POST /api/billing/portal
//
// Returns a Stripe Customer Portal URL for the given tenant. Used for
// self-serve plan changes, billing-detail updates, and cancellation.
//
// Body: { tenantId: string }
//
// Demo mode: returns { url: <local /portal/billing stub>, demo: true }.
//
// Role gate (t_23bfd49c): only the `billing` capability is allowed
// (owner / admin). The Stripe Customer Portal is the entire billing
// surface — plan, payment method, invoice history, cancel — so an
// auditor or viewer must NOT be able to mint a portal URL even
// though the public proxy would otherwise let the request through.

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { getStripe, isDemoMode } from "@/lib/stripe";
import { assertMembershipCapability } from "@/lib/membership-gate";

interface PortalBody {
  tenantId?: unknown;
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
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  if (!raw || typeof raw !== "object") {
    return Response.json({ error: "Body must be { tenantId }" }, { status: 400 });
  }
  const tenantId = (raw as PortalBody).tenantId;
  if (typeof tenantId !== "string" || tenantId.length === 0) {
    return Response.json({ error: "tenantId is required" }, { status: 400 });
  }

  // Role gate (t_23bfd49c): owner/admin only. Auditor and viewer
  // are rejected with 403 before we touch Stripe.
  const gate = await assertMembershipCapability(
    session.user.id,
    tenantId,
    "billing",
  );
  if (!gate.ok) {
    return Response.json(
      { error: "forbidden", message: "Only owners can access the billing portal." },
      { status: 403 },
    );
  }

  const tenant = await prisma.tenant.findUnique({ where: { id: tenantId } });
  if (!tenant) {
    return Response.json({ error: `Tenant ${tenantId} not found` }, { status: 404 });
  }
  if (!tenant.stripeCustomerId) {
    return Response.json(
      {
        error:
          `Tenant ${tenantId} has no stripeCustomerId. ` +
          `Open the Customer Portal only after the first successful Checkout.`,
      },
      { status: 409 }
    );
  }

  const baseUrl = process.env["BASE_URL"] || "http://localhost:3000";

  if (isDemoMode()) {
    return Response.json({
      url: `${baseUrl}/portal/billing?tenantId=${encodeURIComponent(tenantId)}&demo=1`,
      demo: true,
    });
  }

  try {
    const session = await getStripe().billingPortal.sessions.create({
      customer: tenant.stripeCustomerId,
      return_url: `${baseUrl}/portal/billing?tenantId=${encodeURIComponent(tenantId)}`,
    });
    return Response.json({ url: session.url, demo: false });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown Stripe error";
    console.error("[/api/billing/portal] Stripe error:", message);
    return Response.json({ error: "stripe_unavailable" }, { status: 502 });
  }
}
