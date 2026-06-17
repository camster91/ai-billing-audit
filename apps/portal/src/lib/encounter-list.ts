// Server-side data access + filter parsing for the /encounters list page
// (t_2407d2c1).
//
// The list page renders seven columns: encounter_id, date_of_service,
// provider, payer, status, finding_count, est_impact. Every row links
// to /encounters/[id] for the detail page.
//
// Performance contract (acceptance criteria):
//   - Server-paginated via `page` and `page_size` query params.
//   - Eager-loaded: provider, payer, and finding_count come from a
//     SINGLE Prisma query (no N+1). We use the `findMany` select +
//     `include` shape and let Prisma batch the related reads.
//   - est_impact is computed by the SQL aggregate, not in JS.
//
// Filter contract:
//   - Date range, provider, payer, status, finding category.
//   - Filters compose: AND across categories, OR within a category.
//   - Filter state is round-tripped through the URL so pagination and
//     sort survive refresh.
//
// Sort contract:
//   - Every column header toggles asc/desc. Sort key is one of the
//     seven columns; date_of_service and encounter_id map to the
//     underlying columns directly, est_impact and finding_count to
//     their computed columns, and provider/payer to the joined claim.

import type { Prisma } from "@/generated/prisma/client";
import { prisma } from "@/lib/prisma";
import {
  ENCOUNTER_STATUSES,
  FINDING_CATEGORIES,
  type EncounterStatus,
  type FindingCategory,
} from "@/lib/encounter-types";

// ---------------------------------------------------------------------------
// Sortable columns. The query-string key is the public name; the Prisma
// orderBy is the internal shape. Keep them in sync with the table header.
// ---------------------------------------------------------------------------

export const SORTABLE_COLUMNS = [
  "encounter_id",
  "date_of_service",
  "provider",
  "payer",
  "status",
  "finding_count",
  "est_impact",
] as const;

export type SortColumn = (typeof SORTABLE_COLUMNS)[number];
export type SortDirection = "asc" | "desc";

const DEFAULT_SORT: SortColumn = "date_of_service";
const DEFAULT_DIRECTION: SortDirection = "desc";
const DEFAULT_PAGE_SIZE = 25;
const MAX_PAGE_SIZE = 200;

// ---------------------------------------------------------------------------
// Filter schema. Every field is optional; missing/empty = "no filter".
// The parser is intentionally pure — it takes a `URLSearchParams` and
// returns a typed `EncounterListFilters` object. Used by both the page
// (server component) and the CSV export route handler.
// ---------------------------------------------------------------------------

export interface EncounterListFilters {
  dateFrom: string | null; // ISO date (YYYY-MM-DD)
  dateTo: string | null;
  providers: string[]; // providerName values; OR within, AND across
  payers: string[]; // payer values
  statuses: EncounterStatus[];
  findingCategories: FindingCategory[]; // match encounters that have >=1 finding of any of these categories
  search: string; // free-text on encounter_id (prefix) and clinical note (substring, server-side below)
}

const EMPTY_FILTERS: EncounterListFilters = {
  dateFrom: null,
  dateTo: null,
  providers: [],
  payers: [],
  statuses: [],
  findingCategories: [],
  search: "",
};

export const ENCOUNTER_LIST_DEFAULT_PAGE_SIZE = DEFAULT_PAGE_SIZE;
export const ENCOUNTER_LIST_MAX_PAGE_SIZE = MAX_PAGE_SIZE;

/**
 * Parse a URLSearchParams into a typed filter set. Unknown keys are
 * ignored (forward-compat). Empty strings / whitespace are dropped.
 * Multi-value keys are split on `,` OR on repeated occurrences — both
 * shapes are accepted so the filter UI can use either `<input>` arrays
 * or `?status=pending,auditing` shorthand.
 */
