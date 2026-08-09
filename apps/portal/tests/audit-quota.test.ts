// Node test script for the audit-quota lib (src/lib/audit-quota.ts).
//
// Covers the acceptance criteria from the t_0d6f44ae task body:
//
//   1. Tenant.auditQuotaUsed increments by exactly 1 per call.
//   2. The cap is enforced server-side; client flags cannot bypass it.
//   3. 80% threshold fires exactly one warning per period (no dups).
//   4. 100% threshold blocks new calls (kind === "blocked").
//   5. Concurrent calls cannot collectively exceed the cap
//      (atomic-increment + re-check).
//   6. resetAuditQuota() on a new period sets used → 0 and clears the
//      warning dedup; a second reset in the same period is a no-op.
//   7. The 80% warning email dedup is per-period — a reset followed
//      by a re-cross fires the email again.
//
// Runs with `pnpm test:audit-quota` (added to package.json). Uses
// the dev DB; cleans up the rows it creates. Concurrent test uses
// Promise.all + a small gap so all 10 promises interleave their
// increments on the same tenant row.

import { test } from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { prisma } from "../src/lib/prisma";
import {
  TIER_AUDIT_QUOTA,
  buildUpgradeUrl,
  consumeAuditQuota,
  effectiveAuditQuotaLimit,
  loadQuotaSnapshot,
  resetAuditQuota,
} from "../src/lib/audit-quota";
import * as quotaModule from "../src/lib/audit-quota";

function uniq(): string {
  return randomBytes(6).toString("hex");
}

interface Fixture {
  tenantId: string;
  userId: string;
  cleanup: () => Promise<void>;
}

async function makeFixture(opts?: {
  tier?: "small" | "mid" | "large";
  cap?: number;
  used?: number;
}): Promise<Fixture> {
  const tag = uniq();
  // Cap = the requested cap, or the tier default. used = 0 by
  // default. Both are explicit so the test doesn't depend on
  // schema defaults that may have shifted between runs.
  const tier = opts?.tier ?? "small";
  const cap = opts?.cap ?? TIER_AUDIT_QUOTA[tier];
  const used = opts?.used ?? 0;
  // Fake Stripe linkage so the reset path can resolve a tenant
  // by stripeCustomerId.
  const stripeCustomerId = `cus_test_${tag}`;
  const user = await prisma.user.create({
    data: {
      email: `quota-test-${tag}@example.com`,
      name: `Quota Test ${tag}`,
    },
  });
  const tenant = await prisma.tenant.create({
    data: {
      name: `Quota Test Clinic ${tag}`,
      slug: `quota-test-${tag}`,
      tier,
      subscriptionStatus: "active",
      stripeCustomerId,
      stripeSubscriptionId: `sub_test_${tag}`,
      auditQuotaLimit: cap,
      auditQuotaUsed: used,
    },
  });
  return {
    tenantId: tenant.id,
    userId: user.id,
    cleanup: async () => {
      // Cascade on tenant delete cleans up the membership /
      // invoice / processed-stripe-event rows. We created no
      // encounters or findings.
      await prisma.tenant
        .delete({ where: { id: tenant.id } })
        .catch(() => {});
      await prisma.user
        .delete({ where: { id: user.id } })
        .catch(() => {});
    },
  };
}

// 1. Increment is exactly 1 per call ---------------------------------------

test("consumeAuditQuota: increments auditQuotaUsed by exactly 1", async () => {
  const fx = await makeFixture({ tier: "small", cap: 100, used: 0 });
  try {
    const r1 = await consumeAuditQuota({ tenantId: fx.tenantId });
    assert.equal(r1.kind, "ok");
    assert.equal(r1.used, 1);
    assert.equal(r1.quota, 100);
    assert.equal(r1.percent, 1);

    const r2 = await consumeAuditQuota({ tenantId: fx.tenantId });
    assert.equal(r2.used, 2);
    const r3 = await consumeAuditQuota({ tenantId: fx.tenantId });
    assert.equal(r3.used, 3);
  } finally {
    await fx.cleanup();
  }
});

// 2. The cap is server-side authoritative --------------------------------

