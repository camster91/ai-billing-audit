// GET /api/findings/export
//
// Streams a CSV of the action plan for the billing team. Mirrors the
// filter+sort contract of the /findings inbox page so the export
// reflects the current view: same status default (pending), same
// category / provider / payer filter semantics, same default sort
// (estimated impact, desc).
//
// Each row in the CSV corresponds to a single Finding the biller
// should act on. The columns are tuned for the billing team: each
// row carries the encounter id + date, provider, payer, the code
// change being recommended, the evidence quote (truncated to 200
// chars so the file stays a reasonable size for Excel), and the
// estimated impact in dollars.
//
// Auth: the proxy redirects unauthenticated users; this route also
// re-checks via `auth()` + `getActiveTenant()` and returns 401/403
// if the session has gone stale. Role gate (t_23bfd49c): any
// active member with the `read` capability (viewer / auditor /
// owner / admin) can export. Disabled members and non-members
// receive 403.
//
// Scoping: every row's `encounter.tenantId` must equal the active
// tenant. The single SELECT uses an `in:` filter on the encounter
// ids (which the inbox page just queried for the current view)
// so the export is bounded by what the user is actually looking at.

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { FINDING_CATEGORY_LABEL, FINDING_STATUSES } from "@/lib/encounter-types";
import { assertMembershipCapability } from "@/lib/membership-gate";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const CSV_HEADERS = [
  "finding_id",
  "encounter_id",
  "date_of_service",
  "category",
  "category_label",
  "current_code",
  "suggested_code",
  "billing_rule_reference",
  "evidence_quote",
  "provider",
  "provider_npi",
  "payer",
  "est_impact_cents",
  "status",
  "patient_hash_prefix",
] as const;

const MAX_EXPORT_ROWS = 5000;
const EVIDENCE_QUOTE_CSV_MAX = 200;

export async function GET(request: Request): Promise<Response> {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const tenant = await getActiveTenant();
  if (!tenant) {
    return NextResponse.json({ error: "no_tenant" }, { status: 403 });
  }
  // Role gate (t_23bfd49c): export is a read — every active
  // member role qualifies.
  const gate = await assertMembershipCapability(
    session.user.id,
    tenant.id,
    "read",
  );
  if (!gate.ok) {
    return NextResponse.json(
      { error: gate.error ?? "forbidden" },
      { status: 403 },
    );
  }

  const url = new URL(request.url);
  const params = url.searchParams;

  // Same filter parsing shape as the /findings page: status defaults
  // to "pending"; category is multi-select; payer is multi-select;
  // provider is multi-select (matches on claim.providerName). All
  // unknown keys are silently dropped — the page does the same.
  const statusParam = params.get("status")?.trim();
  const status: "pending" | "accepted" | "dismissed" =
    statusParam && (FINDING_STATUSES as readonly string[]).includes(statusParam)
      ? (statusParam as "pending" | "accepted" | "dismissed")
      : "pending";

  const categories = splitMulti(params, "category");
  const payers = splitMulti(params, "payer");
  const providers = splitMulti(params, "provider");

  // Default sort = est_impact desc, tiebreaker finding_id asc.
  // Other values are accepted (`date`, `code`) for future use; the
  // accepted set lives next to the inbox page so the two surfaces
  // stay in sync. Direction is always desc on the impact default —
  // the biller wants the biggest $ opportunities first.
  const sort = parseSort(params.get("sort")?.trim());

  // Build the WHERE clause. Status is always set (defaults to pending
  // above) so we never accidentally export every row in the tenant.
  const where = {
    status,
    encounter: { tenantId: tenant.id },
    ...(categories.length > 0 ? { category: { in: categories } } : {}),
    ...(payers.length > 0 || providers.length > 0
      ? {
          encounter: {
            tenantId: tenant.id,
            ...(payers.length > 0 ? { claim: { payer: { in: payers } } } : {}),
            ...(providers.length > 0
              ? {
                  claim: {
                    ...(payers.length > 0 ? { payer: { in: payers } } : {}),
                    providerName: { in: providers },
                  },
                }
              : {}),
          },
        }
      : {}),
  };

  // Sort key resolution. `est_impact` and `date` are scalar columns
  // and go straight into the Prisma orderBy. `code` sorts by the
  // suggested code (then current) — useful when the biller wants to
  // see all "99213 → 99214" recommendations grouped together.
  const orderBy: { [k: string]: "asc" | "desc" }[] =
    sort.column === "date"
      ? [{ createdAt: sort.direction }, { id: "asc" }]
      : sort.column === "code"
        ? [
            { suggestedCode: sort.direction },
            { currentCode: sort.direction },
            { id: "asc" },
          ]
        : [
            { estFinancialImpactCents: sort.direction },
            { id: "asc" },
          ];

  // Re-read the tenant's redactPatientNamesInExports flag so the
  // export reflects the user's current /settings preference. Same
  // default-to-on contract as the encounters export.
  const tenantRow = await prisma.tenant.findUnique({
    where: { id: tenant.id },
    select: { redactPatientNamesInExports: true },
  });
  const redact = tenantRow?.redactPatientNamesInExports ?? true;

  const rows = await prisma.finding.findMany({
    where,
    orderBy,
    take: MAX_EXPORT_ROWS,
    select: {
      id: true,
      encounterId: true,
      category: true,
      billingRuleReference: true,
      currentCode: true,
      suggestedCode: true,
      evidenceQuote: true,
      estFinancialImpactCents: true,
      status: true,
      encounter: {
        select: {
          dateOfService: true,
          patientHash: true,
          claim: {
            select: {
              payer: true,
              providerName: true,
              providerNpi: true,
            },
          },
        },
      },
    },
  });

  const CATEGORY_LABEL = FINDING_CATEGORY_LABEL as Record<string, string>;

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(CSV_HEADERS.join(",") + "\n"));
      for (const r of rows) {
        controller.enqueue(
          encoder.encode(
            encodeRow(
              {
                id: r.id,
                encounterId: r.encounterId,
                dateOfService: r.encounter.dateOfService,
                category: r.category,
                categoryLabel: CATEGORY_LABEL[r.category] ?? r.category,
                currentCode: r.currentCode,
                suggestedCode: r.suggestedCode,
                ruleRef: r.billingRuleReference,
                evidenceQuote: r.evidenceQuote,
                payer: r.encounter.claim.payer,
                providerName: r.encounter.claim.providerName,
                providerNpi: r.encounter.claim.providerNpi,
                estImpactCents: r.estFinancialImpactCents,
                status: r.status,
                patientHash: r.encounter.patientHash,
              },
              redact,
            ),
          ),
        );
      }
      controller.close();
    },
  });

  const filename = buildFilename(tenant.slug, status);
  return new Response(stream, {
    status: 200,
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": `attachment; filename="${filename}"`,
      "cache-control": "no-store",
      "x-row-count": String(rows.length),
      "x-phi-redacted": redact ? "true" : "false",
    },
  });
}

