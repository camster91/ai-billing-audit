// Unit tests for the First-Pass Approval Rate (FPAR) helper.
//
// Tests the pure predicate `isAcceptedUnchanged` from src/lib/fpar.ts.
// The IO-bound computeFPAR() function is exercised end-to-end via
// the dashboard page render + manual verification on a real tenant;
// mocking Prisma in node:test is more setup than is worth the
// regression-safety for a 50-row aggregation. The bands + thresholds
// in FPARTile are pinned by inspecting the rendered HTML in the
// e2e suite (apps/portal/tests/e2e/).
//
// Run from apps/portal:
//   pnpm exec tsx tests/fpar.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { isAcceptedUnchanged, FPAR_MIN_WINDOW, FPAR_STALE_DAYS } from "../src/lib/fpar";

test("isAcceptedUnchanged: all accepted, no dismiss text → true", () => {
  const findings = [
    { status: "accepted", dismissText: null },
    { status: "accepted", dismissText: null },
  ];
  assert.equal(isAcceptedUnchanged(findings), true);
});

test("isAcceptedUnchanged: any dismissed → false", () => {
  const findings = [
    { status: "accepted", dismissText: null },
    { status: "dismissed", dismissText: "wrong code" },
  ];
  assert.equal(isAcceptedUnchanged(findings), false);
});

test("isAcceptedUnchanged: any pending → false", () => {
  const findings = [
    { status: "accepted", dismissText: null },
    { status: "pending", dismissText: null },
  ];
  assert.equal(isAcceptedUnchanged(findings), false);
});

test("isAcceptedUnchanged: empty findings list → false", () => {
  // An encounter with zero findings doesn't count as an "audit"
  // per the spec — the biller had nothing to accept or dismiss.
  assert.equal(isAcceptedUnchanged([]), false);
});

test("isAcceptedUnchanged: accept with dismissText set → false", () => {
  // Defensive: the schema says dismissText is null on accept, but if
  // a malformed row has both accept + dismissText we should not
  // count it as accepted-unchanged. The schema invariant is
  // enforced at the route layer; this is the safety net.
  const findings = [{ status: "accepted", dismissText: "modifier mismatch" }];
  assert.equal(isAcceptedUnchanged(findings), false);
});

test("isAcceptedUnchanged: all dismissed → false", () => {
  const findings = [
    { status: "dismissed", dismissText: null },
    { status: "dismissed", dismissText: "duplicate" },
  ];
  assert.equal(isAcceptedUnchanged(findings), false);
});

test("isAcceptedUnchanged: single accepted finding → true", () => {
  assert.equal(
    isAcceptedUnchanged([{ status: "accepted", dismissText: null }]),
    true,
  );
});

test("constants match the spec (docs/APPROVAL_RATE_KPI.md §3, §5)", () => {
  // These are the locked thresholds from the spec. If you change
  // them, update the spec doc too — they're referenced in clinic
  // onboarding conversations.
  assert.equal(FPAR_MIN_WINDOW, 10);
  assert.equal(FPAR_STALE_DAYS, 30);
});