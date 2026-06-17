// POST /api/onboarding/first-encounter
//
// Body: { tenantId, mode: "uploaded" | "skipped", filePath?, fileName? }
//
// Persists the step 5 first-encounter status. "uploaded" mode requires
// a filePath produced by /api/onboarding/upload; "skipped" mode is the
// explicit "I'll do this later" flag.

import { NextResponse } from "next/server";
import { requireOnboardingAuth } from "@/lib/onboarding-auth";
import { OnboardingError, saveFirstEncounter } from "@/lib/onboarding";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface Body {
  tenantId?: unknown;
  mode?: unknown;
  filePath?: unknown;
  fileName?: unknown;
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

  if (mode !== "uploaded" && mode !== "skipped") {
    return NextResponse.json(
      {
        error: "invalid_input",
        message: "mode must be 'uploaded' or 'skipped'",
      },
      { status: 400 },
    );
  }

  try {
    await requireOnboardingAuth(tenantId);
    const result = await saveFirstEncounter({
      tenantId,
      input: {
        mode,
        filePath: asString(body.filePath),
        fileName: asString(body.fileName),
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
  console.error("[/api/onboarding/first-encounter] error:", message);
  return NextResponse.json({ error: "internal_error" }, { status: 500 });
}
