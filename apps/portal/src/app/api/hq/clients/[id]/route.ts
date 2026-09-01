import { NextResponse } from "next/server";
import { ZodError } from "zod";
import { internalErrorResponse } from "@/lib/api-errors";
import { requirePlatformApi } from "@/lib/platform-auth";
import {
  ClientEngagementError,
  clientEngagementMutationSchema,
  updateClientEngagement,
} from "@/lib/client-engagement";

interface RouteContext { params: Promise<{ id: string }> }

export async function PUT(request: Request, context: RouteContext) {
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
    const client = await updateClientEngagement(id, clientEngagementMutationSchema.parse(body), gate.request);
    return NextResponse.json({ ok: true, client: { id: client.id, version: client.version } });
  } catch (error) {
    if (error instanceof ZodError) {
      return NextResponse.json({ error: "invalid_input", details: error.flatten() }, { status: 400 });
    }
    if (error instanceof ClientEngagementError) {
      const status = error.code === "engagement_not_found" ? 404 : error.code.includes("conflict") ? 409 : 400;
      return NextResponse.json({ error: error.code, detail: error.message }, { status });
    }
    return internalErrorResponse(request, error, `/api/hq/clients/${id}`);
  }
}
