// POST /api/settings/phi-redaction
//
// Body: { redact: boolean }
//
// Persists the redactPatientNamesInExports flag on the active
// tenant. Defaults to true (set in the migration). When true, the
// /api/encounters/export and /api/findings/export routes replace
// the per-row patient hash prefix with "[redacted]" so downstream
// spreadsheets don't carry the SHA-256 fingerprint that ties a row
// back to a patient identifier.

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import {
  savePhiRedactionSettings,
  SettingsError,
} from "@/lib/settings";
import { assertMembershipCapability } from "@/lib/membership-gate";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface Body {
  redact?: unknown;
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
  // Role gate (t_23bfd49c): PHI-redaction toggle is a write
  // action — owner/admin only.
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
  if (typeof body.redact !== "boolean") {
    return NextResponse.json(
      { error: "invalid_input", message: "redact must be a boolean" },
      { status: 400 },
    );
  }

  try {
    const result = await savePhiRedactionSettings({
      tenantId: tenant.id,
      redact: body.redact,
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
          : e.code === "invalid_input"
            ? 400
            : 500;
    return NextResponse.json(
      { error: e.code, message: e.message },
      { status },
    );
  }
  const message = e instanceof Error ? e.message : "unknown error";
  console.error("[/api/settings/phi-redaction] error:", message);
  return NextResponse.json({ error: "internal_error" }, { status: 500 });
}
