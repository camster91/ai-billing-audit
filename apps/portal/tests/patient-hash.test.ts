// Unit tests for the peppered patient-hash helper.
//
// These tests exercise the pure function (no DB, no network) so they
// run in <100ms and are safe to keep in the default `pnpm test:onboarding`
// script. They prove the three properties the HIPAA / PHIPA risk
// assessment needs:
//   1. Determinism: same input + same pepper → same output.
//   2. Pepper-sensitivity: same input + different pepper → different
//      output (so a pepper rotation invalidates every hash).
//   3. Domain separation: changing only the input produces a
//      different output (so a candidate plaintext can be verified
//      by re-hashing with the production pepper).
//   4. Production fails fast on a missing / too-short pepper.
//   5. The output is always 64 lowercase hex chars (matches the
//      `audit_trail.sql` CHECK constraint).
//
// Run from apps/portal:
//   pnpm exec tsx tests/patient-hash.test.ts
// (or via `pnpm test:onboarding` if added to the script set)

import { test } from "node:test";
import assert from "node:assert/strict";
import { hashPatientId, assertProductionPepper } from "../src/lib/patient-hash";

test("hashPatientId is deterministic for the same input and pepper", () => {
  const a = hashPatientId("patient-001", { pepper: "x".repeat(32) });
  const b = hashPatientId("patient-001", { pepper: "x".repeat(32) });
  assert.equal(a, b);
  assert.equal(a.length, 64);
  assert.match(a, /^[0-9a-f]{64}$/);
});

test("hashPatientId is sensitive to the pepper (rotating the pepper invalidates hashes)", () => {
  const a = hashPatientId("patient-001", { pepper: "a".repeat(32) });
  const b = hashPatientId("patient-001", { pepper: "b".repeat(32) });
  assert.notEqual(a, b, "different pepper must produce different hash");
});

test("hashPatientId is sensitive to the input (an attacker can verify a candidate plaintext)", () => {
  const real = hashPatientId("real-patient-id", { pepper: "p".repeat(32) });
  const guess = hashPatientId("wrong-patient-id", { pepper: "p".repeat(32) });
  assert.notEqual(real, guess, "different input must produce different hash");
  // Verify: the same input re-hashed with the same pepper equals the stored hash.
  const verified = hashPatientId("real-patient-id", { pepper: "p".repeat(32) });
  assert.equal(real, verified);
});

test("hashPatientId rejects an empty / non-string input", () => {
  assert.throws(
    () => hashPatientId("", { pepper: "p".repeat(32) }),
    TypeError,
  );
  assert.throws(
    // @ts-expect-error — intentional bad input
    () => hashPatientId(null, { pepper: "p".repeat(32) }),
    TypeError,
  );
  assert.throws(
    // @ts-expect-error — intentional bad input
    () => hashPatientId(123, { pepper: "p".repeat(32) }),
    TypeError,
  );
});

test("hashPatientId rejects input over 1024 chars (P11 round-2 length cap)", () => {
  const tooLong = "a".repeat(1025);
  assert.throws(
    () => hashPatientId(tooLong, { pepper: "p".repeat(32) }),
    /patientId must be <= 1024 chars/,
  );
  // The boundary (exactly 1024) still works.
  const justRight = "a".repeat(1024);
  const h = hashPatientId(justRight, { pepper: "p".repeat(32) });
  assert.equal(h.length, 64);
});

test("hashPatientId falls back to the dev pepper in non-production when no pepper is given", () => {
  const previousNodeEnv = process.env.NODE_ENV;
  try {
    process.env.NODE_ENV = "test";
    delete process.env.PATIENT_HASH_PEPPER;
    // No throw, no env var, no opts → dev fallback.
    const a = hashPatientId("p1");
    const b = hashPatientId("p1");
    assert.equal(a, b);
    assert.equal(a.length, 64);
  } finally {
    if (previousNodeEnv === undefined) {
      delete process.env.NODE_ENV;
    } else {
      process.env.NODE_ENV = previousNodeEnv;
    }
  }
});