function splitMulti(params: URLSearchParams, key: string): string[] {
  const raw = params.getAll(key).flatMap((v) => v.split(","));
  const out: string[] = [];
  const seen = new Set<string>();
  for (const s of raw) {
    const t = s.trim();
    if (t.length === 0 || t.length > 200) continue;
    if (seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

function parseSort(raw: string | undefined): {
  column: "impact" | "date" | "code";
  direction: "asc" | "desc";
} {
  const column: "impact" | "date" | "code" =
    raw === "date" || raw === "code" ? raw : "impact";
  // Direction is always desc on the impact default — the biller
  // wants the biggest $ opportunities first. (Future toggle support
  // can read the `dir` URL param here; the page surface flips it.)
  return { column, direction: "desc" };
}

interface ExportRow {
  id: string;
  encounterId: string;
  dateOfService: Date;
  category: string;
  categoryLabel: string;
  currentCode: string | null;
  suggestedCode: string | null;
  ruleRef: string;
  evidenceQuote: string;
  payer: string;
  providerName: string;
  providerNpi: string;
  estImpactCents: number;
  status: string;
  patientHash: string;
}

function encodeRow(r: ExportRow, redact: boolean): string {
  const evidence =
    r.evidenceQuote.length > EVIDENCE_QUOTE_CSV_MAX
      ? r.evidenceQuote.slice(0, EVIDENCE_QUOTE_CSV_MAX - 1) + "…"
      : r.evidenceQuote;
  const cells = [
    r.id,
    r.encounterId,
    r.dateOfService.toISOString().slice(0, 10),
    r.category,
    r.categoryLabel,
    r.currentCode ?? "",
    r.suggestedCode ?? "",
    r.ruleRef,
    evidence,
    r.providerName,
    r.providerNpi,
    r.payer,
    String(r.estImpactCents),
    r.status,
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

function buildFilename(slug: string, status: string): string {
  const stamp = new Date().toISOString().replace(/[:T]/g, "-").slice(0, 19);
  return `findings-${status}-${slug}-${stamp}.csv`;
}
