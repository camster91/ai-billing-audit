// Unit tests for the encounter-list helpers in src/lib/encounter-list.ts.
//
// The list helpers are pure (parsing, where-clause assembly) or
// require a Prisma client. The pure ones are tested here; the
// Prisma-bound ones (loadEncounterListPage, loadEncounterListFacets)
// are exercised end-to-end against the dev SQLite DB and verified
// with explicit query counts in the smoke test (see
// tests/encounter-list-smoke.test.ts).
//
// Run from apps/portal:
//   pnpm exec node --import tsx --test tests/encounter-list.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildEncounterListOrderBy,
  buildEncounterListWhere,
  parseEncounterListFilters,
  parseEncounterListPage,
  parseEncounterListSort,
  SORTABLE_COLUMNS,
  ENCOUNTER_LIST_DEFAULT_PAGE_SIZE,
  ENCOUNTER_LIST_MAX_PAGE_SIZE,
} from "../src/lib/encounter-list";
import { ENCOUNTER_STATUSES, FINDING_CATEGORIES } from "../src/lib/encounter-types";

test("parseEncounterListFilters: empty params returns all empty defaults", () => {
  const f = parseEncounterListFilters(new URLSearchParams());
  assert.equal(f.dateFrom, null);
  assert.equal(f.dateTo, null);
  assert.deepEqual(f.providers, []);
  assert.deepEqual(f.payers, []);
  assert.deepEqual(f.statuses, []);
  assert.deepEqual(f.findingCategories, []);
  assert.equal(f.search, "");
});

test("parseEncounterListFilters: date range is parsed and validated", () => {
  const f = parseEncounterListFilters(
    new URLSearchParams("date_from=2026-04-01&date_to=2026-06-30"),
  );
  assert.equal(f.dateFrom, "2026-04-01");
  assert.equal(f.dateTo, "2026-06-30");

  const bad = parseEncounterListFilters(new URLSearchParams("date_from=not-a-date"));
  assert.equal(bad.dateFrom, null);
});

test("parseEncounterListFilters: multi-status accepts both repeated keys and comma syntax", () => {
  const a = parseEncounterListFilters(
    new URLSearchParams("status=pending&status=auditing"),
  );
  assert.deepEqual(a.statuses.sort(), ["auditing", "pending"]);

  const b = parseEncounterListFilters(new URLSearchParams("status=pending,auditing"));
  assert.deepEqual(b.statuses.sort(), ["auditing", "pending"]);
});

test("parseEncounterListFilters: invalid status and category are dropped silently", () => {
  const f = parseEncounterListFilters(
    new URLSearchParams("status=pending&status=bogus&category=em_level&category=nope"),
  );
  assert.deepEqual(f.statuses, ["pending"]);
  assert.deepEqual(f.findingCategories, ["em_level"]);
});

test("parseEncounterListFilters: search query is trimmed and length-capped", () => {
  const long = "x".repeat(500);
  const f = parseEncounterListFilters(new URLSearchParams(`q=${long}`));
  assert.equal(f.search.length, 200);
  assert.equal(f.search[0], "x");
});

test("parseEncounterListSort: defaults to date_of_service desc", () => {
  const s = parseEncounterListSort(new URLSearchParams());
  assert.equal(s.column, "date_of_service");
  assert.equal(s.direction, "desc");
});

test("parseEncounterListSort: unknown column falls back to default", () => {
  const s = parseEncounterListSort(new URLSearchParams("sort=bogus&dir=asc"));
  assert.equal(s.column, "date_of_service");
  // 'asc' on a column that wasn't recognized is still applied to
  // the default, because direction parsing is independent.
  assert.equal(s.direction, "asc");
});

test("parseEncounterListSort: every sortable column round-trips", () => {
  for (const col of SORTABLE_COLUMNS) {
    const s = parseEncounterListSort(new URLSearchParams(`sort=${col}&dir=asc`));
    assert.equal(s.column, col);
    assert.equal(s.direction, "asc");
  }
});

test("parseEncounterListPage: defaults to page 1, default size", () => {
  const p = parseEncounterListPage(new URLSearchParams());
  assert.equal(p.page, 1);
  assert.equal(p.pageSize, ENCOUNTER_LIST_DEFAULT_PAGE_SIZE);
});

test("parseEncounterListPage: page_size is clamped to max", () => {
  const p = parseEncounterListPage(new URLSearchParams("page_size=99999"));
  assert.equal(p.pageSize, ENCOUNTER_LIST_MAX_PAGE_SIZE);
});

test("parseEncounterListPage: bad page falls back to 1", () => {
  const p = parseEncounterListPage(new URLSearchParams("page=-3"));
  assert.equal(p.page, 1);
});

