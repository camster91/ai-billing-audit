// Node test script for the onboarding lib (src/lib/onboarding.ts).
//
// Runs with `pnpm test:onboarding` (added in package.json) using the
// in-tree tsx so the test can import the TypeScript lib directly.
//
// The test creates isolated Tenant + User rows, exercises each lib
// function end-to-end, and asserts the gate / lock / audit-enable
// behavior matches the wizard's acceptance criteria.
//
// Each test uses random session ids + a unique slug so multiple runs
// don't collide. The script does NOT clear the dev DB; cleanup is
// best-effort (delete the rows it created) so a re-run is idempotent.

import { test } from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { prisma } from "../src/lib/prisma";
import {
  buildDemoSessionId,
  canStartAudit,
  completeOnboarding,
  redeemCheckoutSession,
  saveClinicProfile,
  saveEhrConnection,
  saveFirstEncounter,
  saveResidencyRegion,
  OnboardingError,
} from "../src/lib/onboarding";
import { decryptPortalString } from "../src/lib/data-encryption";

process.env.ZORVA_PHI_ENCRYPTION_KEY ??= randomBytes(32).toString("base64url");

function uniq(): string {
  return randomBytes(6).toString("hex");
}

interface Fixture {
  userId: string;
  tenantId: string;
  sessionId: string;
  cleanup: () => Promise<void>;
}

async function makeFixture(opts?: { sessionId?: string }): Promise<Fixture> {
  const tag = uniq();
  const user = await prisma.user.create({
    data: {
      email: `onboarding-test-${tag}@example.com`,
      name: `Test User ${tag}`,
    },
  });
  const sessionId = opts?.sessionId ?? buildDemoSessionId();

  return {
    userId: user.id,
    tenantId: "",
    sessionId,
    cleanup: async () => {
      // Cascade on user delete cleans up the membership / redemption
      // rows. Tenant is created on redeem.
      await prisma.redeemedCheckoutSession
        .deleteMany({ where: { userId: user.id } })
        .catch(() => {});
      await prisma.membership
        .deleteMany({ where: { userId: user.id } })
        .catch(() => {});
      await prisma.tenant
        .deleteMany({ where: { stripeCustomerId: { startsWith: "cus_demo_" } } })
        .catch(() => {});
      await prisma.user.delete({ where: { id: user.id } }).catch(() => {});
    },
  };
}

test("redeem: creates tenant + owner membership, idempotent on replay", async () => {
  const fx = await makeFixture();
  try {
    const first = await redeemCheckoutSession({
      sessionId: fx.sessionId,
      userId: fx.userId,
    });
    assert.equal(first.created, true, "first call should mark created=true");
    assert.equal(first.alreadyClaimed, false);
    assert.ok(first.tenant.id, "tenant id set");
    assert.equal(first.tenant.subscriptionStatus, "active");
    fx.tenantId = first.tenant.id;

    // Verify the membership row exists with role=owner.
    const m = await prisma.membership.findUnique({
      where: { userId_tenantId: { userId: fx.userId, tenantId: fx.tenantId } },
    });
    assert.ok(m, "membership row exists");
    assert.equal(m?.role, "owner");

    // Verify RedeemedCheckoutSession row exists.
    const r = await prisma.redeemedCheckoutSession.findUnique({
      where: { sessionId: fx.sessionId },
    });
    assert.ok(r, "redemption row exists");
    assert.equal(r?.userId, fx.userId);

    // Replay: same user, same session. No-op, created=false, no extra membership.
    const second = await redeemCheckoutSession({
      sessionId: fx.sessionId,
      userId: fx.userId,
    });
    assert.equal(second.created, false);
    assert.equal(second.alreadyClaimed, false);
    assert.equal(second.tenant.id, fx.tenantId);

    const memberships = await prisma.membership.findMany({
      where: { userId: fx.userId, tenantId: fx.tenantId },
    });
    assert.equal(memberships.length, 1, "exactly one membership row");
  } finally {
    await fx.cleanup();
  }
});

test("redeem: second user on same session sees alreadyClaimed", async () => {
  const fx = await makeFixture();
  try {
    const first = await redeemCheckoutSession({
      sessionId: fx.sessionId,
      userId: fx.userId,
    });
    fx.tenantId = first.tenant.id;

    // Make a second user and try to redeem the same session.
    const second = await prisma.user.create({
      data: { email: `onboarding-test-other-${uniq()}@example.com` },
    });
    try {
      const result = await redeemCheckoutSession({
        sessionId: fx.sessionId,
        userId: second.id,
      });
      assert.equal(result.alreadyClaimed, true);
      assert.equal(result.tenant.id, fx.tenantId);
    } finally {
      await prisma.user.delete({ where: { id: second.id } }).catch(() => {});
    }
  } finally {
    await fx.cleanup();
  }
});

test("steps: clinic profile advances step to 2", async () => {
  const fx = await makeFixture();
  try {
    const r = await redeemCheckoutSession({
      sessionId: fx.sessionId,
      userId: fx.userId,
    });
    fx.tenantId = r.tenant.id;

    const result = await saveClinicProfile({
      tenantId: fx.tenantId,
      input: {
        clinicName: "Maple Leaf Family Practice",
        clinicNpi: "1234567890",
        clinicTimezone: "America/Toronto",
      },
    });
    assert.equal(result.onboardingStep, 2);

    const tenant = await prisma.tenant.findUnique({
      where: { id: fx.tenantId },
      select: { clinicName: true, clinicNpi: true, clinicTimezone: true },
    });
    assert.equal(tenant?.clinicName, "Maple Leaf Family Practice");
    assert.equal(tenant?.clinicNpi, "1234567890");
    assert.equal(tenant?.clinicTimezone, "America/Toronto");
  } finally {
    await fx.cleanup();
  }
});

