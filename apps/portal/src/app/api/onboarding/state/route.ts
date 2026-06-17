// GET /api/onboarding/state?session_id=...
//
// Returns the wizard's current state for the calling user. Used by
// the /portal/onboarding page on first render so the right step is
// shown without a hard reload.
//
// Anonymous callers get back a sign-in URL. Signed-in callers get the
// full WizardState. When the session was already redeemed by a
// different user, returns 409.

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { loadWizardState, OnboardingError } from "@/lib/onboarding";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const sessionId = url.searchParams.get("session_id") ?? "";
  if (!sessionId) {
    return NextResponse.json(
      { error: "session_id is required" },
      { status: 400 },
    );
  }

  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json(
      {
        requiresSignIn: true,
        signInUrl: `/login?callbackUrl=${encodeURIComponent(`/portal/onboarding?session_id=${sessionId}`)}`,
      },
      { status: 200 },
    );
  }
  const userId = session.user.id;

  // Find the tenant the session redeemed to (if any) and load state.
  const redemption = await prisma.redeemedCheckoutSession.findUnique({
    where: { sessionId },
    select: { tenantId: true, userId: true },
  });
  if (!redemption) {
    return NextResponse.json(
      {
        error: "session_not_redeemed",
        message:
          "This checkout session has not been redeemed yet. Call /api/onboarding/redeem first.",
      },
      { status: 404 },
    );
  }
  if (redemption.userId !== userId) {
    return NextResponse.json(
      {
        error: "session_already_claimed",
        message:
          "This checkout session has already been attached to a different account.",
      },
      { status: 409 },
    );
  }

  try {
    const state = await loadWizardState({
      tenantId: redemption.tenantId,
      sessionId,
      userId,
    });
    return NextResponse.json({ state }, { status: 200 });
  } catch (e) {
    if (e instanceof OnboardingError) {
      return NextResponse.json(
        { error: e.code, message: e.message },
        { status: 400 },
      );
    }
    const message = e instanceof Error ? e.message : "unknown error";
    console.error("[/api/onboarding/state] error:", message);
    return NextResponse.json({ error: "internal_error" }, { status: 500 });
  }
}
