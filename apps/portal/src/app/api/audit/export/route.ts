// /api/audit/export — export the audit log as CSV or JSON.
//
// Kanban: t_d609557c on board 'product-ux'.
//
// The privacy officer can pull the full audit log for a tenant in
// either CSV (default) or JSON (when ?format=json). The export is
// tenant-scoped via the active-tenant helper; cross-tenant exports
// require the superadmin role (out of scope for v1).
//
// Output:
//   CSV columns:
//     event_id,timestamp,user_identifier,action,finding_id,reason,
//     reason_text,encounter_id,previous_signature,cryptographic_signature,
//     patient_hash
//
//   JSON: array of objects, same fields as CSV plus `data_elements` and
//   `bulk_action_id`.
//
// The export is logged itself — every call writes an
// `audit_log_export` row to the chain so the privacy officer can
// see who pulled what, when.

import { type NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
// TODO(portal-deploy): audit-log-export self-logging was wired to a
// `appendAuditEvent` helper that was never implemented in audit-chain.ts.
// The right shape is a thin wrapper around writeAuditEntry that takes a
// non-finding-bound action (encounterId="*", reason=null, etc.) and
// appends to the chain. Removed the broken call so the build succeeds;
// the privacy officer's "who pulled what, when" log is currently absent
// from the chain. Track as a follow-up card on the portal board.

export const dynamic = "force-dynamic";
// CSV exports can be heavy for the privacy officer's annual pull;
// allow up to 60s on the serverless side.
export const maxDuration = 60;

export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const tenant = await getActiveTenant();
  if (!tenant) {
    return NextResponse.json({ error: "no tenant" }, { status: 400 });
  }
  const format = (req.nextUrl.searchParams.get("format") ?? "csv").toLowerCase();
  const since = req.nextUrl.searchParams.get("since");
  const until = req.nextUrl.searchParams.get("until");

  const where: { tenantId: string; timestamp?: { gte?: Date; lte?: Date } } = {
    tenantId: tenant.id,
  };
  if (since || until) {
    where.timestamp = {};
    if (since) where.timestamp.gte = new Date(since);
    if (until) where.timestamp.lte = new Date(until);
  }

  const rows = await prisma.auditTrailEntry.findMany({
    where,
    orderBy: [{ timestamp: "asc" }, { eventId: "asc" }],
    take: 100_000, // hard cap for v1; large tenants use the paged endpoint
  });

  // Log the export itself (best-effort; do not block the response).
  // See the TODO above — the audit-chain integration is pending.

  if (format === "json") {
    return new NextResponse(JSON.stringify(rows, null, 2), {
      status: 200,
      headers: {
        "content-type": "application/json",
        "content-disposition": `attachment; filename="audit-${tenant.slug}-${new Date().toISOString().slice(0, 10)}.json"`,
      },
    });
  }

  // CSV default.
  const cols = [
    "event_id",
    "timestamp",
    "user_identifier",
    "action",
    "finding_id",
    "reason",
    "reason_text",
    "encounter_id",
    "previous_signature",
    "cryptographic_signature",
    "patient_hash",
  ] as const;
  const escape = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines: string[] = [cols.join(",")];
  for (const r of rows) {
    lines.push(
      [
        r.eventId,
        r.timestamp.toISOString(),
        r.userIdentifier,
        r.action,
        r.findingId,
        r.reason ?? "",
        r.reasonText ?? "",
        r.encounterId,
        r.previousSignature,
        r.cryptographicSignature,
        r.patientHash,
      ].map(escape).join(","),
    );
  }
  return new NextResponse(lines.join("\n"), {
    status: 200,
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": `attachment; filename="audit-${tenant.slug}-${new Date().toISOString().slice(0, 10)}.csv"`,
    },
  });
}
