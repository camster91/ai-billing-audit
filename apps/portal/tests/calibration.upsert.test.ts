// Round-trip smoke test for the CalibrationSignal write path.
//
// Locks the write-path -> read-path -> bucket chain end-to-end so a
// future schema change can't silently break the dashboard card
// again. Mirrors the pattern in tests/audit-quota.test.ts (uses the
// dev SQLite DB; cleans up rows it creates).
//
// Acceptance criteria (from the calibration worker suggestion):
//   1. upsertCalibrationSignal 1 time on a fresh (tenant, rule) →
//      read back via computeCalibration, bucket=uncalibrated (n=1 < 5).
//   2. upsert 4 more times → bucket=calibrated (n=5, acceptRate=1.0).
//   3. upsert 1 dismiss after the 5 accepts → bucket=reviewing
//      (n=6, acceptRate=5/6 ≈ 0.83 still calibrated by 0.70 threshold;
//      re-check threshold below).
//   4. ruleId === null input is a no-op (no row created).
//
// Run from apps/portal:
//   pnpm test:calibration-upsert
// (or via `pnpm test:onboarding` if added to the script set)

import { test, after } from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { prisma } from "../src/lib/prisma";
import {
  upsertCalibrationSignal,
  type CalibrationAction,
} from "../src/lib/calibration-write";
import {
  computeCalibration,
  CALIBRATION_MIN_ACTED_ON,
} from "../src/lib/calibration";

const fixedTimestamp = new Date("2026-06-27T20:00:00.000Z");
const usedTenantIds: string[] = [];
const usedRuleIds: string[] = [];

function freshTenantId(): string {
  const id = `t_calib_smoke_${randomBytes(6).toString("hex")}`;
  usedTenantIds.push(id);
  return id;
}

function freshRuleId(label: string): string {
  const id = `rule_calib_smoke_${label}_${randomBytes(4).toString("hex")}`;
  usedRuleIds.push(id);
  return id;
}

// Cleanup: delete any rows we created so the dev DB stays tidy
// for the next run. Order: CalibrationSignal rows first (they have
// no FK to other tables), then Tenant.
after(async () => {
  await prisma.calibrationSignal.deleteMany({
    where: { tenantId: { in: usedTenantIds } },
  });
  // We never actually insert Tenant rows in this test (the helper
  // only needs a tenantId string). If a future test starts inserting
  // real Tenants, add a `prisma.tenant.deleteMany` here.
});

async function callUpsert(
  tenantId: string,
  ruleId: string | null,
  action: CalibrationAction,
) {
  await prisma.$transaction((tx) =>
    upsertCalibrationSignal(tx, {
      tenantId,
      ruleId,
      action,
      timestamp: fixedTimestamp,
    }),
  );
}

test("upsertCalibrationSignal: 1 accept → bucket=uncalibrated (n=1 < MIN)", async () => {
  const tenantId = freshTenantId();
  const ruleId = freshRuleId("oneaccept");

  await callUpsert(tenantId, ruleId, "accept");

  const calibration = await computeCalibration(tenantId);
  assert.equal(calibration.signals.length, 1);
  const sig = calibration.signals[0]!;
  assert.equal(sig.ruleId, ruleId);
  assert.equal(sig.acceptCount, 1);
  assert.equal(sig.dismissCount, 0);
  assert.equal(sig.actedOn, 1);
  assert.equal(sig.acceptRate, null, "n=1 < MIN must null the rate");
  assert.equal(sig.bucket, "uncalibrated");
});

test("upsertCalibrationSignal: 5 accepts → bucket=calibrated (n=5, rate=1.0)", async () => {
  const tenantId = freshTenantId();
  const ruleId = freshRuleId("fiveaccepts");

  for (let i = 0; i < CALIBRATION_MIN_ACTED_ON; i++) {
    await callUpsert(tenantId, ruleId, "accept");
  }

  const calibration = await computeCalibration(tenantId);
  assert.equal(calibration.signals.length, 1);
  const sig = calibration.signals[0]!;
  assert.equal(sig.acceptCount, 5);
  assert.equal(sig.dismissCount, 0);
  assert.equal(sig.actedOn, 5);
  assert.equal(sig.acceptRate, 1.0);
  assert.equal(sig.bucket, "calibrated");
});

test("upsertCalibrationSignal: 5 accepts + 1 dismiss → bucket still calibrated (rate=0.833)", async () => {
  const tenantId = freshTenantId();
  const ruleId = freshRuleId("mixed");

  for (let i = 0; i < CALIBRATION_MIN_ACTED_ON; i++) {
    await callUpsert(tenantId, ruleId, "accept");
  }
  await callUpsert(tenantId, ruleId, "dismiss");

  const calibration = await computeCalibration(tenantId);
  const sig = calibration.signals[0]!;
  assert.equal(sig.acceptCount, 5);
  assert.equal(sig.dismissCount, 1);
  assert.equal(sig.actedOn, 6);
  assert.equal(sig.acceptRate, Math.round((5 / 6) * 1000) / 1000);
  // 5/6 = 0.833 → above the 0.70 threshold → calibrated.
  assert.equal(sig.bucket, "calibrated");
});

test("upsertCalibrationSignal: 5 dismisses → bucket=overcalled (rate=0.0)", async () => {
  const tenantId = freshTenantId();
  const ruleId = freshRuleId("alldismiss");

  for (let i = 0; i < CALIBRATION_MIN_ACTED_ON; i++) {
    await callUpsert(tenantId, ruleId, "dismiss");
  }

  const calibration = await computeCalibration(tenantId);
  const sig = calibration.signals[0]!;
  assert.equal(sig.acceptCount, 0);
  assert.equal(sig.dismissCount, 5);
  assert.equal(sig.acceptRate, 0.0);
  assert.equal(sig.bucket, "overcalled");
});

test("upsertCalibrationSignal: ruleId=null is a no-op (no row created)", async () => {
  const tenantId = freshTenantId();

  await callUpsert(tenantId, null, "accept");

  const calibration = await computeCalibration(tenantId);
  assert.equal(
    calibration.signals.length,
    0,
    "null ruleId must skip the upsert — signals stays empty",
  );
});

test("upsertCalibrationSignal: separate (tenant, rule) pairs don't share counters", async () => {
  const tenantId = freshTenantId();
  const ruleA = freshRuleId("isoA");
  const ruleB = freshRuleId("isoB");

  await callUpsert(tenantId, ruleA, "accept");
  await callUpsert(tenantId, ruleA, "accept");
  await callUpsert(tenantId, ruleB, "dismiss");

  const calibration = await computeCalibration(tenantId);
  const a = calibration.signals.find((s) => s.ruleId === ruleA)!;
  const b = calibration.signals.find((s) => s.ruleId === ruleB)!;
  assert.equal(a.acceptCount, 2);
  assert.equal(a.dismissCount, 0);
  assert.equal(b.acceptCount, 0);
  assert.equal(b.dismissCount, 1);
});