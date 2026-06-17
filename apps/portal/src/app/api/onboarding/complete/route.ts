// POST /api/onboarding/complete
//
// Body: { tenantId }
//
// Locks the residency region, marks onboardingCompletedAt, and
// dispatches the welcome email with a magic-link signin URL. The
// response includes the magic-link URL so the client can show a
// "check your inbox" state and let the user click through directly
// without waiting on the email (the email is a fallback for
// async/inbox delivery).
//
// Only the tenant owner can complete the wizard.

import { NextResponse } from "next/server";
import { requireOnboardingOwner } from "@/lib/onboarding-auth";
import {
  OnboardingError,
  completeOnboarding,
} from "@/lib/onboarding";
import {
  buildWelcomeMagicLink,
  findTenantOwnerEmail,
  isWelcomeEmailMockMode,
  sendWelcomeEmail,
} from "@/lib/welcome-email";
import { maybeSendFirstAuditComplete } from "@/lib/emails/trigger";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface Body {
  tenantId?: unknown;
}

export async function POST(request: Request) {
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const tenantId = typeof body.tenantId === "string" ? body.tenantId : "";

  let ownerEmail: string | null;
  try {
    const owner = await requireOnboardingOwner(tenantId);
    ownerEmail = await findTenantOwnerEmail(tenantId);
    if (!ownerEmail) {
      // Fall back to the session user's email when the owner membership
      // has no email on file (rare — happens when the redeem created
      // the user row with an empty email).
      ownerEmail = owner.userId;
    }
  } catch (e) {
    return mapError(e);
  }

  let result;
  try {
    result = await completeOnboarding({ tenantId });
  } catch (e) {
    return mapError(e);
  }

  // Build the magic link and dispatch the email. In mock mode (no
  // RESEND_API_KEY) the helper logs to the console and we surface the
  // URL in the response so the dev flow stays unbroken end-to-end.
  const magicLink = buildWelcomeMagicLink({
    email: ownerEmail!,
    redirectTo: "/dashboard",
  });
  const dispatch = await sendWelcomeEmail({
    to: ownerEmail!,
    tenantName: result.name,
    magicLink,
  });

  // First-audit-complete follow-up. Idempotent — fires the first
  // time a tenant has a real encounter + findings, and never again
  // (Tenant.firstAuditEmailSentAt is the dedup key). Runs after the
  // welcome send because a) the welcome is the user-visible primary
  // and b) we want the "first audit ready" email to land in a
  // mailbox that already has the welcome's magic link in it.
  let firstAudit:
    | { sent: true; id: string; encounterId: string }
    | { skipped: true; reason: string }
    | { sent: false; error: string }
    | null = null;
  try {
    firstAudit = await maybeSendFirstAuditComplete(tenantId);
  } catch (e) {
    const message = e instanceof Error ? e.message : "unknown error";
    console.error(
      "[/api/onboarding/complete] maybeSendFirstAuditComplete threw:",
      message,
    );
  }

  return NextResponse.json(
    {
      tenant: result,
      magicLink,
      emailSent: dispatch.sent,
      emailMock: dispatch.mock || isWelcomeEmailMockMode(),
      emailId: dispatch.id ?? null,
      firstAudit,
    },
    { status: 200 },
  );
}

function mapError(e: unknown): NextResponse {
  if (e instanceof OnboardingError) {
    const status =
      e.code === "unauthenticated"
        ? 401
        : e.code === "forbidden"
          ? 403
          : e.code === "tenant_not_found"
            ? 404
            : e.code === "step_not_reached" || e.code === "missing_field"
              ? 409
              : 400;
    return NextResponse.json(
      { error: e.code, message: e.message },
      { status },
    );
  }
  const message = e instanceof Error ? e.message : "unknown error";
  console.error("[/api/onboarding/complete] error:", message);
  return NextResponse.json({ error: "internal_error" }, { status: 500 });
}