test("buildEncounterListWhere: status filter uses the in-list shape", () => {
  const where = buildEncounterListWhere("t1", {
    dateFrom: null,
    dateTo: null,
    providers: [],
    payers: [],
    statuses: ["pending", "auditing"],
    findingCategories: [],
    search: "",
  });
  assert.equal((where as { tenantId?: string }).tenantId, "t1");
  assert.deepEqual((where as { status?: { in: string[] } }).status, {
    in: ["pending", "auditing"],
  });
});

test("buildEncounterListWhere: category filter reaches into findings.some", () => {
  const where = buildEncounterListWhere("t1", {
    dateFrom: null,
    dateTo: null,
    providers: [],
    payers: [],
    statuses: [],
    findingCategories: ["em_level"],
    search: "",
  });
  const findings = (where as { findings?: { some: { category: { in: string[] } } } }).findings;
  assert.deepEqual(findings, { some: { category: { in: ["em_level"] } } });
});

test("buildEncounterListWhere: provider and payer merge into a single claim where", () => {
  const where = buildEncounterListWhere("t1", {
    dateFrom: null,
    dateTo: null,
    providers: ["Dr. A"],
    payers: ["OHIP"],
    statuses: [],
    findingCategories: [],
    search: "",
  });
  const claim = (where as { claim?: { providerName?: { in: string[] }; payer?: { in: string[] } } }).claim;
  assert.deepEqual(claim, {
    providerName: { in: ["Dr. A"] },
    payer: { in: ["OHIP"] },
  });
});

test("buildEncounterListWhere: date range uses inclusive end-of-day for dateTo", () => {
  const where = buildEncounterListWhere("t1", {
    dateFrom: "2026-04-01",
    dateTo: "2026-06-30",
    providers: [],
    payers: [],
    statuses: [],
    findingCategories: [],
    search: "",
  });
  const range = (where as { dateOfService?: { gte?: Date; lte?: Date } }).dateOfService;
  assert.ok(range?.gte instanceof Date);
  assert.ok(range?.lte instanceof Date);
  assert.equal(range?.lte?.toISOString(), "2026-06-30T23:59:59.999Z");
});

test("buildEncounterListWhere: search hits encounter id and patient hash", () => {
  const where = buildEncounterListWhere("t1", {
    dateFrom: null,
    dateTo: null,
    providers: [],
    payers: [],
    statuses: [],
    findingCategories: [],
    search: "enc-list",
  });
  const or = (where as { OR?: unknown[] }).OR;
  assert.ok(Array.isArray(or));
  assert.equal(or?.length, 2);
});

test("buildEncounterListOrderBy: date_of_service and encounter_id produce a stable primary sort", () => {
  const a = buildEncounterListOrderBy({
    column: "date_of_service",
    direction: "asc",
  });
  assert.deepEqual(a, [{ dateOfService: "asc" }, { id: "asc" }]);

  const b = buildEncounterListOrderBy({
    column: "encounter_id",
    direction: "desc",
  });
  assert.deepEqual(b, [{ id: "desc" }]);
});

test("buildEncounterListOrderBy: provider and payer reach into the claim relation", () => {
  const provider = buildEncounterListOrderBy({ column: "provider", direction: "asc" });
  assert.deepEqual(provider, [{ claim: { providerName: "asc" } }, { id: "asc" }]);

  const payer = buildEncounterListOrderBy({ column: "payer", direction: "desc" });
  assert.deepEqual(payer, [{ claim: { payer: "desc" } }, { id: "desc" }]);
});

test("buildEncounterListOrderBy: finding_count and est_impact fall back to date sort", () => {
  // These are computed in JS; the DB-level sort is the stable
  // date+id fallback. The route applies the post-sort in JS.
  const a = buildEncounterListOrderBy({ column: "finding_count", direction: "asc" });
  assert.deepEqual(a, [{ dateOfService: "asc" }, { id: "asc" }]);

  const b = buildEncounterListOrderBy({ column: "est_impact", direction: "desc" });
  assert.deepEqual(b, [{ dateOfService: "desc" }, { id: "desc" }]);
});

test("ENCOUNTER_STATUSES and FINDING_CATEGORIES are non-empty and used by parser", () => {
  // Smoke check: every status is accepted by the parser; a non-list
  // value is dropped.
  for (const s of ENCOUNTER_STATUSES) {
    const f = parseEncounterListFilters(new URLSearchParams(`status=${s}`));
    assert.deepEqual(f.statuses, [s]);
  }
  for (const c of FINDING_CATEGORIES) {
    const f = parseEncounterListFilters(new URLSearchParams(`category=${c}`));
    assert.deepEqual(f.findingCategories, [c]);
  }
});
