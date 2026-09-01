import { NextResponse } from "next/server";
import { ZodError } from "zod";
import { internalErrorResponse } from "@/lib/api-errors";
import { requirePlatformApi } from "@/lib/platform-auth";
import {
  ClientEngagementError,
  createClientEngagement,
  createClientEngagementSchema,
} from "@/lib/client-engagement";

interface RouteContext { params: Promise<{ id: string }> }

export async function POST(request: Request, context: RouteContext) {
  const gate = await requirePlatformApi("clients:write");
  if (!gate.ok) return gate.response;
  const { id } = await context.params;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }

  try {
    const engagement = await createClientEngagement(
      id,
      createClientEngagementSchema.parse(body),
      gate.request,
    );
    return NextResponse.json({ ok: true, engagement: { id: engagement.id } }, { status: 201 });
  } catch (error) {
    if (error instanceof ZodError) {
      return NextResponse.json({ error: "invalid_input", details: error.flatten() }, { status: 400 });
    }
    if (error instanceof ClientEngagementError) {
      const status = error.code === "lead_not_found" ? 404 : error.code.includes("conflict") || error.code === "engagement_exists" ? 409 : 400;
      return NextResponse.json({ error: error.code, detail: error.message }, { status });
    }
    return internalErrorResponse(request, error, `/api/hq/leads/${id}/convert`);
  }
}
