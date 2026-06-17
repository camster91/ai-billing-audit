// Client-safe constants, types, and small helpers for the
// /encounters list page.
//
// This file is safe to import from a "use client" component — it
// has no Node-only dependencies (no Prisma, no better-sqlite3, no
// filesystem, no `node:module` or `node:crypto`). The pure parser
// logic for the URL query string lives here, shared with the
// server-side data loader in encounter-list.ts.
//
// Rules of engagement:
//   - No imports from `@/lib/prisma`.
//   - No imports from `@/generated/prisma/client` (Prisma runtime).
//   - No `node:*` builtins.
//   - No filesystem access.
//
// Why split from encounter-list.ts:
//   - The list page renders a Server Component (page.tsx) that
//     delegates the interactive parts to a Client Component
//     (encounters-list.tsx). The Client Component needs the column
//     labels, the sort constants, the URL parser, and the formatters
//     so the URL state stays in sync with the server. The Client
//     Component MUST NOT import the Prisma client (better-sqlite3 is
//     a Node native module and will break the webpack client bundle
//     if pulled in transitively — see build error from t_2407d2c1).
//
// Source-of-truth: the canonical sort/filter schema still lives in
// encounter-list.ts. The parser functions are duplicated here
// intentionally — they are 20 lines each and the duplication buys
// us the client/server boundary without an awkward `import type`
// gymnastics. The server module's parsers MUST stay in sync; a
// small set of unit tests in tests/encounter-list.test.ts covers
// both.

import { ENCOUNTER_STATUSES, FINDING_CATEGORIES, type EncounterStatus, type FindingCategory } from "@/lib/encounter-types";

// ---------------------------------------------------------------------------
// Sortable columns + directions
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

export const DEFAULT_SORT: SortColumn = "date_of_service";
export const DEFAULT_SORT_DIRECTION: SortDirection = "desc";
export const DEFAULT_PAGE_SIZE = 25;
export const MAX_PAGE_SIZE = 200;

// ---------------------------------------------------------------------------
// URL query parsing — client-safe. Used by the Client Component to
// initialize controlled inputs and to know which sort indicator to
// draw. The server-side parsers in encounter-list.ts have the same
// behavior; the two are exercised in parallel by
// tests/encounter-list.test.ts.
// ---------------------------------------------------------------------------

export interface EncounterListFilters {
  dateFrom: string | null;
  dateTo: string | null;
  providers: string[];
  payers: string[];
  statuses: EncounterStatus[];
  findingCategories: FindingCategory[];
  search: string;
}

export interface EncounterListSort {
  column: SortColumn;
  direction: SortDirection;
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

export function parseEncounterListFiltersClient(
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

export function parseEncounterListSortClient(
  params: URLSearchParams,
): EncounterListSort {
  const rawCol = params.get("sort")?.trim();
  const column: SortColumn =
    rawCol && (SORTABLE_COLUMNS as readonly string[]).includes(rawCol)
      ? (rawCol as SortColumn)
      : DEFAULT_SORT;
  const dirRaw = params.get("dir")?.trim().toLowerCase();
  const direction: SortDirection = dirRaw === "asc" ? "asc" : DEFAULT_SORT_DIRECTION;
  return { column, direction };
}

export function parseEncounterListPageClient(params: URLSearchParams): {
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

function splitMulti(params: URLSearchParams, key: string): string[] {
  const raw = params.getAll(key).flatMap((v) => v.split(","));
  const seen = new Set<string>();
  const out: string[] = [];
  for (const v of raw) {
    const s = v.trim();
    if (s.length === 0 || s.length > 200) continue;
    if (seen.has(s)) continue;
    seen.add(s);
    out.push(s);
  }
  return out;
}

function isIsoDate(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const d = new Date(s + "T00:00:00.000Z");
  return !Number.isNaN(d.getTime());
}

// ---------------------------------------------------------------------------
// Display formatters. Pure / no I/O. Reused by the split-review
// page via the canonical encounter-format.ts (we deliberately do
// NOT import that here because it pulls in ClaimPayload types from
// the server-side lib; duplication is cheaper than the type
// gymnastics).
// ---------------------------------------------------------------------------

export function formatCents(cents: number): string {
  const dollars = cents / 100;
  const sign = cents < 0 ? "-" : cents > 0 ? "+" : "";
  const abs = Math.abs(dollars).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return cents === 0 ? abs : `${sign}${abs}`;
}

export function formatDate(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return typeof iso === "string" ? iso : "";
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Human-readable labels. Kept here so the Client Component doesn't
// have to import from encounter-types (which is a server-side
// module that exports Zod schemas — Zod is fine for the client but
// we already depend on encounter-types for the union types, and
// these label maps are stable).
// ---------------------------------------------------------------------------

export const STATUS_LABEL: Record<EncounterStatus, string> = {
  pending: "Pending",
  auditing: "Auditing",
  awaiting_review: "Awaiting review",
  completed: "Completed",
};

export const CATEGORY_LABEL: Record<FindingCategory, string> = {
  em_level: "E/M level",
  documentation: "Documentation",
  medical_necessity: "Medical necessity",
  modifier: "Modifier",
  code_mismatch: "Code mismatch",
  payer_policy: "Payer policy",
  other: "Other",
};

export const COLUMN_LABEL: Record<SortColumn, string> = {
  encounter_id: "Encounter",
  date_of_service: "Date of service",
  provider: "Provider",
  payer: "Payer",
  status: "Status",
  finding_count: "Findings",
  est_impact: "Est. impact",
};
