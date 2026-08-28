import { NextResponse } from "next/server";
import { ZodError } from "zod";
import { internalErrorResponse } from "@/lib/api-errors";
import { requirePlatformApi } from "@/lib/platform-auth";
import {
  LeadWorkflowError,
  leadMutationSchema,
  updateLeadWorkflow,
} from "@/lib/lead-workflow";

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function PUT(request: Request, context: RouteContext) {
  const gate = await requirePlatformApi("leads:write");
  if (!gate.ok) return gate.response;
  const { id } = await context.params;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }

  try {
    const input = leadMutationSchema.parse(body);
    const lead = await updateLeadWorkflow(id, input, gate.request);
    return NextResponse.json({ ok: true, lead: { id: lead.id, version: lead.version } });
  } catch (error) {
    if (error instanceof ZodError) {
      return NextResponse.json(
        { error: "invalid_input", details: error.flatten() },
        { status: 400 },
      );
    }
    if (error instanceof LeadWorkflowError) {
      const status =
        error.code === "lead_not_found"
          ? 404
          : error.code === "version_conflict" || error.code === "idempotency_conflict"
            ? 409
            : 400;
      return NextResponse.json({ error: error.code, detail: error.message }, { status });
    }
    return internalErrorResponse(request, error, `/api/hq/leads/${id}`);
  }
}
