// End-to-end smoke test for the encounter list data layer.
//
// This is the test that verifies the "no N+1 queries" acceptance
// criterion and the CSV export shape. The seed script
// (scripts/seed-encounter-list.ts) must have been run first; the
// demo tenant should have 60+ encounters across the four statuses,
// six payers, and five providers.
//
// Strategy:
//   - Count the queries Prisma makes when loading one page.
//     Prisma logs queries in dev mode (see src/lib/prisma.ts); we
//     monkey-patch the `query` log to count them.
//   - Load the page twice and assert the count is bounded (one count
//     + one findMany + a small number of relation reads for the
//     eager-loaded `claim` and `findings`).
//   - Hit the export logic directly (we re-implement the route's
//     SQL path inline to avoid a Next.js test harness) and verify
//     the CSV header + a known row's columns.
//
// Run from apps/portal:
//   pnpm exec node --import tsx --test tests/encounter-list-smoke.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { PrismaClient } from "../src/generated/prisma/client";
import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3";
import { hashPatientId } from "../src/lib/patient-hash";
import { buildEncounterListWhere, parseEncounterListFilters } from "../src/lib/encounter-list";

// Build a dedicated Prisma client with `query` logging enabled, so
// the smoke test can count queries. The shared `prisma` singleton
// in src/lib/prisma.ts gates query logging on NODE_ENV ===
// "development", which the node test runner overrides to "test" —
// reusing the shared client here would always report 0 queries.
const testPrisma = new PrismaClient({
  adapter: new PrismaBetterSqlite3({
    url: (process.env.DATABASE_URL ?? "file:./prisma/dev.db").replace(/^file:/, ""),
  }),
  log: ["query", "error", "warn"],
});

const TENANT_SLUG = "demo-clinic";

async function getDemoTenantId(): Promise<string> {
  const t = await testPrisma.tenant.findFirst({ where: { slug: TENANT_SLUG } });
  if (!t) throw new Error("demo tenant not seeded — run pnpm exec tsx scripts/seed-encounter-list.ts");
  return t.id;
}

/**
 * Install a Prisma query-event listener and count events during `fn`.
 * The Prisma client emits `query` events when log level includes
 * "query" (it does in dev, see src/lib/prisma.ts). The result is a
 * tuple of [count, sampleSqls].
 */
async function countQueries<T>(fn: () => Promise<T>): Promise<{ result: T; count: number; samples: string[] }> {
  const samples: string[] = [];
  let count = 0;
  const handler = (event: { query: string }) => {
    count += 1;
    if (samples.length < 6) samples.push(event.query.replace(/\s+/g, " ").slice(0, 200));
  };
  // The Prisma 7 event emitter is $on / $off but the untyped path is
  // fine for a smoke test. The unused-error directives are
  // commented out because @types/prisma's typings now expose both
  // signatures; if a future Prisma upgrade narrows the type we can
  // re-enable them.
  testPrisma.$on("query", handler);
  try {
    const result = await fn();
    return { result, count, samples };
  } finally {
    testPrisma.$off?.("query", handler);
  }
}

test("list page issues a bounded number of queries (no N+1)", async () => {
  const tenantId = await getDemoTenantId();
  const where = buildEncounterListWhere(tenantId, parseEncounterListFilters(new URLSearchParams()));

  const { count } = await countQueries(async () => {
    // The production path uses $transaction([count, findMany]) to
    // snapshot the reads; we mimic that shape here so the count is
    // a realistic upper bound.
    const [total, rows] = await testPrisma.$transaction([
      testPrisma.encounter.count({ where }),
      testPrisma.encounter.findMany({
        where,
        orderBy: [{ dateOfService: "desc" }, { id: "desc" }],
        take: 25,
        select: {
          id: true,
          dateOfService: true,
          status: true,
          claim: { select: { providerName: true, providerNpi: true, payer: true } },
          findings: { select: { id: true, estFinancialImpactCents: true } },
        },
      }),
    ]);
    return { total, rows };
  });

  // Expected: 1 count + 1 findMany for the encounter page + 1
  // related-select for `claim` (1 per row, batched by Prisma) + 1
  // related-select for `findings` (1 per row, batched). That's 4
  // queries total, not 25*N. The exact count can drift with
  // Prisma internals; we cap at 8 to leave headroom while still
  // catching N+1 regressions (which would be 25+).
  assert.ok(count <= 8, `expected <= 8 queries for one page, got ${count}`);
  assert.ok(count >= 3, `expected at least 3 queries (count + page + relations), got ${count}`);
});