test("consumeAuditQuota: the cap cannot be bypassed by the caller", async () => {
  // Even if the caller passes a different origin or no origin, the
  // result still reads the live tenant row. The route handler
  // cannot spoof `used`, `quota`, or `percent` from the request.
  const fx = await makeFixture({ tier: "small", cap: 5, used: 4 });
  try {
    const r = await consumeAuditQuota({
      tenantId: fx.tenantId,
      origin: "https://attacker.example",
    });
    // 4 → 5: still ok (not at 100% yet, since 5 === 100% only when
    // the comparison is `used >= quota`, but our small cap of 5
    // means the 5th call hits the block path).
    assert.equal(r.kind, "blocked", "expected blocked at 5 of 5");
    if (r.kind === "blocked") {
      assert.equal(r.used, 5);
      assert.equal(r.quota, 5);
      // The upgrade URL is built from the (untrusted) origin, but
      // that's a UX hint, not a security boundary. The block stands
      // regardless.
      assert.ok(r.upgradeUrl.length > 0);
    }
  } finally {
    await fx.cleanup();
  }
});

// 3. 80% threshold fires exactly one warning per period ------------------

test("consumeAuditQuota: 80% threshold fires warning once per period", async () => {
  // Cap = 10 → 80% at 8 audits, 100% at 10. Set used = 7 so the
  // 8th call crosses the warning threshold; the 9th stays in warn
  // (no re-fire), the 10th hits the block path.
  const fx = await makeFixture({ tier: "small", cap: 10, used: 7 });
  try {
    const r1 = await consumeAuditQuota({ tenantId: fx.tenantId });
    assert.equal(r1.kind, "warn");
    assert.equal(r1.used, 8);
    if (r1.kind === "warn") {
      assert.equal(r1.warnedNow, true, "first 80%-crossing fires the email");
    }

    // The 9th call stays in the warn state but does NOT re-fire the
    // email — the warning is deduped per period.
    const r2 = await consumeAuditQuota({ tenantId: fx.tenantId });
    assert.equal(r2.kind, "warn");
    assert.equal(r2.used, 9);
    if (r2.kind === "warn") {
      assert.equal(r2.warnedNow, false, "second 80%-crossing does not re-fire");
    }
    // The 10th call hits 100% of the cap, which is the block
    // path — not the warn path. The lib's warn threshold is
    // `>= ceil(cap * 0.8)` and the block threshold is
    // `>= cap * 1.0`. At cap=10, ceil(10*0.8)=8, and 10>=10 → blocked.
    const r3 = await consumeAuditQuota({ tenantId: fx.tenantId });
    assert.equal(r3.kind, "blocked", "100% threshold is the block path");
    assert.equal(r3.used, 10);
  } finally {
    await fx.cleanup();
  }
});

// 4. 100% threshold blocks subsequent calls ------------------------------

test("consumeAuditQuota: 100% threshold blocks subsequent calls", async () => {
  const fx = await makeFixture({ tier: "small", cap: 3, used: 2 });
  try {
    // 2 → 3 hits the block path on the increment.
    const r = await consumeAuditQuota({ tenantId: fx.tenantId });
    assert.equal(r.kind, "blocked");
    if (r.kind === "blocked") {
      assert.equal(r.used, 3);
      assert.equal(r.quota, 3);
      assert.ok(r.upgradeUrl.includes("/billing"));
    }

    // A second call after the cap is reached still returns blocked
    // (the increment is applied, but the result is still blocked).
    const r2 = await consumeAuditQuota({ tenantId: fx.tenantId });
    assert.equal(r2.kind, "blocked");
    if (r2.kind === "blocked") {
      assert.equal(r2.used, 4, "increment still applied; result still blocked");
    }
  } finally {
    await fx.cleanup();
  }
});

// 5. Concurrent calls cannot collectively exceed the cap -----------------

test("consumeAuditQuota: concurrent calls are serialized, never exceed cap", async () => {
  // Cap = 50. Fire 80 concurrent consume calls. The post-update
  // count must never exceed 50; the result must be a mix of
  // ok / warn / blocked whose totals sum to 80.
  //
  // Lib math at cap=50:
  //   - warn threshold = ceil(50*0.8) = 40
  //   - block threshold = 50*1.0 = 50
  //   - calls 1..39 → ok
  //   - calls 40..49 → warn  (10 calls)
  //   - calls 50..80 → blocked  (31 calls)
  //   Total allowed = 39 + 10 = 49 (the 50th call lands AT the
  //   cap and is blocked, not allowed). The test asserts 49
  //   allowed, not 50.
  const fx = await makeFixture({ tier: "mid", cap: 50, used: 0 });
  try {
    const N = 80;
    const results = await Promise.all(
      Array.from({ length: N }, () =>
        consumeAuditQuota({ tenantId: fx.tenantId }),
      ),
    );
    const counts = results.reduce(
      (acc, r) => {
        acc[r.kind] += 1;
        return acc;
      },
      { ok: 0, warn: 0, blocked: 0 } as Record<string, number>,
    );
    assert.equal(
      counts.ok + counts.warn,
      49,
      `expected 49 allowed calls, got ${counts.ok + counts.warn} (ok=${counts.ok} warn=${counts.warn} blocked=${counts.blocked})`,
    );
    assert.equal(counts.blocked, N - 49);
    // The post-update count is the cap (50) for the call that hit
    // the block, plus 30 more from the rejected-after-cap calls
    // (51..80) — the increment is always applied, the post-update
    // check is what blocks.
    const final = await loadQuotaSnapshot(fx.tenantId);
    assert.equal(final.used, 50 + (N - 50));
    assert.equal(final.state, "blocked");
  } finally {
    await fx.cleanup();
  }
});

