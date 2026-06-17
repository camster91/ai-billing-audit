// POST /api/onboarding/clinic-profile
//
// Body: { tenantId, clinicName?, clinicNpi?, clinicTimezone? }
//
// Persists the step 2 fields. Requires the caller to be a member of
// the tenant; the lib enforces step-1-precedes-step-2.

import { NextResponse } from "next/server";
import { requireOnboardingAuth } from "@/lib/onboarding-auth";
import { OnboardingError, saveClinicProfile } from "@/lib/onboarding";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface Body {
  tenantId?: unknown;
  clinicName?: unknown;
  clinicNpi?: unknown;
  clinicTimezone?: unknown;
}

export async function POST(request: Request) {
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const tenantId = typeof body.tenantId === "string" ? body.tenantId : "";

  try {
    await requireOnboardingAuth(tenantId);
    const result = await saveClinicProfile({
      tenantId,
      input: {
        clinicName: asString(body.clinicName),
        clinicNpi: asString(body.clinicNpi),
        clinicTimezone: asString(body.clinicTimezone),
      },
    });
    return NextResponse.json(result, { status: 200 });
  } catch (e) {
    return mapError(e);
  }
}

function asString(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

function mapError(e: unknown): NextResponse {
  if (e instanceof OnboardingError) {
    const status =
      e.code === "unauthenticated"
        ? 401
        : e.code === "forbidden"
          ? 403
          : e.code === "step_not_reached"
            ? 409
            : 400;
    return NextResponse.json(
      { error: e.code, message: e.message },
      { status },
    );
  }
  const message = e instanceof Error ? e.message : "unknown error";
  console.error("[/api/onboarding/clinic-profile] error:", message);
  return NextResponse.json({ error: "internal_error" }, { status: 500 });
}
