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
// The export is logged itself — every successful call writes an
// `audit_log_export` row to the chain so the privacy officer can
// see who pulled what, when. See the note further down for why that
// row carries a synthetic finding/encounter key.

import { type NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { assertMembershipCapability } from "@/lib/membership-gate";
import { resolveAuditExportAnchor } from "@/lib/audit-export-anchor";
import { writeAuditExportEntry } from "@/lib/audit-write";
import { prisma } from "@/lib/prisma";
import {
  decryptPortalNullableString,
  decryptPortalString,
} from "@/lib/data-encryption";

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
  // Role gate: the audit chain is the most sensitive artifact the
  // tenant stores (every accept/dismiss action, reason text, patient
  // hash, and prior signature), so this route requires the `read`
  // capability like its sibling exports (encounters/export,
  // findings/export, usage). Disabled members and non-members are
  // rejected by the helper.
  const gate = await assertMembershipCapability(
    session.user.id,
    tenant.id,
    "read",
  );
  if (!gate.ok) {
    return NextResponse.json(
      { error: gate.error ?? "forbidden" },
      { status: gate.error === "unauthenticated" ? 401 : 403 },
    );
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

  // Hard cap — full-table dumps OOM the Node process on large tenants.
  // Privacy officers with bigger chains should page via `since`/`until`
  // (or a future cursor endpoint). 10k rows ≈ a year of busy-clinic
  // activity at ~25 events/day.
  const EXPORT_ROW_CAP = 10_000;
  const rows = await prisma.auditTrailEntry.findMany({
    where,
    orderBy: [{ timestamp: "asc" }, { eventId: "asc" }],
    take: EXPORT_ROW_CAP,
  });

  // Log the export itself. The self-audit row is written BEFORE the
  // rows are read so the export is on the record even if serialization
  // or the response fails. It is a deliberate exception to
  // "mutate-then-audit": there is no finding state to keep in sync, and
  // a privacy-officer pull is exactly the event the chain must capture.
  // If this write fails we still serve the export (readers must not be
  // locked out by a logging fault) but the response carries
  // `x-audit-export-logged: false` so the omission is visible to the
  // caller instead of silent.
  let exportLogged = true;
  try {
    const anchor = await resolveAuditExportAnchor(tenant.id);
    await writeAuditExportEntry({
      tenantId: tenant.id,
      userIdentifier: session.user.email ?? session.user.id,
      format,
      rowCount: rows.length,
      rowCap: EXPORT_ROW_CAP,
      // Anchor the synthetic keys to a real finding/encounter pair so the
      // two FK relations stay valid and the row does not collide with the
      // `eventId` unique index. The anchor pair is stable per tenant and
      // resolved server-side.
      encounterId: anchor.encounterId,
      findingId: anchor.findingId,
      patientHash: anchor.patientHash,
    });
  } catch (err) {
    exportLogged = false;
    console.error("audit-export self-logging failed", err);
  }

  const exportRows = rows.map((row) => ({
    ...row,
    reasonText: decryptPortalNullableString(row.reasonText),
    dataElements: decryptAuditDataElements(row.dataElements),
  }));

  const loggedHeader = exportLogged ? "true" : "false";

  if (format === "json") {
    return new NextResponse(JSON.stringify(exportRows, null, 2), {
      status: 200,
      headers: {
        "content-type": "application/json",
        "content-disposition": `attachment; filename="audit-${tenant.slug}-${new Date().toISOString().slice(0, 10)}.json"`,
        "x-audit-export-logged": loggedHeader,
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
  for (const r of exportRows) {
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
      "x-audit-export-logged": loggedHeader,
    },
  });
}

function decryptAuditDataElements(value: string): string {
  const parsed = JSON.parse(value) as Record<string, unknown>;
  if (typeof parsed.reasonText === "string") {
    parsed.reasonText = decryptPortalString(parsed.reasonText);
  }
  return JSON.stringify(parsed, Object.keys(parsed).sort());
}
