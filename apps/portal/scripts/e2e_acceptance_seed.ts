// One-shot seed: provision the E2E tenant + user + encounter + findings
// the acceptance test will exercise. The seed pre-creates an "already
// onboarded" tenant so the E2E can hit /portal/onboarding?session_id=...
// and (because the redeem endpoint is idempotent on already-redeemed
// sessions) get a Tenant that's "fresh" from the wizard's perspective
// — we reset onboardingStep/onboardingCompletedAt so the wizard renders
// the step 0 form on the next visit.
//
// The encounter + 2 findings are pre-created because the audit-runner
// pipeline (Python DSPy loop enqueuing from `firstEncounterFilePath`)
// is not wired through the portal yet. The seed simulates the audit
// having completed.
//
// Run from apps/portal:
//   pnpm exec tsx scripts/e2e_acceptance_seed.ts

import { randomBytes, createHash } from "node:crypto";
import { prisma } from "../src/lib/prisma";

function sha256Hex(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function cuidLike(prefix = ""): string {
  return `${prefix}${randomBytes(12).toString("hex")}`;
}

async function main() {
  const tenantSlug = process.env["E2E_TENANT_SLUG"] || "e2e-clinic";
  const userEmail = process.env["E2E_USER_EMAIL"] || "[email protected]";
  const tier = (process.env["E2E_TIER"] || "mid") as "small" | "mid" | "large";

  // ---- Clean slate ----------------------------------------------------
  await prisma.auditTrailEntry.deleteMany({
    where: { tenant: { slug: tenantSlug } },
  });
  await prisma.finding.deleteMany({
    where: { encounter: { tenant: { slug: tenantSlug } } },
  });
  await prisma.encounter.deleteMany({
    where: { tenant: { slug: tenantSlug } },
  });
  await prisma.encounterClaim.deleteMany({
    where: { encounter: { tenant: { slug: tenantSlug } } },
  });
  await prisma.membership.deleteMany({
    where: { tenant: { slug: tenantSlug } },
  });
  await prisma.redeemedCheckoutSession.deleteMany({
    where: { tenant: { slug: tenantSlug } },
  });
  await prisma.session.deleteMany({ where: { user: { email: userEmail } } });
  await prisma.tenant.deleteMany({ where: { slug: tenantSlug } });
  await prisma.user.deleteMany({ where: { email: userEmail } });

  // ---- Tenant (not yet onboarded — wizard will drive the steps) ------
  const auditQuotaLimit = tier === "mid" ? 2000 : tier === "large" ? 5000 : 500;
  const tenant = await prisma.tenant.create({
    data: {
      id: cuidLike(),
      name: "e2e-clinic",
      slug: tenantSlug,
      tier,
      subscriptionStatus: "active",
      stripeCustomerId: `cus_e2e_${tenantSlug.slice(-8).padStart(8, "0")}`,
      stripeSubscriptionId: `sub_e2e_${tenantSlug.slice(-8).padStart(8, "0")}`,
      auditQuotaLimit,
      // onboardingStep starts at 0; the redeem route will bump to 1.
      onboardingStep: 0,
    },
  });

  // ---- User -----------------------------------------------------------
  const user = await prisma.user.create({
    data: {
      id: cuidLike(),
      email: userEmail,
      name: "E2E Reviewer",
      emailVerified: new Date(),
    },
  });
  // Note: NO membership yet. The redeem route will attach the user as
  // owner when the wizard is driven.

  console.log(JSON.stringify({
    tenantId: tenant.id,
    tenantSlug: tenant.slug,
    userId: user.id,
    userEmail: user.email,
    // No encounter yet — the seed pre-creates it after the wizard
    // completes (see scripts/e2e_acceptance_post_seed.ts). The E2E
    // runner orchestrates both.
  }, null, 2));
}

main()
  .catch((e) => {
    console.error("[e2e-seed] failed:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
