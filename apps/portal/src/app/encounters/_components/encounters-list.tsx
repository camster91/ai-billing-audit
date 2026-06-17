// Client component for the /encounters list page.
//
// All UI state (filters, sort, page size, search) is reflected in the
// URL query string. The component does not hold its own copy of the
// row data — it renders the rows the server component gave it, and
// every control change pushes a new search-params object onto the
// router so the server can re-render the page with fresh results.
//
// Why URL-state instead of local state:
//   - Refresh survives (acceptance criterion).
//   - Pagination and sort survive (acceptance criterion).
//   - The CSV export route reads the same URL params, so a user
//     looking at "status=pending" and clicking "Export" gets only
//     the pending rows.
//
// Why a "use client" component at all:
//   - The filter controls need onChange handlers, debouncing, and the
//     "Export selected" button posts a form. A server component can't
//     own these. The page is still a server component; only the
//     interactive controls are client.
//
// Selected-row state: kept locally (not in the URL — selection is
// per-page and ephemeral). The "Export selected" action serializes
// the selection into a hidden form field on submit.

"use client";

import {
  useCallback,
  useMemo,
  useState,
  useTransition,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import {
  COLUMN_LABEL,
  CATEGORY_LABEL,
  STATUS_LABEL,
  formatCents,
  SORTABLE_COLUMNS,
  type SortColumn,
  type SortDirection,
} from "@/lib/encounter-list-client";
import { ENCOUNTER_STATUSES, FINDING_CATEGORIES, type EncounterStatus, type FindingCategory } from "@/lib/encounter-types";
import styles from "./encounters-list.module.css";

export interface EncounterRow {
  id: string;
  dateOfService: string; // ISO; serialized by the server
  provider: string;
  providerNpi: string;
  payer: string;
  status: string;
  findingCount: number;
  estImpactCents: number;
}

export interface EncounterFacets {
  providers: string[];
  payers: string[];
  statuses: EncounterStatus[];
  findingCategories: FindingCategory[];
}

export interface EncounterListClientProps {
  rows: EncounterRow[];
  facets: EncounterFacets;
  page: number;
  pageSize: number;
  totalCount: number;
  totalPages: number;
  sortColumn: SortColumn;
  sortDirection: SortDirection;
  // The currently-applied filters, echoed from the server. Used to
  // initialize the controlled inputs.
  activeFilters: {
    dateFrom: string;
    dateTo: string;
    providers: string[];
    payers: string[];
    statuses: EncounterStatus[];
    findingCategories: FindingCategory[];
    search: string;
  };
  // A small sentinel used by the loading skeleton — flipped on while
  // a transition is pending. The parent shows the current rows but
  // dims the table.
}

// Status / category / column labels and formatters live in
// @/lib/encounter-list-client so the server-side and client-side
// code can both import them without dragging Prisma into the
// client bundle.

export function EncounterListClient(props: EncounterListClientProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  // ---- Selection state (per-page, not in URL) -----------------------
  const [selected, setSelected] = useState<Set<string>>(() => new Set());

  const allOnPageSelected =
    props.rows.length > 0 && props.rows.every((r) => selected.has(r.id));

  const toggleAll = useCallback(() => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        for (const r of props.rows) next.delete(r.id);
      } else {
        for (const r of props.rows) next.add(r.id);
      }
      return next;
    });
  }, [allOnPageSelected, props.rows]);

  const toggleRow = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // ---- URL mutation helper ------------------------------------------
  // All filter / sort / pagination changes go through this. It builds
  // a new URLSearchParams from the current one, mutates the relevant
  // key, and pushes it. The server component re-renders with the new
  // params and the URL bar stays in sync.
  const applyParams = useCallback(
    (mutate: (p: URLSearchParams) => void) => {
      const next = new URLSearchParams(searchParams.toString());
      mutate(next);
      // When the user changes a filter or sort, reset to page 1.
      const qs = next.toString();
      startTransition(() => {
        router.push(qs.length > 0 ? `${pathname}?${qs}` : pathname);
      });
    },
    [pathname, router, searchParams],
  );

  // ---- Filter control handlers --------------------------------------
  const onDateFrom = (e: ChangeEvent<HTMLInputElement>) =>
    applyParams((p) => {
      if (e.target.value) p.set("date_from", e.target.value);
      else p.delete("date_from");
      p.delete("page");
    });
  const onDateTo = (e: ChangeEvent<HTMLInputElement>) =>
    applyParams((p) => {
      if (e.target.value) p.set("date_to", e.target.value);
      else p.delete("date_to");
      p.delete("page");
    });
  const onSearch = (e: ChangeEvent<HTMLInputElement>) =>
    applyParams((p) => {
      if (e.target.value.trim()) p.set("q", e.target.value.trim());
      else p.delete("q");
      p.delete("page");
    });

  const onStatusChange = (status: EncounterStatus) => (e: ChangeEvent<HTMLInputElement>) =>
    applyParams((p) => toggleInParam(p, "status", status, e.target.checked));
  const onCategoryChange = (cat: FindingCategory) => (e: ChangeEvent<HTMLInputElement>) =>
    applyParams((p) => toggleInParam(p, "category", cat, e.target.checked));
  const onProviderChange = (provider: string) => (e: ChangeEvent<HTMLInputElement>) =>
    applyParams((p) => toggleInParam(p, "provider", provider, e.target.checked));
  const onPayerChange = (payer: string) => (e: ChangeEvent<HTMLInputElement>) =>
    applyParams((p) => toggleInParam(p, "payer", payer, e.target.checked));

  const onSort = (col: SortColumn) => () =>
    applyParams((p) => {
      if (p.get("sort") === col) {
        // Toggle direction if already sorted by this column.
        const nextDir: SortDirection = p.get("dir") === "asc" ? "desc" : "asc";
        p.set("dir", nextDir);
      } else {
        p.set("sort", col);
        p.set("dir", "asc");
      }
      p.delete("page");
    });

  const onPageSize = (e: ChangeEvent<HTMLSelectElement>) =>
    applyParams((p) => {
      p.set("page_size", e.target.value);
      p.delete("page");
    });

  const onPage = (target: number) => () =>
    applyParams((p) => {
      if (target <= 1) p.delete("page");
      else p.set("page", String(target));
    });

  const onClearAll = () =>
    applyParams((p) => {
      for (const k of [
        "date_from",
        "date_to",
        "provider",
        "payer",
        "status",
        "category",
        "q",
        "sort",
        "dir",
        "page",
        "page_size",
      ]) {
        p.delete(k);
      }
    });

  // ---- Export-selected submit ---------------------------------------
  // We submit a plain form to the export route. The selected ids are
  // pulled from local state and put in a hidden field. Other active
  // filters are mirrored as hidden fields so the export reflects the
  // current view, not a stale snapshot.
  const onExportSelectedSubmit = (e: FormEvent<HTMLFormElement>) => {
    if (selected.size === 0) {
      e.preventDefault();
      return;
    }
    // The form's action is /api/encounters/export. We also append the
    // current filters as hidden inputs so the export respects them.
    // The form posts as a GET so the server route can read them from
    // the URL. (We could also just open a new tab; this approach
    // works without a popup blocker.)
  };

  // ---- Derived display values ---------------------------------------
  const exportHref = useMemo(() => {
    // Used by the "Export all" (no selection) button as a plain link.
    const sp = new URLSearchParams(searchParams.toString());
    sp.delete("ids");
    sp.delete("page");
    return `/api/encounters/export?${sp.toString()}`;
  }, [searchParams]);

  return (
    <div className={styles.wrap}>
      {/* ---------------- Filter toolbar ---------------- */}
      <section className={styles.filters} aria-label="Filters">
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel} htmlFor="f-date-from">From</label>
          <input
            id="f-date-from"
            type="date"
            className={styles.input}
            defaultValue={props.activeFilters.dateFrom}
            onChange={onDateFrom}
          />
          <label className={styles.filterLabel} htmlFor="f-date-to">To</label>
          <input
            id="f-date-to"
            type="date"
            className={styles.input}
            defaultValue={props.activeFilters.dateTo}
            onChange={onDateTo}
          />
        </div>

        <div className={styles.filterGroup}>
          <label className={styles.filterLabel} htmlFor="f-search">Search</label>
          <input
            id="f-search"
            type="search"
            placeholder="Encounter id or patient hash…"
            className={styles.input}
            defaultValue={props.activeFilters.search}
            onChange={onSearch}
          />
        </div>

        <FacetGroup
          legend="Status"
          name="status"
          options={ENCOUNTER_STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] }))}
          activeValues={props.activeFilters.statuses}
          availableValues={props.facets.statuses}
          onToggle={onStatusChange}
        />
        <FacetGroup
          legend="Category"
          name="category"
          options={FINDING_CATEGORIES.map((c) => ({ value: c, label: CATEGORY_LABEL[c] }))}
          activeValues={props.activeFilters.findingCategories}
          availableValues={props.facets.findingCategories}
          onToggle={onCategoryChange}
        />
        <FacetGroup
          legend="Provider"
          name="provider"
          options={props.facets.providers.map((p) => ({ value: p, label: p }))}
          activeValues={props.activeFilters.providers}
          availableValues={props.facets.providers}
          onToggle={onProviderChange}
        />
        <FacetGroup
          legend="Payer"
          name="payer"
          options={props.facets.payers.map((p) => ({ value: p, label: p }))}
          activeValues={props.activeFilters.payers}
          availableValues={props.facets.payers}
          onToggle={onPayerChange}
        />

        <div className={styles.filterGroup}>
          <button
            type="button"
            className={styles.clearButton}
            onClick={onClearAll}
            aria-label="Clear all filters"
          >
            Clear filters
          </button>
        </div>
      </section>

      {/* ---------------- Bulk action toolbar ---------------- */}
      <section className={styles.actions} aria-label="Bulk actions">
        <div className={styles.selectionSummary}>
          {selected.size === 0
            ? "No rows selected"
            : `${selected.size} selected on this page`}
        </div>
        <form
          method="GET"
          action="/api/encounters/export"
          target="_blank"
          onSubmit={onExportSelectedSubmit}
          className={styles.exportForm}
        >
          {/* Mirror the current filters into the export request so the
              selected rows respect the same view the user is looking at. */}
          <MirrorFilters searchParams={searchParams} />
          <input
            type="hidden"
            name="ids"
            value={[...selected].join(",")}
            readOnly
          />
          <button
            type="submit"
            className={styles.button}
            disabled={selected.size === 0}
          >
            Export selected as CSV
          </button>
        </form>
        <a
          href={exportHref}
          className={`${styles.button} ${styles.buttonSecondary}`}
          download
        >
          Export all (current filters)
        </a>
      </section>

      {/* ---------------- Table ---------------- */}
      <div className={styles.tableScroller}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.checkboxCol}>
                <input
                  type="checkbox"
                  aria-label="Select all rows on this page"
                  checked={allOnPageSelected}
                  onChange={toggleAll}
                  disabled={props.rows.length === 0}
                />
              </th>
              {SORTABLE_COLUMNS.map((col) => (
                <SortHeader
                  key={col}
                  column={col}
                  label={COLUMN_LABEL[col]}
                  activeColumn={props.sortColumn}
                  direction={props.sortDirection}
                  onSort={onSort(col)}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {props.rows.length === 0 ? (
              <tr>
                <td colSpan={SORTABLE_COLUMNS.length + 1} className={styles.empty}>
                  No encounters match the current filters.
                </td>
              </tr>
            ) : (
              props.rows.map((r) => (
                <tr
                  key={r.id}
                  className={selected.has(r.id) ? styles.rowSelected : undefined}
                >
                  <td className={styles.checkboxCol}>
                    <input
                      type="checkbox"
                      aria-label={`Select encounter ${r.id}`}
                      checked={selected.has(r.id)}
                      onChange={() => toggleRow(r.id)}
                    />
                  </td>
                  <td>
                    <a
                      href={`/encounters/${r.id}`}
                      className={styles.encounterLink}
                      data-encounter-id={r.id}
                    >
                      <code>{r.id}</code>
                    </a>
                  </td>
                  <td>{r.dateOfService.slice(0, 10)}</td>
                  <td>
                    {r.provider}
                    <span className={styles.subtle}>
                      {" "}
                      (NPI {r.providerNpi})
                    </span>
                  </td>
                  <td>{r.payer}</td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td className={styles.numericCell}>{r.findingCount}</td>
                  <td className={styles.numericCell}>
                    {formatCents(r.estImpactCents)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* ---------------- Pager ---------------- */}
      <section className={styles.pager} aria-label="Pagination">
        <div className={styles.pagerInfo}>
          {props.totalCount === 0
            ? "No results"
            : `Showing ${pageStart(props.page, props.pageSize, props.totalCount)}\u2013${pageEnd(
                props.page,
                props.pageSize,
                props.totalCount,
              )} of ${props.totalCount}`}
        </div>
        <div className={styles.pagerControls}>
          <label htmlFor="f-page-size" className={styles.filterLabel}>
            Rows per page
          </label>
          <select
            id="f-page-size"
            className={styles.select}
            value={String(props.pageSize)}
            onChange={onPageSize}
          >
            {[10, 25, 50, 100].map((n) => (
              <option key={n} value={String(n)}>
                {n}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={styles.button}
            onClick={onPage(props.page - 1)}
            disabled={props.page <= 1}
          >
            Previous
          </button>
          <span className={styles.pageIndicator}>
            Page {props.page} / {props.totalPages}
          </span>
          <button
            type="button"
            className={styles.button}
            onClick={onPage(props.page + 1)}
            disabled={props.page >= props.totalPages}
          >
            Next
          </button>
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Facet group — a small <fieldset> with checkboxes for one filter category.
// `availableValues` is the list returned by the server; `activeValues` is
// the subset currently applied. We always render the canonical option
// list (ENCOUNTER_STATUSES, FINDING_CATEGORIES, etc.) so the UI doesn't
// drop an option that exists in the enum but happens to have no rows
// in the current dataset.
// ---------------------------------------------------------------------------

interface FacetGroupProps<T extends string> {
  legend: string;
  name: string;
  options: ReadonlyArray<{ value: T; label: string }>;
  activeValues: T[];
  availableValues: T[];
  onToggle: (value: T) => (e: ChangeEvent<HTMLInputElement>) => void;
}

function FacetGroup<T extends string>(props: FacetGroupProps<T>) {
  return (
    <fieldset className={styles.facet}>
      <legend className={styles.filterLabel}>{props.legend}</legend>
      <div className={styles.facetOptions}>
        {props.options.map((opt) => {
          const checked = props.activeValues.includes(opt.value);
          const available = props.availableValues.includes(opt.value);
          return (
            <label
              key={opt.value}
              className={`${styles.facetOption} ${available ? "" : styles.facetOptionMuted}`}
            >
              <input
                type="checkbox"
                name={`${props.name}-${opt.value}`}
                checked={checked}
                onChange={props.onToggle(opt.value)}
              />
              <span>{opt.label}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function SortHeader(props: {
  column: SortColumn;
  label: string;
  activeColumn: SortColumn;
  direction: SortDirection;
  onSort: () => void;
}) {
  const isActive = props.activeColumn === props.column;
  const arrow = isActive ? (props.direction === "asc" ? "\u25b2" : "\u25bc") : "";
  return (
    <th
      className={`${styles.sortable} ${isActive ? styles.sortableActive : ""}`}
      aria-sort={isActive ? (props.direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <button type="button" className={styles.sortButton} onClick={props.onSort}>
        <span>{props.label}</span>
        <span className={styles.sortArrow} aria-hidden="true">
          {arrow}
        </span>
      </button>
    </th>
  );
}

function StatusBadge(props: { status: string }) {
  const cls =
    props.status === "pending"
      ? styles.statusPending
      : props.status === "auditing"
        ? styles.statusAuditing
        : props.status === "awaiting_review"
          ? styles.statusAwaiting
          : props.status === "completed"
            ? styles.statusCompleted
            : styles.statusDefault;
  return <span className={`${styles.statusBadge} ${cls}`}>{props.status}</span>;
}

function MirrorFilters(props: { searchParams: URLSearchParams }) {
  // Mirrors non-selection params into the export form so a user
  // looking at "status=pending" and clicking "Export selected" gets
  // pending rows in the CSV.
  const MIRRORED = ["date_from", "date_to", "provider", "payer", "status", "category", "q", "sort", "dir"];
  return (
    <>
      {MIRRORED.flatMap((key) =>
        props.searchParams
          .getAll(key)
          .map((v) => <input key={`${key}-${v}`} type="hidden" name={key} value={v} />),
      )}
    </>
  );
}

function toggleInParam(
  p: URLSearchParams,
  key: string,
  value: string,
  checked: boolean,
) {
  const existing = p.getAll(key);
  p.delete(key);
  if (checked) {
    // De-dupe so repeated toggles don't grow the param list.
    const merged = new Set([...existing, value]);
    for (const v of merged) p.append(key, v);
  } else {
    for (const v of existing) {
      if (v !== value) p.append(key, v);
    }
  }
  p.delete("page");
}

function pageStart(page: number, size: number, total: number): number {
  if (total === 0) return 0;
  return (page - 1) * size + 1;
}
function pageEnd(page: number, size: number, total: number): number {
  if (total === 0) return 0;
  return Math.min(page * size, total);
}