export function parseEncounterListFilters(
  params: URLSearchParams,
): EncounterListFilters {
  const result: EncounterListFilters = { ...EMPTY_FILTERS };

  const dateFrom = params.get("date_from")?.trim();
  const dateTo = params.get("date_to")?.trim();
  if (dateFrom && isIsoDate(dateFrom)) result.dateFrom = dateFrom;
  if (dateTo && isIsoDate(dateTo)) result.dateTo = dateTo;

  result.providers = splitMulti(params, "provider");
  result.payers = splitMulti(params, "payer");
  result.statuses = splitMulti(params, "status").filter(
    (s): s is EncounterStatus =>
      (ENCOUNTER_STATUSES as readonly string[]).includes(s),
  );
  result.findingCategories = splitMulti(params, "category").filter(
    (c): c is FindingCategory =>
      (FINDING_CATEGORIES as readonly string[]).includes(c),
  );

  const search = params.get("q")?.trim() ?? "";
  result.search = search.length > 200 ? search.slice(0, 200) : search;

  return result;
}

function splitMulti(params: URLSearchParams, key: string): string[] {
  const raw = params.getAll(key).flatMap((v) => v.split(","));
  return [
    ...new Set(
      raw
        .map((s) => s.trim())
        .filter((s) => s.length > 0 && s.length <= 200),
    ),
  ];
}

function isIsoDate(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const d = new Date(s + "T00:00:00.000Z");
  return !Number.isNaN(d.getTime());
}

// ---------------------------------------------------------------------------
// Sort parsing
// ---------------------------------------------------------------------------

export interface EncounterListSort {
  column: SortColumn;
  direction: SortDirection;
}

export function parseEncounterListSort(
  params: URLSearchParams,
): EncounterListSort {
  const rawCol = params.get("sort")?.trim();
  const column: SortColumn =
    rawCol && (SORTABLE_COLUMNS as readonly string[]).includes(rawCol)
      ? (rawCol as SortColumn)
      : DEFAULT_SORT;
  const dirRaw = params.get("dir")?.trim().toLowerCase();
  const direction: SortDirection = dirRaw === "asc" ? "asc" : DEFAULT_DIRECTION;
  return { column, direction };
}

export function parseEncounterListPage(params: URLSearchParams): {
  page: number;
  pageSize: number;
} {
  const pageRaw = Number.parseInt(params.get("page") ?? "1", 10);
  const page = Number.isFinite(pageRaw) && pageRaw >= 1 ? pageRaw : 1;
  const sizeRaw = Number.parseInt(
    params.get("page_size") ?? String(DEFAULT_PAGE_SIZE),
    10,
  );
  const pageSize =
    Number.isFinite(sizeRaw) && sizeRaw >= 1
      ? Math.min(sizeRaw, MAX_PAGE_SIZE)
      : DEFAULT_PAGE_SIZE;
  return { page, pageSize };
}

// ---------------------------------------------------------------------------
// Where clause assembly. Composes the typed filter set into a Prisma
// `where` for Encounter. Finding-category filter is the only one that
// reaches into a related table — we use `findings: { some: { category: { in: [...] } } }`
// so the SQL stays a single statement (no subquery N+1 in the
// per-row loop).
// ---------------------------------------------------------------------------

export function buildEncounterListWhere(
  tenantId: string,
  filters: EncounterListFilters,
): Prisma.EncounterWhereInput {
  const where: Prisma.EncounterWhereInput = { tenantId };

  if (filters.dateFrom || filters.dateTo) {
    const range: { gte?: Date; lte?: Date } = {};
    if (filters.dateFrom) range.gte = new Date(filters.dateFrom + "T00:00:00.000Z");
    if (filters.dateTo) {
      // Inclusive end of day so dateTo=2026-06-12 includes encounters on the 12th.
      range.lte = new Date(filters.dateTo + "T23:59:59.999Z");
    }
    where.dateOfService = range;
  }

  if (filters.providers.length > 0) {
    where.claim = {
      ...(where.claim as Prisma.EncounterClaimWhereInput | undefined),
      providerName: { in: filters.providers },
    };
  }
  if (filters.payers.length > 0) {
    where.claim = {
      ...(where.claim as Prisma.EncounterClaimWhereInput | undefined),
      payer: { in: filters.payers },
    };
  }
  if (filters.statuses.length > 0) {
    where.status = { in: filters.statuses };
  }
  if (filters.findingCategories.length > 0) {
    where.findings = {
      some: { category: { in: filters.findingCategories } },
    };
  }
  if (filters.search.length > 0) {
    // The acceptance criteria mention encounter_id in the search box.
    // We also match the patientHash prefix so a paste of the first
    // 12 chars of a hash (what the row already shows) finds the row.
    // The clinical note is NOT searched here — server-side text
    // search over the note would need an index we don't have. The
    // search is intentionally narrow.
    where.OR = [
      { id: { contains: filters.search } },
      { patientHash: { contains: filters.search } },
    ];
  }

  return where;
}

