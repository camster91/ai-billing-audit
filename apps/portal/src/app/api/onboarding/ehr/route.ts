// POST /api/onboarding/ehr
//
// Body: { tenantId, mode: "sftp" | "manual", host?, port?, username?, password? }
//
// Persists the step 4 EHR connection. SFTP mode requires the full
// credential set; "manual" mode is the explicit skip-SFTP flag.

import { NextResponse } from "next/server";
import { requireOnboardingAuth } from "@/lib/onboarding-auth";
import { OnboardingError, saveEhrConnection } from "@/lib/onboarding";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface Body {
  tenantId?: unknown;
  mode?: unknown;
  host?: unknown;
  port?: unknown;
  username?: unknown;
  password?: unknown;
}

export async function POST(request: Request) {
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const tenantId = typeof body.tenantId === "string" ? body.tenantId : "";
  const mode = typeof body.mode === "string" ? body.mode : "";

  if (mode !== "sftp" && mode !== "manual") {
    return NextResponse.json(
      { error: "invalid_input", message: "mode must be 'sftp' or 'manual'" },
      { status: 400 },
    );
  }

  try {
    await requireOnboardingAuth(tenantId);
    const result = await saveEhrConnection({
      tenantId,
      input: {
        mode,
        host: asString(body.host),
        port: asPort(body.port),
        username: asString(body.username),
        password: asString(body.password),
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

function asPort(v: unknown): number | undefined {
  if (typeof v === "number" && Number.isInteger(v)) return v;
  if (typeof v === "string" && v.trim().length > 0) {
    const n = Number.parseInt(v, 10);
    if (Number.isInteger(n)) return n;
  }
  return undefined;
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
  console.error("[/api/onboarding/ehr] error:", message);
  return NextResponse.json({ error: "internal_error" }, { status: 500 });
}
