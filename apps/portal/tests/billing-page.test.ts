// Node test script for the billing-page lib (src/lib/billing-page.ts).
//
// Verifies the date-arithmetic primitives that drive the usage
// card and the invoice window. Both are UTC because the dev host
// (EDT) and the production Postgres cluster are in different
// time zones — using a non-UTC initializer loses or gains a day
// on month boundaries. The bug we're guarding against was caught
// in the jw-habits "day of year" calculation (see ~/.hermes
// MEMORY.md entry "Date arithmetic on non-UTC machines"); same
// root cause, different surface.
//
// Run with `pnpm test:billing-page` (added to package.json). The
// test doesn't touch the database — it exercises the pure
// helpers so it's fast and isolated from the running dev server.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  startOfCurrentMonthUtc,
  startOfInvoiceWindowUtc,
  formatCents,
} from "../src/lib/billing-page-helpers";

test("startOfCurrentMonthUtc: returns the 1st of the current month in UTC", () => {
  const cases = [
    // 2026-06-17 00:00 local -> treat as UTC for the test
    new Date("2026-06-17T04:29:36.000Z"),
    new Date("2026-01-01T00:00:00.000Z"),
    new Date("2026-12-31T23:59:59.999Z"),
    new Date("2026-02-15T12:00:00.000Z"),
  ];
  for (const now of cases) {
    const start = startOfCurrentMonthUtc(now);
    assert.equal(start.getUTCMonth(), now.getUTCMonth(), `month for ${now.toISOString()}`);
    assert.equal(start.getUTCDate(), 1, `day=1 for ${now.toISOString()}`);
    assert.equal(start.getUTCHours(), 0, `hours=0 for ${now.toISOString()}`);
    assert.equal(start.getUTCMinutes(), 0, `minutes=0 for ${now.toISOString()}`);
    assert.equal(start.getUTCSeconds(), 0, `seconds=0 for ${now.toISOString()}`);
  }
});

test("startOfInvoiceWindowUtc: returns the 1st of 11 months ago", () => {
  // 2026-06-17 → window starts 2025-07-01 (11 months back, UTC).
  const start = startOfInvoiceWindowUtc(new Date("2026-06-17T12:00:00.000Z"));
  assert.equal(start.getUTCFullYear(), 2025);
  assert.equal(start.getUTCMonth(), 6); // July (0-indexed)
  assert.equal(start.getUTCDate(), 1);
});

test("startOfInvoiceWindowUtc: year-rollover at January", () => {
  // 2026-01-15 → window starts 2025-02-01.
  const start = startOfInvoiceWindowUtc(new Date("2026-01-15T12:00:00.000Z"));
  assert.equal(start.getUTCFullYear(), 2025);
  assert.equal(start.getUTCMonth(), 1); // February
  assert.equal(start.getUTCDate(), 1);
});

test("formatCents: integer cents to human-readable string", () => {
  assert.equal(formatCents(149900, "USD"), "$1,499");
  assert.equal(formatCents(149900, "CAD"), "CA$1,499");
  assert.equal(formatCents(110900, "USD"), "$1,109");
  assert.equal(formatCents(49900, "CAD"), "CA$499");
  assert.equal(formatCents(0, "USD"), "$0");
});