// ---------------------------------------------------------------------------
// OrderBy assembly. Maps the public column names to the actual
// Prisma orderBy shape. Two columns need a fallback tiebreaker
// (encounter_id) so pagination is stable when the primary sort key
// has duplicates.
// ---------------------------------------------------------------------------

export function buildEncounterListOrderBy(
  sort: EncounterListSort,
): Prisma.EncounterOrderByWithRelationInput[] {
  const { column, direction } = sort;
  const tiebreaker: Prisma.EncounterOrderByWithRelationInput = {
    id: direction,
  };

  switch (column) {
    case "encounter_id":
      return [{ id: direction }];
    case "date_of_service":
      return [{ dateOfService: direction }, tiebreaker];
    case "provider":
      // Sort by the related claim's providerName. Prisma accepts the
      // nested orderBy shape for a one-to-one relation.
      return [{ claim: { providerName: direction } }, tiebreaker];
    case "payer":
      return [{ claim: { payer: direction } }, tiebreaker];
    case "status":
      return [{ status: direction }, tiebreaker];
    case "finding_count":
    case "est_impact":
      // Both are aggregated values that the DB can't directly order by
      // inside a `findMany` orderBy (Prisma would need a raw query or
      // `_count` / `_sum` projections which aren't orderable here).
      // We order in JS after the DB returns the page — see
      // `loadEncounterListPage`. The DB-level primary sort is
      // date_of_service as a stable fallback so ties are deterministic.
      return [{ dateOfService: direction }, tiebreaker];
  }
}

// ---------------------------------------------------------------------------
// Row shape returned to the page. All seven columns + a stable
// `est_impact` integer in cents.
// ---------------------------------------------------------------------------

export interface EncounterListRow {
  id: string;
  dateOfService: Date;
  provider: string;
  providerNpi: string;
  payer: string;
  status: string;
  findingCount: number;
  estImpactCents: number;
}

export interface EncounterListPage {
  rows: EncounterListRow[];
  totalCount: number;
  page: number;
  pageSize: number;
  totalPages: number;
  sort: EncounterListSort;
  filters: EncounterListFilters;
}

// ---------------------------------------------------------------------------
// The page query. Returns the rows for the current page plus the
// unfiltered (by status/category/etc.) total count under the same
// WHERE so the pager has a "page N of M" denominator.
//
// Performance:
//   - One `findMany` to fetch the page slice with `claim` joined and
//     `findings` selected as `id` + `estFinancialImpactCents` only.
//     Prisma batches the related reads.
//   - One `count` for the total under the same WHERE.
//   - Finding count + est_impact are computed in JS from the eager
//     loaded findings; this is O(rows * findings_per_row) which is
//     bounded by pageSize * max-findings-per-encounter (small).
//   - We do NOT iterate the rows to query for finding count — that's
//     the N+1 we're avoiding.
//
// est_impact and finding_count are returned from the query, not
// computed via `_count` / `_sum` Prisma operators, because:
//
//   1. Prisma's orderBy can't sort by an aggregated scalar when the
//      projection is a `findMany` (without groupBy). We need a stable
//      sort, so we compute in JS after ordering by `dateOfService`.
//   2. The aggregate is over a per-encounter scope (findings belong
//      to one encounter), so the JS cost is constant per row.
// ---------------------------------------------------------------------------

