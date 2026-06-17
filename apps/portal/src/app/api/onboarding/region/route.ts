// POST /api/onboarding/region
//
// Body: { tenantId, region: "ca-central-1" | "us-east-1" }
//
// Persists the data residency region. Rejects once the region is
// locked (after wizard completion).

import { NextResponse } from "next/server";
import { requireOnboardingAuth } from "@/lib/onboarding-auth";
import {
  OnboardingError,
  RESIDENCY_REGIONS,
  saveResidencyRegion,
} from "@/lib/onboarding";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface Body {
  tenantId?: unknown;
  region?: unknown;
}

export async function POST(request: Request) {
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const tenantId = typeof body.tenantId === "string" ? body.tenantId : "";
  const region = typeof body.region === "string" ? body.region : "";

  if (!RESIDENCY_REGIONS.includes(region as (typeof RESIDENCY_REGIONS)[number])) {
    return NextResponse.json(
      {
        error: "invalid_input",
        message: `region must be one of: ${RESIDENCY_REGIONS.join(", ")}`,
      },
      { status: 400 },
    );
  }

  try {
    await requireOnboardingAuth(tenantId);
    const result = await saveResidencyRegion({
      tenantId,
      input: { region: region as (typeof RESIDENCY_REGIONS)[number] },
    });
    return NextResponse.json(result, { status: 200 });
  } catch (e) {
    return mapError(e);
  }
}

function mapError(e: unknown): NextResponse {
  if (e instanceof OnboardingError) {
    const status =
      e.code === "unauthenticated"
        ? 401
        : e.code === "forbidden"
          ? 403
          : e.code === "step_not_reached" || e.code === "region_locked"
            ? 409
            : 400;
    return NextResponse.json(
      { error: e.code, message: e.message },
      { status },
    );
  }
  const message = e instanceof Error ? e.message : "unknown error";
  console.error("[/api/onboarding/region] error:", message);
  return NextResponse.json({ error: "internal_error" }, { status: 500 });
}