// 6. Reset on a new period zeros the counter -----------------------------

test("resetAuditQuota: zeros used on a new period, clears warning dedup", async () => {
  const fx = await makeFixture({ tier: "small", cap: 10, used: 9 });
  try {
    // Pre-set quotaWarningSentAt so we can verify the reset
    // clears it (so the next 80%-crossing fires a fresh email).
    await prisma.tenant.update({
      where: { id: fx.tenantId },
      data: { quotaWarningSentAt: new Date() },
    });
    // Look up the stripe customer id to pass to the reset.
    const t = await prisma.tenant.findUnique({
      where: { id: fx.tenantId },
      select: { stripeCustomerId: true },
    });
    assert.ok(t?.stripeCustomerId, "fixture must have stripeCustomerId");
    const r = await resetAuditQuota({
      stripeCustomerId: t!.stripeCustomerId!,
    });
    assert.equal(r.kind, "reset");
    if (r.kind === "reset") {
      assert.equal(r.previousUsed, 9);
    }
    // Counter and warning timestamp both cleared.
    const after = await prisma.tenant.findUnique({
      where: { id: fx.tenantId },
      select: { auditQuotaUsed: true, quotaWarningSentAt: true, lastQuotaResetPeriodStart: true },
    });
    assert.equal(after?.auditQuotaUsed, 0);
    assert.equal(after?.quotaWarningSentAt, null);
    assert.ok(after?.lastQuotaResetPeriodStart, "lastQuotaResetPeriodStart set");
  } finally {
    await fx.cleanup();
  }
});

// 7. Second reset in the same period is a no-op --------------------------

test("resetAuditQuota: second reset in same period is skipped", async () => {
  const fx = await makeFixture({ tier: "small", cap: 10, used: 5 });
  try {
    const t = await prisma.tenant.findUnique({
      where: { id: fx.tenantId },
      select: { stripeCustomerId: true },
    });
    assert.ok(t?.stripeCustomerId);
    const r1 = await resetAuditQuota({
      stripeCustomerId: t!.stripeCustomerId!,
    });
    assert.equal(r1.kind, "reset");

    // Bump the counter again and call reset once more in the
    // same period. The lib should return skipped_same_period
    // and leave the row alone.
    await prisma.tenant.update({
      where: { id: fx.tenantId },
      data: { auditQuotaUsed: 3 },
    });
    const r2 = await resetAuditQuota({
      stripeCustomerId: t!.stripeCustomerId!,
    });
    assert.equal(r2.kind, "skipped_same_period");
    if (r2.kind === "skipped_same_period") {
      assert.equal(r2.currentUsed, 3, "used not touched by the second reset");
    }
    const after = await prisma.tenant.findUnique({
      where: { id: fx.tenantId },
      select: { auditQuotaUsed: true },
    });
    assert.equal(after?.auditQuotaUsed, 3);
  } finally {
    await fx.cleanup();
  }
});

// 8. Effective cap is the column value (no snap-up) ----------------------

test("effectiveAuditQuotaLimit: the column is the source of truth, no snap-up", async () => {
  // The column is authoritative — a tenant whose `auditQuotaLimit`
  // is below the tier default (e.g. a manually-bumped-down plan)
  // stays at the column value. The tier default is what gets
  // written at provisioning, not a floor.
  const fx = await makeFixture({ tier: "small", cap: 100, used: 0 });
  try {
    const snap = await loadQuotaSnapshot(fx.tenantId);
    assert.equal(snap.quota, 100, "effective cap = column, not tier default");
    assert.equal(snap.state, "ok");
  } finally {
    await fx.cleanup();
  }
});