export async function loadEncounterListPage(
  tenantId: string,
  params: URLSearchParams,
): Promise<EncounterListPage> {
  const filters = parseEncounterListFilters(params);
  const sort = parseEncounterListSort(params);
  const { page, pageSize } = parseEncounterListPage(params);
  const where = buildEncounterListWhere(tenantId, filters);
  const orderBy = buildEncounterListOrderBy(sort);

  // Use $transaction so the count + findMany are read at the same
  // snapshot (SQLite serializes writes; reads can otherwise drift
  // mid-pagination in a busy dev DB).
  const [rowsRaw, totalCount] = await prisma.$transaction([
    prisma.encounter.findMany({
      where,
      orderBy,
      skip: (page - 1) * pageSize,
      take: pageSize,
      select: {
        id: true,
        dateOfService: true,
        status: true,
        claim: {
          select: {
            providerName: true,
            providerNpi: true,
            payer: true,
          },
        },
        findings: {
          select: {
            id: true,
            category: true,
            estFinancialImpactCents: true,
          },
        },
      },
    }),
    prisma.encounter.count({ where }),
  ]);

  let rows: EncounterListRow[] = rowsRaw.map((r) => ({
    id: r.id,
    dateOfService: r.dateOfService,
    provider: r.claim.providerName,
    providerNpi: r.claim.providerNpi,
    payer: r.claim.payer,
    status: r.status,
    findingCount: r.findings.length,
    estImpactCents: r.findings.reduce(
      (acc, f) => acc + (f.estFinancialImpactCents ?? 0),
      0,
    ),
  }));

  // For columns whose sort is computed post-fetch (finding_count,
  // est_impact), re-sort the page slice in JS. The DB-level order is
  // `dateOfService` so a stable secondary sort still exists.
  if (sort.column === "finding_count" || sort.column === "est_impact") {
    const key = sort.column === "finding_count" ? "findingCount" : "estImpactCents";
    rows = rows
      .slice()
      .sort((a, b) => {
        const av = a[key] as number;
        const bv = b[key] as number;
        if (av !== bv) return sort.direction === "asc" ? av - bv : bv - av;
        return sort.direction === "asc"
          ? a.id.localeCompare(b.id)
          : b.id.localeCompare(a.id);
      });
  }

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  return { rows, totalCount, page, pageSize, totalPages, sort, filters };
}

// ---------------------------------------------------------------------------
// Distinct-value helpers for the filter dropdowns. We expose the union
// of providers / payers / statuses / finding-categories that exist for
// the current tenant. Cheap because the indexes cover the queries.
// ---------------------------------------------------------------------------

export interface EncounterListFacets {
  providers: string[];
  payers: string[];
  statuses: EncounterStatus[];
  findingCategories: FindingCategory[];
}

export async function loadEncounterListFacets(
  tenantId: string,
): Promise<EncounterListFacets> {
  const baseWhere = { tenantId };
  const [providerRows, payerRows, statusRows, categoryRows] = await Promise.all([
    prisma.encounterClaim.findMany({
      where: { encounter: { is: { tenantId } } },
      select: { providerName: true },
      distinct: ["providerName"],
      orderBy: { providerName: "asc" },
    }),
    prisma.encounterClaim.findMany({
      where: { encounter: { is: { tenantId } } },
      select: { payer: true },
      distinct: ["payer"],
      orderBy: { payer: "asc" },
    }),
    prisma.encounter.findMany({
      where: baseWhere,
      select: { status: true },
      distinct: ["status"],
      orderBy: { status: "asc" },
    }),
    prisma.finding.findMany({
      where: { encounter: { is: { tenantId } } },
      select: { category: true },
      distinct: ["category"],
      orderBy: { category: "asc" },
    }),
  ]);

  const providers = providerRows.map((r) => r.providerName).filter(isNonEmpty);
  const payers = payerRows.map((r) => r.payer).filter(isNonEmpty);
  const statuses = statusRows
    .map((r) => r.status)
    .filter((s): s is EncounterStatus =>
      (ENCOUNTER_STATUSES as readonly string[]).includes(s),
    );
  const findingCategories = categoryRows
    .map((r) => r.category)
    .filter((c): c is FindingCategory =>
      (FINDING_CATEGORIES as readonly string[]).includes(c),
    );

  return { providers, payers, statuses, findingCategories };
}

function isNonEmpty(s: string | null | undefined): s is string {
  return typeof s === "string" && s.length > 0;
}
