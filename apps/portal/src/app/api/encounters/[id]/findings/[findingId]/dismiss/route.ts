// POST /api/encounters/[id]/findings/[findingId]/dismiss
//
// Marks a finding as dismissed with a required reason payload. The
// reason picker is the dropdown specified in the task body:
//   - wrong_payer_policy
//   - hallucinated_fact
//   - too_conservative
//   - other_with_text  (requires a non-empty reasonText, 1-2000 chars)
//
// Writes exactly one audit_trail row and updates the finding's status
// + dismissReason + dismissText in a single transaction.

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { normalizeDismissInput, writeAuditEntry } from "@/lib/audit-write";
import { dismissInputSchema } from "@/lib/encounter-types";

interface RouteContext {
  params: Promise<{ id: string; findingId: string }>;
}

export async function POST(
  request: Request,
  context: RouteContext,
): Promise<NextResponse> {
  const { id: encounterId, findingId } = await context.params;

  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const tenant = await getActiveTenant();
  if (!tenant) {
    return NextResponse.json({ error: "no_tenant" }, { status: 403 });
  }

  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return NextResponse.json(
      { error: "invalid_json" },
      { status: 400 },
    );
  }

  // Zod first (clearer error messages), then a server-side re-check
  // via normalizeDismissInput which the audit-write helper uses for
  // its internal validation. Both run; the second is a no-op when
  // the first passes, but it documents the contract.
  const parsed = dismissInputSchema.safeParse(raw);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "invalid_input", details: parsed.error.flatten() },
      { status: 400 },
    );
  }
  let normalized;
  try {
    normalized = normalizeDismissInput(parsed.data);
  } catch (err) {
    return NextResponse.json(
      {
        error: "invalid_input",
        detail: err instanceof Error ? err.message : String(err),
      },
      { status: 400 },
    );
  }

  // Tenant-scoped encounter lookup — same shape as accept.
  const encounter = await prisma.encounter.findFirst({
    where: { id: encounterId, tenantId: tenant.id },
    select: { id: true, patientHash: true },
  });
  if (!encounter) {
    return NextResponse.json({ error: "encounter_not_found" }, { status: 404 });
  }

  try {
    const result = await prisma.$transaction(async (tx) => {
      return writeAuditEntry({
        tenantId: tenant.id,
        encounterId,
        findingId,
        userIdentifier: session.user.id,
        action: "dismiss",
        reason: normalized.reason,
        reasonText: normalized.reasonText,
        patientHash: encounter.patientHash,
        modelRunId: "portal-review",
        tx,
      });
    });
    return NextResponse.json({
      ok: true,
      findingId,
      newStatus: result.newFindingStatus,
      reason: normalized.reason,
      reasonText: normalized.reasonText,
      auditEventId: result.eventId,
      cryptographicSignature: result.cryptographicSignature,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown error";
    if (message.includes("already accepted") || message.includes("already dismissed")) {
      return NextResponse.json(
        { error: "finding_terminal", detail: message },
        { status: 409 },
      );
    }
    if (message.includes("not found")) {
      return NextResponse.json(
        { error: "finding_not_found", detail: message },
        { status: 404 },
      );
    }
    console.error("[dismiss] audit write failed", err);
    return NextResponse.json(
      { error: "audit_write_failed", detail: message },
      { status: 500 },
    );
  }
}
