// POST /api/findings/bulk/dismiss
//
// Dismisses every finding in `findingIds` with the SAME reason in a
// single Prisma transaction. Mirrors /api/findings/bulk/accept but
// with the dismiss reason payload required by the inbox modal
// (`reason: DismissReason`, optional `reasonText`).
//
// The reason and reasonText are the same for every row in the batch
// — the inbox UI does not currently support per-finding dismissal
// reasons inside a bulk action. Persisted on each row's
// `AuditTrailEntry.reason` / `reasonText` (so the per-finding history
// is consistent) and on each `Finding.dismissReason` / `dismissText`
// (so the encounter view is consistent).
//
// Scoping, terminal-state, and missing-id handling are identical to
// bulk-accept: a single bad id rolls the entire transaction back.

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { writeAuditBatch } from "@/lib/audit-write";
import { bulkDismissInputSchema } from "@/lib/encounter-types";

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
  const parsed = bulkDismissInputSchema.safeParse(raw);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "invalid_input", details: parsed.error.flatten() },
      { status: 400 },
    );
  }
  const reason = parsed.data.reason;
  const reasonText =
    reason === "other_with_text"
      ? (parsed.data.reasonText ?? null)
      : null;
  if (reason === "other_with_text" && (!reasonText || reasonText.trim().length === 0)) {
    return NextResponse.json(
      {
        error: "invalid_input",
        detail: "reasonText is required when reason is other_with_text",
      },
      { status: 400 },
    );
  }

  // De-dupe ids. Preserve first-seen order so the chain walk is
  // deterministic.
  const findingIds: string[] = [];
  const seen = new Set<string>();
  for (const id of parsed.data.findingIds) {
    if (seen.has(id)) continue;
    seen.add(id);
    findingIds.push(id);
  }

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

  const bulkActionId = cryptoRandomId();

  try {
    const result = await prisma.$transaction(async (tx) => {
      return writeAuditBatch({
        tenantId: tenant.id,
        userIdentifier: session.user.id,
        action: "dismiss",
        bulkActionId,
        items: findings.map((f) => ({
          encounterId: f.encounterId,
          findingId: f.id,
          patientHash: f.encounter.patientHash,
          reason,
          reasonText,
        })),
        tx,
      });
    });

    return NextResponse.json({
      ok: true,
      bulkActionId: result.bulkActionId,
      reason,
      reasonText,
      dismissedFindingIds: result.perItem.map((p) => p.findingId),
      perFinding: result.perItem.map((p) => ({
        findingId: p.findingId,
        auditEventId: p.auditEventId,
        signature: p.cryptographicSignature,
      })),
    });
  } catch (err) {
    console.error("[bulk/dismiss] audit write failed", err);
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
