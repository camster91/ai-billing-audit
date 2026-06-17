// POST /api/findings/bulk/accept
//
// Accepts every finding in `findingIds` in a single Prisma transaction.
// Writes one row to the audit_trail chain per finding, all sharing
// the same `bulkActionId` (persisted on the new `AuditTrailEntry.bulkActionId`
// column AND embedded in the chain payload's `dataElements` so the
// chain hash includes the grouping identifier).
//
// Scoping: every id must belong to an encounter owned by the active
// tenant. Missing ids (e.g. a stale client) and findings that are
// already in a terminal state cause the entire transaction to roll
// back — the route returns 404 / 409 with the offending ids so the
// client can re-render the inbox without committing a partial batch.
//
// Idempotency: a duplicate POST that re-sends the same `findingIds`
// (all already accepted) is detected by the terminal-state check and
// returns 409 with `already_terminal: [...]`. A retry on a fresh
// (all-pending) inbox completes normally.
//
// Response: 200 with `{ ok: true, bulkActionId, acceptedFindingIds,
// perFinding: [{ findingId, auditEventId, signature }] }`.

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { writeAuditBatch } from "@/lib/audit-write";
import { bulkAcceptInputSchema } from "@/lib/encounter-types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<NextResponse> {
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
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }
  const parsed = bulkAcceptInputSchema.safeParse(raw);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "invalid_input", details: parsed.error.flatten() },
      { status: 400 },
    );
  }
  // De-dupe the input list so the same id twice doesn't fail the
  // terminal check on its own sibling row. Preserve first-seen order
  // so the audit row write order is deterministic.
  const findingIds: string[] = [];
  const seen = new Set<string>();
  for (const id of parsed.data.findingIds) {
    if (seen.has(id)) continue;
    seen.add(id);
    findingIds.push(id);
  }

  // Look up the findings and their parent encounters in one
  // round-trip. The `encounter.tenantId` filter enforces scoping —
  // a user can't smuggle in an id from another tenant and have the
  // route treat it as "not found" silently; the row simply doesn't
  // come back, and the missing-id branch below flags it.
  const findings = await prisma.finding.findMany({
    where: {
      id: { in: findingIds },
      encounter: { tenantId: tenant.id },
    },
    select: {
      id: true,
      status: true,
      encounterId: true,
      encounter: { select: { patientHash: true } },
    },
  });

  const foundIds = new Set(findings.map((f) => f.id));
  const missingIds = findingIds.filter((id) => !foundIds.has(id));
  if (missingIds.length > 0) {
    return NextResponse.json(
      {
        error: "findings_not_found",
        detail: `these ids are missing or not in this tenant: ${missingIds.join(", ")}`,
        missingFindingIds: missingIds,
      },
      { status: 404 },
    );
  }

  const alreadyTerminal = findings
    .filter((f) => f.status !== "pending")
    .map((f) => ({ id: f.id, status: f.status }));
  if (alreadyTerminal.length > 0) {
    return NextResponse.json(
      {
        error: "finding_terminal",
        detail: `${alreadyTerminal.length} finding(s) are not in pending state; refusing to apply a partial batch`,
        alreadyTerminal,
      },
      { status: 409 },
    );
  }

  // Shared bulk action id. 16 bytes -> 32 hex chars; stable for the
  // lifetime of the batch and queryable across the audit log via the
  // `AuditTrailEntry.bulkActionId` index. Embedded in `dataElements`
  // (so it is part of the chain hash) AND persisted on the row.
  const bulkActionId = cryptoRandomId();

  try {
    const result = await prisma.$transaction(async (tx) => {
      return writeAuditBatch({
        tenantId: tenant.id,
        userIdentifier: session.user.id,
        action: "accept",
        bulkActionId,
        items: findings.map((f) => ({
          encounterId: f.encounterId,
          findingId: f.id,
          patientHash: f.encounter.patientHash,
          reason: null,
          reasonText: null,
        })),
        tx,
      });
    });

    return NextResponse.json({
      ok: true,
      bulkActionId: result.bulkActionId,
      acceptedFindingIds: result.perItem.map((p) => p.findingId),
      perFinding: result.perItem.map((p) => ({
        findingId: p.findingId,
        auditEventId: p.auditEventId,
        signature: p.cryptographicSignature,
      })),
    });
  } catch (err) {
    console.error("[bulk/accept] audit write failed", err);
    const message = err instanceof Error ? err.message : "unknown error";
    return NextResponse.json(
      { error: "audit_write_failed", detail: message },
      { status: 500 },
    );
  }
}

function cryptoRandomId(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  let out = "";
  for (let i = 0; i < bytes.length; i++) {
    out += bytes[i]!.toString(16).padStart(2, "0");
  }
  return out;
}
