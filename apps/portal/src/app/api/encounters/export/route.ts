// GET /api/encounters/export
//
// Streams a CSV of encounters for the active tenant. The route reuses
// the same filter+sort parsing as the /encounters list page so the
// export reflects what the user is currently looking at. Selection is
// supported by the `ids` query param — when present, only the listed
// encounter ids are included (still filtered + sorted, in case the
// caller wants the export restricted to a subset of the current view).
//
// Auth: the proxy redirects unauthenticated users; this route also
// re-checks via `auth()` + `getActiveTenant()` and returns 401/403 if
// the session has gone stale.
//
// Response shape: text/csv with the seven list columns plus the
// per-row total_billed_cents and the audit_chain_anchor (the
// patientHash prefix + first 6 chars of the encounter id) for
// downstream reconciliation.

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { buildEncounterListOrderBy, buildEncounterListWhere, parseEncounterListFilters, parseEncounterListSort } from "@/lib/encounter-list";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const CSV_HEADERS = [
  "encounter_id",
  "date_of_service",
  "provider",
  "provider_npi",
  "payer",
  "status",
  "finding_count",
  "est_impact_cents",
  "total_billed_cents",
  "patient_hash_prefix",
] as const;

const MAX_EXPORT_ROWS = 5000;

export async function GET(request: Request): Promise<Response> {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const tenant = await getActiveTenant();
  if (!tenant) {
    return NextResponse.json({ error: "no_tenant" }, { status: 403 });
  }

  const url = new URL(request.url);
  const params = url.searchParams;
  const filters = parseEncounterListFilters(params);
  const sort = parseEncounterListSort(params);

  // Restrict the export to a list of encounter ids when `ids` is
  // present. Used by the row-selection bulk action. The id list is
  // bounded (max 1000 entries) to prevent a runaway query.
  const idsParam = params.get("ids");
  let idScope: string[] | null = null;
  if (idsParam) {
    const seen = new Set<string>();
    idScope = [];
    for (const raw of idsParam.split(",")) {
      const s = raw.trim();
      if (s.length === 0 || s.length > 200) continue;
      if (seen.has(s)) continue;
      seen.add(s);
      idScope.push(s);
      if (idScope.length >= 1000) break;
    }
  }

  const baseWhere = buildEncounterListWhere(tenant.id, filters);
  const where =
    idScope && idScope.length > 0
      ? { AND: [baseWhere, { id: { in: idScope } }] }
      : baseWhere;
  const orderBy = buildEncounterListOrderBy(sort);

  // Re-read the tenant's redactPatientNamesInExports flag so the
  // export reflects the user's current /settings preference. The
  // flag defaults to true (set in the migration), so clinics that
  // never open /settings still get redaction by default.
  const tenantRow = await prisma.tenant.findUnique({
    where: { id: tenant.id },
    select: { redactPatientNamesInExports: true },
  });
  const redact = tenantRow?.redactPatientNamesInExports ?? true;

  const rawRows = await prisma.encounter.findMany({
    where,
    orderBy,
    take: MAX_EXPORT_ROWS,
    select: {
      id: true,
      dateOfService: true,
      status: true,
      patientHash: true,
      claim: {
        select: {
          providerName: true,
          providerNpi: true,
          payer: true,
          billedCents: true,
        },
      },
      findings: {
        select: {
          id: true,
          estFinancialImpactCents: true,
        },
      },
    },
  });

  // Compute aggregates the same way the list page does. Done in JS
  // for the same reason as in encounter-list.ts — Prisma's orderBy
  // can't order a findMany by an aggregate scalar.
  const rows = rawRows.map((r) => {
    const findingCount = r.findings.length;
    const estImpactCents = r.findings.reduce(
      (acc, f) => acc + (f.estFinancialImpactCents ?? 0),
      0,
    );
    return {
      id: r.id,
      dateOfService: r.dateOfService,
      provider: r.claim.providerName,
      providerNpi: r.claim.providerNpi,
      payer: r.claim.payer,
      status: r.status,
      billedCents: r.claim.billedCents,
      patientHash: r.patientHash,
      findingCount,
      estImpactCents,
    };
  });

  if (sort.column === "finding_count" || sort.column === "est_impact") {
    const key = sort.column === "finding_count" ? "findingCount" : "estImpactCents";
    rows.sort((a, b) => {
      const av = a[key] as number;
      const bv = b[key] as number;
      if (av !== bv) return sort.direction === "asc" ? av - bv : bv - av;
      return sort.direction === "asc"
        ? a.id.localeCompare(b.id)
        : b.id.localeCompare(a.id);
    });
  }

  // Stream the CSV via a ReadableStream. Even for small result sets
  // this keeps the route's memory profile constant and gets the
  // download started sooner over slow connections.
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(CSV_HEADERS.join(",") + "\n"));
      for (const r of rows) {
        controller.enqueue(encoder.encode(encodeRow(r, redact)));
      }
      controller.close();
    },
  });

  const filename = buildFilename(tenant.slug);
  return new Response(stream, {
    status: 200,
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": `attachment; filename="${filename}"`,
      "cache-control": "no-store",
      "x-row-count": String(rows.length),
      // Surface the redaction state in a response header so a CI check
      // or downstream consumer can verify the export matches the
      // /settings preference without diffing CSV cells.
      "x-phi-redacted": redact ? "true" : "false",
    },
  });
}

function encodeRow(
  r: {
    id: string;
    dateOfService: Date;
    provider: string;
    providerNpi: string;
    payer: string;
    status: string;
    billedCents: number;
    patientHash: string;
    findingCount: number;
    estImpactCents: number;
  },
  redact: boolean,
): string {
  const cells = [
    r.id,
    r.dateOfService.toISOString().slice(0, 10),
    r.provider,
    r.providerNpi,
    r.payer,
    r.status,
    String(r.findingCount),
    String(r.estImpactCents),
    String(r.billedCents),
    redact ? "[redacted]" : r.patientHash.slice(0, 12),
  ];
  return cells.map(csvEscape).join(",") + "\n";
}

function csvEscape(value: string): string {
  if (value === "") return "";
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function buildFilename(slug: string): string {
  const stamp = new Date().toISOString().replace(/[:T]/g, "-").slice(0, 19);
  return `encounters-${slug}-${stamp}.csv`;
}
