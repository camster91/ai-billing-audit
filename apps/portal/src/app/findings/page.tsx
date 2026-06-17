// /findings — bulk-action findings inbox.
//
// Server component: tenant-scoped read of pending findings with the
// filter facets needed to populate the dropdowns. The interactive
// parts (multi-select, modals, filter submissions) live in
// `_components/findings-inbox.tsx` (a Client Component) so this
// page stays cacheable as a pure data loader.
//
// Status filter via `?status=pending|accepted|dismissed` query
// param. Default is `pending` so the page is the work queue on
// first load. Filters for category, provider, and payer compose
// (AND across filters, OR within a multi-select) — see
// `parseFindingsInboxFilters` in the client component.
//
// Sort: the inbox always sorts by `estFinancialImpactCents` desc
// (highest impact first) per the task brief; the user can re-sort
// in a follow-up. The export endpoint mirrors this default.

import { redirect } from "next/navigation";
import Link from "next/link";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import {
  FINDING_CATEGORY_LABEL,
  FINDING_STATUSES,
  type FindingCategory,
} from "@/lib/encounter-types";
import { PortalNav } from "../portal-nav";
import { FindingsInbox } from "./_components/findings-inbox";
import styles from "../shell.module.css";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

function isValidStatus(value: string | undefined): value is
  | "pending"
  | "accepted"
  | "dismissed" {
  return FINDING_STATUSES.includes(
    value as "pending" | "accepted" | "dismissed",
  );
}

function firstString(
  value: string | string[] | undefined,
): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}

function toList(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  if (Array.isArray(value)) {
    return value.flatMap((v) => v.split(",")).map((s) => s.trim()).filter(Boolean);
  }
  return value.split(",").map((s) => s.trim()).filter(Boolean);
}

export default async function FindingsPage({ searchParams }: PageProps) {
  const session = await auth();
  if (!session?.user?.id) {
    redirect("/login?callbackUrl=/findings");
  }

  const sp = await searchParams;
  const statusParam = firstString(sp.status);
  const status: "pending" | "accepted" | "dismissed" = isValidStatus(statusParam)
    ? statusParam
    : "pending";
  const categories = toList(sp.category);
  const payers = toList(sp.payer);
  const providers = toList(sp.provider);

  const tenant = await getActiveTenant();

  // Single Prisma round-trip: findings + their encounter's claim
  // (for provider/payer display). Eager-loaded so the inbox render
  // is a single query, not N+1.
  const findings = tenant
    ? await prisma.finding.findMany({
        where: {
          status,
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
          ...(categories.length > 0 ? { category: { in: categories } } : {}),
        },
        orderBy: [{ estFinancialImpactCents: "desc" }, { id: "asc" }],
        take: 500,
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
      })
    : [];

  // Facets: distinct providers + payers across the same tenant
  // scope, restricted to the active status so the dropdowns
  // reflect "what can I actually filter to". Pulled in two
  // groupBys for clarity — both are O(n) over the same set of
  // claims.
  let providerOptions: string[] = [];
  let payerOptions: string[] = [];
  if (tenant) {
    const groups = await prisma.encounterClaim.groupBy({
      by: ["providerName", "payer"],
      where: { encounter: { tenantId: tenant.id } },
      _count: { _all: true },
    });
    const providers = new Set<string>();
    const payers = new Set<string>();
    for (const g of groups) {
      if (g.providerName) providers.add(g.providerName);
      if (g.payer) payers.add(g.payer);
    }
    providerOptions = [...providers].sort();
    payerOptions = [...payers].sort();
  }

  const initialRows = findings.map((f) => ({
    id: f.id,
    encounterId: f.encounterId,
    dateOfService: f.encounter.dateOfService.toISOString().slice(0, 10),
    category: f.category as FindingCategory,
    billingRuleReference: f.billingRuleReference,
    currentCode: f.currentCode,
    suggestedCode: f.suggestedCode,
    estFinancialImpactCents: f.estFinancialImpactCents,
    providerName: f.encounter.claim.providerName,
    providerNpi: f.encounter.claim.providerNpi,
    payer: f.encounter.claim.payer,
  }));

  return (
    <main className={styles.shell}>
      {tenant ? <PortalNav current="/findings" tenant={tenant} /> : null}

      <h1 className={styles.heading}>Findings</h1>
      <p className={styles.subheading}>
        {tenant
          ? `Showing ${findings.length} ${status} finding${findings.length === 1 ? "" : "s"} for ${tenant.name}. Sort: estimated impact, highest first. Select rows to bulk-accept or bulk-dismiss.`
          : "Tenant scope required to view findings."}
      </p>

      {!tenant ? (
        <section className={styles.empty}>
          <h2>No clinic connected</h2>
          <p>You aren&rsquo;t a member of a clinic yet.</p>
        </section>
      ) : (
        <FindingsInbox
          rows={initialRows}
          categoryOptions={Object.keys(FINDING_CATEGORY_LABEL)}
          providerOptions={providerOptions}
          payerOptions={payerOptions}
          initialStatus={status}
          initialCategories={categories}
          initialProviders={providers}
          initialPayers={payers}
        />
      )}

      <p className={styles.muted} style={{ marginTop: 32, fontSize: 12 }}>
        Need to look at the underlying claim? Open a finding from the
        table to jump to its <Link href="/encounters">encounter</Link>.
      </p>
    </main>
  );
}
