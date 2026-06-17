// POST /api/settings/region
//
// Body: { region: "ca-central-1" | "us-east-1" }
//
// Persists the data residency region for the active tenant. Rejects
// with 409 when the region is locked — either by the wizard
// (residencyRegionLocked) or implicitly by the existence of an
// Encounter row (the first audit has been recorded).

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import {
  RESIDENCY_REGIONS,
  saveResidencyRegionSettings,
  SettingsError,
} from "@/lib/settings";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface Body {
  region?: unknown;
}

export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const tenant = await getActiveTenant();
  if (!tenant) {
    return NextResponse.json({ error: "no_tenant" }, { status: 403 });
  }

  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
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
    const result = await saveResidencyRegionSettings({
      tenantId: tenant.id,
      input: { region: region as (typeof RESIDENCY_REGIONS)[number] },
    });
    return NextResponse.json(result, { status: 200 });
  } catch (e) {
    return mapError(e);
  }
}

function mapError(e: unknown): NextResponse {
  if (e instanceof SettingsError) {
    const status =
      e.code === "unauthenticated"
        ? 401
        : e.code === "not_found"
          ? 404
          : e.code === "region_locked"
            ? 409
            : e.code === "invalid_input"
              ? 400
              : 500;
    return NextResponse.json(
      { error: e.code, message: e.message },
      { status },
    );
  }
  const message = e instanceof Error ? e.message : "unknown error";
  console.error("[/api/settings/region] error:", message);
  return NextResponse.json({ error: "internal_error" }, { status: 500 });
}
