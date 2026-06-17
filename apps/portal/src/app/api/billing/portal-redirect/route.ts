// GET /api/billing/portal-redirect?tenantId=<id>
//
// Server-side helper that the /portal/billing page uses to bounce the
// browser into the Stripe Customer Portal. Calls /api/billing/portal
// internally, then 302s to the returned URL.
//
// Keeping this separate from the POST endpoint lets the page use a
// straight <a href> link — the user gets a clean redirect with no
// client-side fetch + window.location dance.

import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getStripe, isDemoMode } from "@/lib/stripe";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const tenantId = url.searchParams.get("tenantId");
  if (!tenantId) {
    return NextResponse.json({ error: "tenantId required" }, { status: 400 });
  }

  const tenant = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: { stripeCustomerId: true },
  });
  if (!tenant) {
    return NextResponse.json({ error: "tenant not found" }, { status: 404 });
  }
  if (!tenant.stripeCustomerId) {
    return NextResponse.json(
      { error: "tenant has no stripeCustomerId" },
      { status: 409 }
    );
  }

  const baseUrl = process.env["BASE_URL"] || `${url.protocol}//${url.host}`;

  if (isDemoMode()) {
    return NextResponse.redirect(
      `${baseUrl}/portal/onboarding?demo=1&note=portal-unavailable-in-demo`
    );
  }

  try {
    const session = await getStripe().billingPortal.sessions.create({
      customer: tenant.stripeCustomerId,
      return_url: `${baseUrl}/portal/billing?tenantId=${encodeURIComponent(tenantId)}`,
    });
    return NextResponse.redirect(session.url);
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown Stripe error";
    console.error("[/api/billing/portal-redirect] Stripe error:", message);
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