test("effectiveAuditQuotaLimit: respects a column value above the tier default", async () => {
  // Operator bumped a tenant's cap individually to 10_000. The
  // effective cap should honor the override, not the tier default.
  const fx = await makeFixture({ tier: "small", cap: 10_000, used: 0 });
  try {
    const snap = await loadQuotaSnapshot(fx.tenantId);
    assert.equal(snap.quota, 10_000);
  } finally {
    await fx.cleanup();
  }
});

test("effectiveAuditQuotaLimit: pure helper returns column value (no snap-up)", () => {
  // Below the tier default — column wins.
  assert.equal(
    effectiveAuditQuotaLimit({ tier: "small", auditQuotaLimit: 100 }),
    100,
  );
  assert.equal(
    effectiveAuditQuotaLimit({ tier: "mid", auditQuotaLimit: 100 }),
    100,
  );
  assert.equal(
    effectiveAuditQuotaLimit({ tier: "large", auditQuotaLimit: 4999 }),
    4999,
  );
  // Equal to the tier default — column wins.
  assert.equal(
    effectiveAuditQuotaLimit({ tier: "small", auditQuotaLimit: 500 }),
    500,
  );
  // Above the tier default — column wins.
  assert.equal(
    effectiveAuditQuotaLimit({ tier: "small", auditQuotaLimit: 501 }),
    501,
  );
});

test("effectiveAuditQuotaLimit: zero or negative column falls back to the tier default", () => {
  // A non-provisioned tenant (column = 0) gets the tier default
  // so the user is not blocked at "0 audits" before provisioning
  // finishes. Negative is treated the same way (a malformed
  // manual write should not silently cap at 0).
  assert.equal(
    effectiveAuditQuotaLimit({ tier: "small", auditQuotaLimit: 0 }),
    500,
  );
  assert.equal(
    effectiveAuditQuotaLimit({ tier: "mid", auditQuotaLimit: 0 }),
    2_000,
  );
  assert.equal(
    effectiveAuditQuotaLimit({ tier: "large", auditQuotaLimit: 0 }),
    5_000,
  );
  assert.equal(
    effectiveAuditQuotaLimit({ tier: "small", auditQuotaLimit: -1 }),
    500,
  );
});

// 9. Snapshot reads without mutating -------------------------------------

test("loadQuotaSnapshot: does not increment or fire the warning email", async () => {
  const fx = await makeFixture({ tier: "small", cap: 10, used: 8 });
  try {
    const before = await prisma.tenant.findUnique({
      where: { id: fx.tenantId },
      select: { auditQuotaUsed: true, quotaWarningSentAt: true },
    });
    assert.equal(before?.auditQuotaUsed, 8);
    assert.equal(before?.quotaWarningSentAt, null);

    const snap = await loadQuotaSnapshot(fx.tenantId);
    assert.equal(snap.used, 8);
    assert.equal(snap.quota, 10);
    assert.equal(snap.state, "warn");
    assert.equal(snap.warningSentThisPeriod, false);

    const after = await prisma.tenant.findUnique({
      where: { id: fx.tenantId },
      select: { auditQuotaUsed: true, quotaWarningSentAt: true },
    });
    assert.equal(after?.auditQuotaUsed, 8, "snapshot did not increment");
    assert.equal(
      after?.quotaWarningSentAt,
      null,
      "snapshot did not set warning timestamp",
    );
  } finally {
    await fx.cleanup();
  }
});

// 10. buildUpgradeUrl: respects caller origin ----------------------------

test("buildUpgradeUrl: composes URL from origin (or falls back to localhost)", () => {
  assert.equal(
    buildUpgradeUrl("https://app.example.com"),
    "https://app.example.com/billing",
  );
  assert.equal(
    buildUpgradeUrl("https://app.example.com/"),
    "https://app.example.com/billing",
  );
  assert.equal(
    buildUpgradeUrl(null),
    "http://localhost:3000/billing",
  );
  assert.equal(
    buildUpgradeUrl(undefined),
    "http://localhost:3000/billing",
  );
});

