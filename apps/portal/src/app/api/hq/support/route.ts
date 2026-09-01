import { NextResponse } from "next/server";
import { ZodError } from "zod";
import { internalErrorResponse } from "@/lib/api-errors";
import { requirePlatformApi } from "@/lib/platform-auth";
import { createSupportCase, createSupportCaseSchema, SupportCaseError } from "@/lib/support-case";

export async function POST(request: Request) {
  const gate = await requirePlatformApi("support:write");
  if (!gate.ok) return gate.response;
  let body: unknown;
  try { body = await request.json(); } catch { return NextResponse.json({ error: "invalid_json" }, { status: 400 }); }
  try {
    const supportCase = await createSupportCase(createSupportCaseSchema.parse(body), gate.request);
    return NextResponse.json({ ok: true, supportCase: { id: supportCase.id, version: supportCase.version } }, { status: 201 });
  } catch (error) {
    if (error instanceof ZodError) return NextResponse.json({ error: "invalid_input", details: error.flatten() }, { status: 400 });
    if (error instanceof SupportCaseError) {
      const status = error.code === "engagement_not_found" ? 404 : error.code.includes("conflict") ? 409 : 400;
      return NextResponse.json({ error: error.code, detail: error.message }, { status });
    }
    return internalErrorResponse(request, error, "/api/hq/support");
  }
}
