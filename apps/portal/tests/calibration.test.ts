// Unit tests for the per-clinic calibration read path.
//
// Tests the pure `bucketFor()` function from src/lib/calibration.ts —
// the IO-bound computeCalibration() function is exercised via the
// dashboard page render + manual verification on a real tenant;
// mocking Prisma in node:test is more setup than is worth the
// regression-safety for an aggregation that lives entirely behind
// the calibration card on /dashboard.
//
// Run from apps/portal:
//   pnpm exec tsx tests/calibration.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  bucketFor,
  CALIBRATION_MIN_ACTED_ON,
  CALIBRATION_STALE_DAYS,
} from "../src/lib/calibration";

test("bucketFor: acceptRate >= 0.70 → calibrated", () => {
  assert.equal(bucketFor(0.7, 100), "calibrated");
  assert.equal(bucketFor(0.85, 50), "calibrated");
  assert.equal(bucketFor(1.0, 20), "calibrated");
});

test("bucketFor: 0.40 <= acceptRate < 0.70 → reviewing", () => {
  assert.equal(bucketFor(0.4, 100), "reviewing");
  assert.equal(bucketFor(0.55, 50), "reviewing");
  assert.equal(bucketFor(0.69, 10), "reviewing");
});

test("bucketFor: acceptRate < 0.40 → overcalled", () => {
  assert.equal(bucketFor(0.0, 100), "overcalled");
  assert.equal(bucketFor(0.2, 50), "overcalled");
  assert.equal(bucketFor(0.39, 10), "overcalled");
});

test("bucketFor: actedOn < CALIBRATION_MIN_ACTED_ON → uncalibrated (regardless of rate)", () => {
  // Even at 100% accept rate, with only 1 data point we don't trust the signal.
  assert.equal(bucketFor(1.0, 1), "uncalibrated");
  assert.equal(bucketFor(0.5, 0), "uncalibrated");
  assert.equal(bucketFor(null, 3), "uncalibrated");
});

test("bucketFor: acceptRate === null → uncalibrated", () => {
  // Caller passed null (the data shape from computeCalibration when
  // actedOn < threshold). Even if actedOn is high, null means "no
  // rate to bucket from".
  assert.equal(bucketFor(null, 100), "uncalibrated");
});

test("constants match the FastAPI side (feedback.py:280)", () => {
  // These are the locked thresholds from the FastAPI's
  // feedback.py:280 calibration buckets. If you change them, change
  // the FastAPI side too — the two stay in lockstep so the
  // portal-dashboard and the FastAPI report are interchangeable.
  assert.equal(CALIBRATION_MIN_ACTED_ON, 5);
  assert.equal(CALIBRATION_STALE_DAYS, 30);
});

test("boundary cases at 0.40 and 0.70 (off-by-one safety)", () => {
  // These are the exact edges where a single off-by-one flip would
  // re-bucket a rule. They exist because the thresholds are
  // hard-coded constants and have been wrong before.
  assert.equal(bucketFor(0.399, 100), "overcalled", "0.399 must be overcalled");
  assert.equal(bucketFor(0.400, 100), "reviewing", "0.400 must be reviewing");
  assert.equal(bucketFor(0.699, 100), "reviewing", "0.699 must be reviewing");
  assert.equal(bucketFor(0.700, 100), "calibrated", "0.700 must be calibrated");
});