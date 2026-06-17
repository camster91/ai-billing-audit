// POST /api/onboarding/redeem
//
// Body: { sessionId: string }
//
// Verifies the Stripe Checkout Session, ensures a Tenant row exists,
// attaches the calling user as `owner`, and returns the wizard state
// (so the page can render the right step on the next render).
//
// Anonymous callers are supported (the buyer just came back from
// Stripe and may not be signed in yet). The response includes
// `requiresSignIn: true` in that case, so the page can route them
// through /login before continuing.

import { NextResponse } from "next/server";
import { getOptionalOnboardingUser } from "@/lib/onboarding-auth";
import {
  OnboardingError,
  redeemCheckoutSession,
  loadWizardState,
} from "@/lib/onboarding";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface RedeemBody {
  sessionId?: unknown;
}

export async function POST(request: Request) {
  let body: RedeemBody;
  try {
    body = (await request.json()) as RedeemBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const sessionId = typeof body.sessionId === "string" ? body.sessionId : "";
  if (!sessionId) {
    return NextResponse.json(
      { error: "sessionId is required" },
      { status: 400 },
    );
  }

  const userId = await getOptionalOnboardingUser();

  if (!userId) {
    // Anonymous caller — don't redeem; return enough info for the
    // page to route them to sign-in.
    return NextResponse.json(
      {
        requiresSignIn: true,
        sessionId,
        signInUrl: `/login?callbackUrl=${encodeURIComponent(`/portal/onboarding?session_id=${sessionId}`)}`,
      },
      { status: 200 },
    );
  }

  try {
    const result = await redeemCheckoutSession({ sessionId, userId });

    if (result.alreadyClaimed) {
      // Don't auto-attach a second user. Return a 409 so the page
      // can show a "this session belongs to a different account" UI.
      return NextResponse.json(
        {
          error: "session_already_claimed",
          message:
            "This checkout session has already been attached to a different account. Sign in with the original email, or contact support.",
          tenantId: result.tenant.id,
        },
        { status: 409 },
      );
    }

    const state = await loadWizardState({
      tenantId: result.tenant.id,
      sessionId,
      userId,
    });

    return NextResponse.json(
      {
        created: result.created,
        tenant: result.tenant,
        state,
      },
      { status: 200 },
    );
  } catch (e) {
    if (e instanceof OnboardingError) {
      const status =
        e.code === "session_not_found" || e.code === "session_incomplete"
          ? 404
          : 400;
      return NextResponse.json(
        { error: e.code, message: e.message },
        { status },
      );
    }
    const message = e instanceof Error ? e.message : "unknown error";
    console.error("[/api/onboarding/redeem] error:", message);
    return NextResponse.json({ error: "internal_error" }, { status: 500 });
  }
}