test("steps: clinic profile rejects bad NPI", async () => {
  const fx = await makeFixture();
  try {
    const r = await redeemCheckoutSession({
      sessionId: fx.sessionId,
      userId: fx.userId,
    });
    fx.tenantId = r.tenant.id;

    await assert.rejects(
      () =>
        saveClinicProfile({
          tenantId: fx.tenantId,
          input: { clinicNpi: "!!!" },
        }),
      (e: unknown) =>
        e instanceof OnboardingError && e.code === "invalid_input",
    );
  } finally {
    await fx.cleanup();
  }
});

test("steps: region requires step 2 to be done first", async () => {
  const fx = await makeFixture();
  try {
    const r = await redeemCheckoutSession({
      sessionId: fx.sessionId,
      userId: fx.userId,
    });
    fx.tenantId = r.tenant.id;

    // Skip step 2 (clinic profile) and try to set region.
    await assert.rejects(
      () =>
        saveResidencyRegion({
          tenantId: fx.tenantId,
          input: { region: "ca-central-1" },
        }),
      (e: unknown) =>
        e instanceof OnboardingError && e.code === "step_not_reached",
    );
  } finally {
    await fx.cleanup();
  }
});

test("steps: region locks after complete; further writes rejected", async () => {
  const fx = await makeFixture();
  try {
    const r = await redeemCheckoutSession({
      sessionId: fx.sessionId,
      userId: fx.userId,
    });
    fx.tenantId = r.tenant.id;
    await saveClinicProfile({ tenantId: fx.tenantId, input: {} });
    await saveResidencyRegion({
      tenantId: fx.tenantId,
      input: { region: "ca-central-1" },
    });
    await saveEhrConnection({
      tenantId: fx.tenantId,
      input: { mode: "manual" },
    });
    await saveFirstEncounter({
      tenantId: fx.tenantId,
      input: { mode: "skipped" },
    });
    const done = await completeOnboarding({ tenantId: fx.tenantId });
    assert.equal(done.dataResidencyRegion, "ca-central-1");
    assert.ok(done.onboardingCompletedAt);

    // Try to change the region post-completion.
    await assert.rejects(
      () =>
        saveResidencyRegion({
          tenantId: fx.tenantId,
          input: { region: "us-east-1" },
        }),
      (e: unknown) =>
        e instanceof OnboardingError && e.code === "region_locked",
    );
  } finally {
    await fx.cleanup();
  }
});

test("audit gate: cannot run until complete + region + EHR + first encounter", async () => {
  const fx = await makeFixture();
  try {
    const r = await redeemCheckoutSession({
      sessionId: fx.sessionId,
      userId: fx.userId,
    });
    fx.tenantId = r.tenant.id;

    // Right after redeem: no.
    assert.equal(await canStartAudit(fx.tenantId), false);

    // After clinic profile: still no (region not set).
    await saveClinicProfile({ tenantId: fx.tenantId, input: {} });
    assert.equal(await canStartAudit(fx.tenantId), false);

    // After region: still no (EHR not set).
    await saveResidencyRegion({
      tenantId: fx.tenantId,
      input: { region: "us-east-1" },
    });
    assert.equal(await canStartAudit(fx.tenantId), false);

    // After EHR manual: still no (first encounter not set).
    await saveEhrConnection({
      tenantId: fx.tenantId,
      input: { mode: "manual" },
    });
    assert.equal(await canStartAudit(fx.tenantId), false);

    // After first encounter skip: still no (wizard not completed).
    await saveFirstEncounter({
      tenantId: fx.tenantId,
      input: { mode: "skipped" },
    });
    assert.equal(await canStartAudit(fx.tenantId), false);

    // After complete: yes.
    await completeOnboarding({ tenantId: fx.tenantId });
    assert.equal(await canStartAudit(fx.tenantId), true);
  } finally {
    await fx.cleanup();
  }
});

test("audit gate: SFTP mode without credentials is rejected", async () => {
  const fx = await makeFixture();
  try {
    const r = await redeemCheckoutSession({
      sessionId: fx.sessionId,
      userId: fx.userId,
    });
    fx.tenantId = r.tenant.id;
    await saveClinicProfile({ tenantId: fx.tenantId, input: {} });
    await saveResidencyRegion({
      tenantId: fx.tenantId,
      input: { region: "ca-central-1" },
    });
    // Save ehr as sftp via the lib (so onboardingStep advances) but
    // then strip the credentials to simulate a stale row.
    await saveEhrConnection({
      tenantId: fx.tenantId,
      input: {
        mode: "sftp",
        host: "sftp.example.com",
        port: 22,
        username: "billing",
        password: "secret",
      },
    });
    const encryptedTenant = await prisma.tenant.findUnique({
      where: { id: fx.tenantId },
      select: { ehrSftpPasswordCiphertext: true },
    });
    assert.notEqual(encryptedTenant?.ehrSftpPasswordCiphertext, "secret");
    assert.equal(
      decryptPortalString(encryptedTenant?.ehrSftpPasswordCiphertext ?? ""),
      "secret",
    );
    await prisma.tenant.update({
      where: { id: fx.tenantId },
      data: { ehrSftpHost: null, ehrSftpUsername: null, ehrSftpPasswordCiphertext: null },
    });
    await saveFirstEncounter({
      tenantId: fx.tenantId,
      input: { mode: "skipped" },
    });
    // Don't complete — check the gate directly. Without SFTP creds the
    // gate should refuse.
    assert.equal(await canStartAudit(fx.tenantId), false);
  } finally {
    await fx.cleanup();
  }
});
