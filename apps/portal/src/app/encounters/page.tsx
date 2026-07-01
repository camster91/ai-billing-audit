// /encounters — server-paginated encounter list page.
//
// Server component: loads the active tenant, the filtered/paged list
// from `loadEncounterListPage`, the available filter facets from
// `loadEncounterListFacets`, and hands everything to the
// `EncounterListClient` interactive component.
//
// Auth: src/proxy.ts redirects unauthenticated users; we still call
// `auth()` so a stale session is caught and the page renders the
// empty state with a clear message.
//
// Performance: `loadEncounterListPage` does two Prisma queries
// (count + findMany with `claim` + `findings` eager-loaded). No
// N+1 — the seven columns come from a single row read.

import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import {
  loadEncounterListFacets,
  loadEncounterListPage,
} from "@/lib/encounter-list";
import { PortalNav } from "../portal-nav";
import { EncounterListClient } from "./_components/encounters-list";
import {
  EmptyStateCTA,
  onboardingWizardHref,
} from "@/components/EmptyStateCTA";
import { EncounterListSkeleton } from "@/components/Skeleton";
import styles from "../shell.module.css";

export const metadata: Metadata = {
  // Authenticated portal page — must stay out of search engine indexes.
  // Overrides the root layout's `robots: { index: true, follow: true }`.
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function EncountersListPage({ searchParams }: PageProps) {
  const session = await auth();
  if (!session?.user?.id) {
    redirect("/login?callbackUrl=/encounters");
  }

  const tenant = await getActiveTenant();
  const paramsResolved = await searchParams;
  const params = new URLSearchParams();

  // The Next.js `searchParams` value can be `string | string[]`. We
  // canonicalize into a flat URLSearchParams. The list helpers expect
  // `?status=pending&status=auditing` to be retrievable via
  // `params.getAll("status")` — getAll on a string works for one
  // value, and we replicate the multi-value with comma-split for
  // repeated keys.
  for (const [key, value] of Object.entries(paramsResolved)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) {
      for (const v of value) params.append(key, v);
    } else {
      params.append(key, value);
    }
  }

  if (!tenant) {
    return (
      <main id="main" className={styles.shell}>
        <h1 className={styles.heading}>Encounters</h1>
        <p className={styles.subheading}>Tenant scope required to view encounters.</p>
        <section className={styles.empty}>
          <h2>No clinic connected</h2>
          <p>You aren&rsquo;t a member of a clinic yet.</p>
        </section>
      </main>
    );
  }

  // Both queries are tenant-scoped, so a missing tenant is the only
  // case that returns empty. Inside the tenant scope we always
  // render the full filter UI, even with zero rows, so the user can
  // see which facets are available.
  const [list, facets] = await Promise.all([
    loadEncounterListPage(tenant.id, params),
    loadEncounterListFacets(tenant.id),
  ]);

  // Serialize the rows to plain primitives before crossing the
  // server/client boundary — Date objects don't survive RSC's
  // serialization intact.
  const rows = list.rows.map((r) => ({
    id: r.id,
    dateOfService: r.dateOfService.toISOString(),
    provider: r.provider,
    providerNpi: r.providerNpi,
    payer: r.payer,
    status: r.status,
    findingCount: r.findingCount,
    estImpactCents: r.estImpactCents,
  }));

  return (
    <main id="main" className={styles.shell}>
      <PortalNav current="/encounters" tenant={tenant} />

      <h1 className={styles.heading}>Encounters</h1>
      <p className={styles.subheading}>
        {list.totalCount === 0
          ? `No encounters for ${tenant.name} match the current filters.`
          : `${list.totalCount} encounter${list.totalCount === 1 ? "" : "s"} for ${tenant.name}.`}
      </p>

      {/* Zero-data CTA — rendered above the filter row so a fresh
          user does not have to interpret the empty filter set as
          "no results, try harder". Only shown when the table is
          actually empty (filter state matches the data state). */}
      {list.totalCount === 0 ? (
        <EmptyStateCTA
          variant="inline"
          testId="encounters-fresh-tenant-cta"
          title="No encounters yet"
          description="Upload a clinical note and the auditor will surface any documentation gaps before you bill."
          primaryAction={{
            label: "Upload your first encounter",
            href: onboardingWizardHref(),
            testId: "encounters-upload-first-encounter",
          }}
          secondaryAction={{
            label: "How it works",
            href: "/how-it-works",
            testId: "encounters-how-it-works",
          }}
        />
      ) : null}

      <Suspense fallback={<EncounterListSkeleton rows={5} />}>
        <EncounterListClient
          rows={rows}
          facets={facets}
          page={list.page}
          pageSize={list.pageSize}
          totalCount={list.totalCount}
          totalPages={list.totalPages}
          sortColumn={list.sort.column}
          sortDirection={list.sort.direction}
          activeFilters={{
            dateFrom: list.filters.dateFrom ?? "",
            dateTo: list.filters.dateTo ?? "",
            providers: list.filters.providers,
            payers: list.filters.payers,
            statuses: list.filters.statuses,
            findingCategories: list.filters.findingCategories,
            search: list.filters.search,
          }}
        />
      </Suspense>
    </main>
  );
}
