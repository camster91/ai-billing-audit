// POST /api/encounters/[id]/findings/[findingId]/accept
//
// Marks a finding as accepted by the current user. Writes exactly one
// row to the audit_trail chain inside a single transaction and updates
// the finding's status. Idempotent on repeat (returns 409) — accepted
// findings are terminal.
//
// Authorization: owner | auditor | admin can accept. Viewers
// receive 403 (role enforcement from t_23bfd49c — accept is
// the read-side mutation the spec allows for auditors).

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { writeAuditEntry } from "@/lib/audit-write";
import { acceptInputSchema } from "@/lib/encounter-types";
import { assertMembershipCapability } from "@/lib/membership-gate";

interface RouteContext {
  params: Promise<{ id: string; findingId: string }>;
}

export async function POST(
  _request: Request,
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

  // Role check (t_23bfd49c): accept requires the
  // "accept_or_dismiss" capability — auditor and above, not viewer.
  const gate = await assertMembershipCapability(
    session.user.id,
    tenant.id,
    "accept_or_dismiss",
  );
  if (!gate.ok) {
    return NextResponse.json({ error: gate.error ?? "forbidden" }, { status: 403 });
  }

  // Empty body — `acceptInputSchema` is {} but the strict() call rejects
  // unknown keys, so a stale client sending junk gets a 400.
  let body: unknown = {};
  try {
    const raw = await _request.json();
    if (raw !== null && raw !== undefined) body = raw;
  } catch {
    // Empty body is fine for accept; the client can omit it.
  }
  const parsed = acceptInputSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "invalid_input", details: parsed.error.flatten() },
      { status: 400 },
    );
  }

  // Look up the encounter and finding in tenant scope. Use a single
  // round-trip so the tenant check can't drift between the two reads.
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
        action: "accept",
        reason: null,
        reasonText: null,
        patientHash: encounter.patientHash,
        modelRunId: "portal-review",
        tx,
      });
    });
    return NextResponse.json({
      ok: true,
      findingId,
      newStatus: result.newFindingStatus,
      auditEventId: result.eventId,
      cryptographicSignature: result.cryptographicSignature,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown error";
    if (message.includes("already accepted") || message.includes("already dismissed")) {
      return NextResponse.json(
        { error: "finding_terminal" },
        { status: 409 },
      );
    }
    if (message.includes("not found")) {
      return NextResponse.json(
        { error: "finding_not_found" },
        { status: 404 },
      );
    }
    console.error("[accept] audit write failed", err);
    return NextResponse.json(
      { error: "audit_write_failed" },
      { status: 500 },
    );
  }
}
