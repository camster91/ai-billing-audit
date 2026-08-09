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

import type { Metadata } from "next";
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
import {
  EmptyStateCTA,
  onboardingWizardHref,
} from "@/components/EmptyStateCTA";
import styles from "../shell.module.css";

export const metadata: Metadata = {
  // Authenticated portal page — must stay out of search engine indexes.
  // Overrides the root layout's `robots: { index: true, follow: true }`.
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** Page size for the findings inbox. Keeps memory bounded while
 *  still showing a useful work queue. */
const FINDINGS_PAGE_SIZE = 50;

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

function parsePage(value: string | undefined): number {
  const n = Number(value);
  if (!Number.isInteger(n) || n < 1) return 1;
  return Math.min(n, 10_000);
}

function buildFindingsHref(args: {
  status: string;
  categories: string[];
  providers: string[];
  payers: string[];
  page: number;
}): string {
  const params = new URLSearchParams();
  params.set("status", args.status);
  for (const c of args.categories) params.append("category", c);
  for (const p of args.providers) params.append("provider", p);
  for (const p of args.payers) params.append("payer", p);
  if (args.page > 1) params.set("page", String(args.page));
  const qs = params.toString();
  return qs ? `/findings?${qs}` : "/findings";
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
  const page = parsePage(firstString(sp.page));

  const tenant = await getActiveTenant();

  // Tenant-level encounter count, used to disambiguate the empty
  // state: a fresh tenant (0 encounters) gets an "upload your first
  // encounter" CTA, while a tenant with encounters but no findings
  // matching the filter keeps the existing "adjust filters" copy.
  const encounterCount = tenant
    ? await prisma.encounter.count({ where: { tenantId: tenant.id } })
    : 0;

  const findingWhere = tenant
    ? {
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
      }
    : null;

  const totalMatching = findingWhere
    ? await prisma.finding.count({ where: findingWhere })
    : 0;
  const totalPages = Math.max(1, Math.ceil(totalMatching / FINDINGS_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);

  // Single Prisma round-trip: findings + their encounter's claim
  // (for provider/payer display). Eager-loaded so the inbox render
  // is a single query, not N+1. Paginated so large tenants cannot
  // pull unbounded rows into memory.
  const findings = findingWhere
    ? await prisma.finding.findMany({
        where: findingWhere,
        orderBy: [{ estFinancialImpactCents: "desc" }, { id: "asc" }],
        skip: (safePage - 1) * FINDINGS_PAGE_SIZE,
        take: FINDINGS_PAGE_SIZE,
        select: {
          id: true,
          encounterId: true,
          category: true,
          billingRuleReference: true,
          currentCode: true,
          suggestedCode: true,
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

  const rangeStart =
    totalMatching === 0 ? 0 : (safePage - 1) * FINDINGS_PAGE_SIZE + 1;
  const rangeEnd = Math.min(safePage * FINDINGS_PAGE_SIZE, totalMatching);

  return (
    <main id="main" className={styles.shell}>
      {tenant ? <PortalNav current="/findings" tenant={tenant} /> : null}

      <h1 className={styles.heading}>Findings</h1>
      <p className={styles.subheading}>
        {tenant
          ? `Showing ${rangeStart}–${rangeEnd} of ${totalMatching} ${status} finding${totalMatching === 1 ? "" : "s"} for ${tenant.name}. Sort: estimated impact, highest first. Select rows to bulk-accept or bulk-dismiss.`
          : "Tenant scope required to view findings."}
      </p>

      {!tenant ? (
        <section className={styles.empty}>
          <h2>No clinic connected</h2>
          <p>You aren&rsquo;t a member of a clinic yet.</p>
        </section>
      ) : encounterCount === 0 ? (
        // Fresh tenant: no encounters at all, so the existing
        // "Nothing in this view — adjust filters" copy is wrong.
        // Replace with an onboarding CTA that drives the user to
        // upload an encounter (the only way to generate findings).
        <EmptyStateCTA
          variant="block"
          testId="findings-fresh-tenant-cta"
          title="No findings yet"
          description="Findings appear here as soon as the auditor reviews an encounter. Upload a clinical note to get started."
          primaryAction={{
            label: "Upload your first encounter",
            href: onboardingWizardHref(),
            testId: "findings-upload-first-encounter",
          }}
          secondaryAction={{
            label: "View encounters",
            href: "/encounters",
            testId: "findings-view-encounters",
          }}
        />
      ) : (
        <>
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
          {totalPages > 1 ? (
            <nav
              aria-label="Findings pagination"
              style={{
                display: "flex",
                gap: 16,
                alignItems: "center",
                marginTop: 24,
                fontSize: 14,
              }}
            >
              {safePage > 1 ? (
                <Link
                  href={buildFindingsHref({
                    status,
                    categories,
                    providers,
                    payers,
                    page: safePage - 1,
                  })}
                >
                  Previous
                </Link>
              ) : (
                <span aria-disabled="true">Previous</span>
              )}
              <span>
                Page {safePage} of {totalPages}
              </span>
              {safePage < totalPages ? (
                <Link
                  href={buildFindingsHref({
                    status,
                    categories,
                    providers,
                    payers,
                    page: safePage + 1,
                  })}
                >
                  Next
                </Link>
              ) : (
                <span aria-disabled="true">Next</span>
              )}
            </nav>
          ) : null}
        </>
      )}

      <p className={styles.muted} style={{ marginTop: 32, fontSize: 12 }}>
        Need to look at the underlying claim? Open a finding from the
        table to jump to its <Link href="/encounters">encounter</Link>.
      </p>
    </main>
  );
}