test("hashPatientId throws in production when PATIENT_HASH_PEPPER is missing", () => {
  const previousNodeEnv = process.env.NODE_ENV;
  const previousPepper = process.env.PATIENT_HASH_PEPPER;
  try {
    process.env.NODE_ENV = "production";
    delete process.env.PATIENT_HASH_PEPPER;
    assert.throws(
      () => hashPatientId("patient-001"),
      /PATIENT_HASH_PEPPER must be set/,
    );
  } finally {
    if (previousPepper === undefined) {
      delete process.env.PATIENT_HASH_PEPPER;
    } else {
      process.env.PATIENT_HASH_PEPPER = previousPepper;
    }
    if (previousNodeEnv === undefined) {
      delete process.env.NODE_ENV;
    } else {
      process.env.NODE_ENV = previousNodeEnv;
    }
  }
});

test("hashPatientId throws in production when PATIENT_HASH_PEPPER is too short", () => {
  const previousNodeEnv = process.env.NODE_ENV;
  const previousPepper = process.env.PATIENT_HASH_PEPPER;
  try {
    process.env.NODE_ENV = "production";
    process.env.PATIENT_HASH_PEPPER = "short";
    assert.throws(
      () => hashPatientId("patient-001"),
      /PATIENT_HASH_PEPPER must be set/,
    );
  } finally {
    if (previousPepper === undefined) {
      delete process.env.PATIENT_HASH_PEPPER;
    } else {
      process.env.PATIENT_HASH_PEPPER = previousPepper;
    }
    if (previousNodeEnv === undefined) {
      delete process.env.NODE_ENV;
    } else {
      process.env.NODE_ENV = previousNodeEnv;
    }
  }
});

test("assertProductionPepper is a no-op outside production", () => {
  const previousNodeEnv = process.env.NODE_ENV;
  const previousPepper = process.env.PATIENT_HASH_PEPPER;
  try {
    process.env.NODE_ENV = "test";
    delete process.env.PATIENT_HASH_PEPPER;
    assert.doesNotThrow(() => assertProductionPepper());
  } finally {
    if (previousPepper === undefined) {
      delete process.env.PATIENT_HASH_PEPPER;
    } else {
      process.env.PATIENT_HASH_PEPPER = previousPepper;
    }
    if (previousNodeEnv === undefined) {
      delete process.env.NODE_ENV;
    } else {
      process.env.NODE_ENV = previousNodeEnv;
    }
  }
});

test("assertProductionPepper throws in production when PATIENT_HASH_PEPPER is missing or too short", () => {
  const previousNodeEnv = process.env.NODE_ENV;
  const previousPepper = process.env.PATIENT_HASH_PEPPER;
  try {
    process.env.NODE_ENV = "production";
    delete process.env.PATIENT_HASH_PEPPER;
    assert.throws(() => assertProductionPepper(), /PATIENT_HASH_PEPPER/);
    process.env.PATIENT_HASH_PEPPER = "tiny";
    assert.throws(() => assertProductionPepper(), /PATIENT_HASH_PEPPER/);
  } finally {
    if (previousPepper === undefined) {
      delete process.env.PATIENT_HASH_PEPPER;
    } else {
      process.env.PATIENT_HASH_PEPPER = previousPepper;
    }
    if (previousNodeEnv === undefined) {
      delete process.env.NODE_ENV;
    } else {
      process.env.NODE_ENV = previousNodeEnv;
    }
  }
});

test("a sample member-id string is scrubbed to a 64-char hex digest (PHI-scrub smoke)", () => {
  // The "PHI" here is a synthetic member-id-shaped string. The
  // point of the test is to prove the helper never returns the
  // input and never returns a recognisable prefix of the input.
  const sampleMemberId = "OHIP-1234-5678-9012";
  const digest = hashPatientId(sampleMemberId, { pepper: "q".repeat(32) });
  assert.equal(digest.length, 64);
  assert.notEqual(digest.includes(sampleMemberId), true);
  // The digest must not start with the first 8 chars of the input
  // (which would be a sign of an unsalted hash leaking structure).
  assert.notEqual(
    digest.startsWith(sampleMemberId.slice(0, 8).toLowerCase()),
    true,
  );
});