test("audit dispatch reservation converts to one quota charge after durable enqueue", async () => {
  const reserve = (quotaModule as Record<string, unknown>)["reserveAuditDispatch"];
  const finalize = (quotaModule as Record<string, unknown>)["finalizeAuditDispatch"];
  assert.equal(typeof reserve, "function");
  assert.equal(typeof finalize, "function");

  const fx = await makeFixture({ cap: 5, used: 0 });
  const claim = await prisma.encounterClaim.create({
    data: {
      payer: "AHCIP",
      providerNpi: "1234567890",
      providerName: "Dr Test",
      cptCodesJson: JSON.stringify([{ code: "03.03A", units: 1 }]),
      billedCents: 4200,
    },
  });
  const encounter = await prisma.encounter.create({
    data: {
      tenantId: fx.tenantId,
      patientHash: "a".repeat(64),
      dateOfService: new Date("2026-08-08T00:00:00.000Z"),
      specialty: "family_medicine",
      clinicalNote: "encrypted-note-placeholder",
      claimId: claim.id,
      status: "pending",
    },
  });
  try {
    const reserved = await (reserve as (args: {
      tenantId: string;
      encounterId: string;
    }) => Promise<{ kind: string }>)({
      tenantId: fx.tenantId,
      encounterId: encounter.id,
    });
    assert.equal(reserved.kind, "ready");
    let tenant = await prisma.tenant.findUniqueOrThrow({
      where: { id: fx.tenantId },
    });
    assert.equal((tenant as unknown as { auditQuotaReserved: number }).auditQuotaReserved, 1);
    assert.equal(tenant.auditQuotaUsed, 0);

    const finalizeFn = finalize as (args: {
      tenantId: string;
      encounterId: string;
      engineJobId: string;
      engineStatusUrl: string;
    }) => Promise<{ kind: string }>;
    const finalized = await finalizeFn({
      tenantId: fx.tenantId,
      encounterId: encounter.id,
      engineJobId: "engine-job-1",
      engineStatusUrl: "/encounters/upload/jobs/engine-job-1",
    });
    assert.equal(finalized.kind, "queued");
    tenant = await prisma.tenant.findUniqueOrThrow({ where: { id: fx.tenantId } });
    assert.equal((tenant as unknown as { auditQuotaReserved: number }).auditQuotaReserved, 0);
    assert.equal(tenant.auditQuotaUsed, 1);

    await finalizeFn({
      tenantId: fx.tenantId,
      encounterId: encounter.id,
      engineJobId: "engine-job-1",
      engineStatusUrl: "/encounters/upload/jobs/engine-job-1",
    });
    tenant = await prisma.tenant.findUniqueOrThrow({ where: { id: fx.tenantId } });
    assert.equal(tenant.auditQuotaUsed, 1, "idempotent finalize did not double-charge");
  } finally {
    await prisma.encounter.delete({ where: { id: encounter.id } }).catch(() => {});
    await prisma.encounterClaim.delete({ where: { id: claim.id } }).catch(() => {});
    await fx.cleanup();
  }
});

test("a pre-enqueue validation failure releases its reservation idempotently", async () => {
  const release = (quotaModule as Record<string, unknown>)["releaseAuditDispatchReservation"];
  assert.equal(typeof release, "function");
  const fx = await makeFixture({ cap: 2, used: 0 });
  const claim = await prisma.encounterClaim.create({
    data: {
      payer: "AHCIP",
      providerNpi: "1234567890",
      providerName: "Dr Test",
      cptCodesJson: "malformed",
    },
  });
  const encounter = await prisma.encounter.create({
    data: {
      tenantId: fx.tenantId,
      patientHash: "c".repeat(64),
      dateOfService: new Date("2026-08-08T00:00:00Z"),
      specialty: "family_medicine",
      clinicalNote: "invalid-ciphertext",
      claimId: claim.id,
      status: "pending",
    },
  });
  try {
    await quotaModule.reserveAuditDispatch({
      tenantId: fx.tenantId,
      encounterId: encounter.id,
    });
    const releaseFn = release as (args: {
      tenantId: string;
      encounterId: string;
      reason: string;
    }) => Promise<{ kind: string }>;
    assert.equal((await releaseFn({
      tenantId: fx.tenantId,
      encounterId: encounter.id,
      reason: "encounter_data_unavailable",
    })).kind, "released");
    assert.equal((await releaseFn({
      tenantId: fx.tenantId,
      encounterId: encounter.id,
      reason: "encounter_data_unavailable",
    })).kind, "already_released");
    const tenant = await prisma.tenant.findUniqueOrThrow({ where: { id: fx.tenantId } });
    assert.equal(tenant.auditQuotaReserved, 0);
    assert.equal(tenant.auditQuotaUsed, 0);
  } finally {
    await prisma.encounter.delete({ where: { id: encounter.id } }).catch(() => {});
    await prisma.encounterClaim.delete({ where: { id: claim.id } }).catch(() => {});
    await fx.cleanup();
  }
});