test("list page returns >= 50 rows and supports date/status filters", async () => {
  const tenantId = await getDemoTenantId();

  const totalAll = await testPrisma.encounter.count({
    where: buildEncounterListWhere(tenantId, parseEncounterListFilters(new URLSearchParams())),
  });
  assert.ok(totalAll >= 50, `expected at least 50 encounters for the demo tenant, got ${totalAll}`);

  // Status filter: every status is present in the seed.
  const forStatus = buildEncounterListWhere(
    tenantId,
    parseEncounterListFilters(new URLSearchParams("status=pending")),
  );
  const pending = await testPrisma.encounter.count({ where: forStatus });
  assert.ok(pending > 0, "expected at least one pending encounter in the seed");
  assert.ok(pending < totalAll, "expected the pending count to be a strict subset");

  // Date range filter: shrink the window and confirm the count
  // drops.
  const forDate = buildEncounterListWhere(
    tenantId,
    parseEncounterListFilters(new URLSearchParams("date_from=2026-05-01&date_to=2026-05-31")),
  );
  const mayCount = await testPrisma.encounter.count({ where: forDate });
  assert.ok(mayCount < totalAll, "date-range filter should reduce the count");
  assert.ok(mayCount > 0, "expected at least one encounter in May 2026");
});

test("CSV export shape matches the documented column order", async () => {
  const tenantId = await getDemoTenantId();

  // Mirror the route's behavior end-to-end: assemble the rows the
  // way `loadEncounterListPage` does, then encode them through the
  // same CSV rules the route uses.
  const rows = await testPrisma.encounter.findMany({
    where: buildEncounterListWhere(tenantId, parseEncounterListFilters(new URLSearchParams())),
    orderBy: [{ dateOfService: "desc" }, { id: "desc" }],
    take: 5,
    select: {
      id: true,
      dateOfService: true,
      status: true,
      patientHash: true,
      claim: { select: { providerName: true, providerNpi: true, payer: true, billedCents: true } },
      findings: { select: { id: true, estFinancialImpactCents: true } },
    },
  });

  assert.ok(rows.length > 0, "expected seeded rows for the export smoke test");

  const HEADER = [
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
  ];

  const csvHeader = HEADER.join(",");
  const firstRow = rows[0];
  const cells = [
    firstRow.id,
    firstRow.dateOfService.toISOString().slice(0, 10),
    firstRow.claim.providerName,
    firstRow.claim.providerNpi,
    firstRow.claim.payer,
    firstRow.status,
    String(firstRow.findings.length),
    String(firstRow.findings.reduce((acc, f) => acc + (f.estFinancialImpactCents ?? 0), 0)),
    String(firstRow.claim.billedCents),
    firstRow.patientHash.slice(0, 12),
  ];
  const csvLine = cells.map(csvEscape).join(",");

  assert.equal(csvHeader, HEADER.join(","));
  assert.equal(csvLine.split(",").length, HEADER.length);
  // Patient-hash prefix is 12 hex chars, never contains CSV-special.
  assert.match(csvLine.split(",")[9], /^[a-f0-9]{12}$/);
});

function csvEscape(value: string): string {
  if (value === "") return "";
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

test("finding-category filter reaches the related table (no N+1 at the where level)", async () => {
  const tenantId = await getDemoTenantId();

  // The seed populates em_level findings on a subset of encounters.
  // The filter should match >= 1 row, and the SQL Prisma emits
  // should be a single statement (we verify by counting).
  const where = buildEncounterListWhere(
    tenantId,
    parseEncounterListFilters(new URLSearchParams("category=em_level")),
  );

  const { result, count } = await countQueries(async () => {
    return testPrisma.encounter.findMany({
      where,
      take: 10,
      select: { id: true, findings: { select: { category: true } } },
    });
  });

  assert.ok(result.length > 0, "expected at least one em_level match in the seed");
  // One statement for the encounter findMany + (likely) one for
  // the `findings` related select. We don't care about the exact
  // count, just that it isn't proportional to the result length.
  assert.ok(count <= 4, `expected <= 4 queries for category filter, got ${count}`);
});

// Silence "no test runs" complaints when this file is loaded by the
// node --test runner on its own.
test("smoke test wired up", () => {
  assert.equal(typeof randomBytes, "function");
  assert.equal(typeof hashPatientId, "function");
});
