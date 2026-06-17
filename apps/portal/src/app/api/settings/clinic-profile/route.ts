// POST /api/settings/clinic-profile
//
// Body: { clinicName?, clinicAddress?, clinicNpi?, clinicTimezone? }
//
// Persists the four clinic-profile fields on the active tenant. Any
// field can be sent as an empty string to clear it; the lib maps
// "" → null on the row. All fields are optional, but if any are
// present they go through the same Zod validation the wizard
// applies at its clinic-profile step (NPI shape, IANA tz shape, etc).

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import {
  saveClinicProfileSettings,
  SettingsError,
} from "@/lib/settings";
import { assertMembershipCapability } from "@/lib/membership-gate";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface Body {
  clinicName?: unknown;
  clinicAddress?: unknown;
  clinicNpi?: unknown;
  clinicTimezone?: unknown;
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
  // Role gate (t_23bfd49c): clinic-profile edit is a write action.
  // Viewers are rejected; auditors are also rejected (auditors
  // can read everything but not mutate non-finding data).
  const gate = await assertMembershipCapability(
    session.user.id,
    tenant.id,
    "write",
  );
  if (!gate.ok) {
    return NextResponse.json(
      { error: gate.error ?? "forbidden" },
      { status: 403 },
    );
  }

  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  try {
    const result = await saveClinicProfileSettings({
      tenantId: tenant.id,
      input: {
        clinicName: asString(body.clinicName),
        clinicAddress: asString(body.clinicAddress),
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
  if (e instanceof SettingsError) {
    const status =
      e.code === "unauthenticated"
        ? 401
        : e.code === "not_found"
          ? 404
          : e.code === "invalid_input"
            ? 400
            : 500;
    return NextResponse.json(
      { error: e.code, message: e.message },
      { status },
    );
  }
  const message = e instanceof Error ? e.message : "unknown error";
  console.error("[/api/settings/clinic-profile] error:", message);
  return NextResponse.json({ error: "internal_error" }, { status: 500 });
}
