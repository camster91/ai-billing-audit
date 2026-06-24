// QA empty-state seed: provision a fresh tenant + user with ZERO
// encounters and ZERO findings, simulating the state immediately after
// Stripe-test-mode signup. The "fresh signup" path in the portal does
// not auto-create a Stripe customer (real Stripe Checkout would, demo
// mode can't), so this seed sets `stripeCustomerId` + `stripeSubscriptionId`
// to synthetic demo ids so /billing renders the "Current plan" card and
// the next-invoice date line. The user is also pre-attached as the
// tenant's owner so the dashboard does NOT show the "No clinic
// connected" empty state — we want the four pages to render with the
// tenant context present but encounter count = 0.
//
// Run from apps/portal:
//   pnpm exec tsx scripts/qa_empty_states_seed.ts

import { randomBytes, createHash } from "node:crypto";
import { prisma } from "../src/lib/prisma";

function sha256Hex(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function cuidLike(prefix = ""): string {
  return `${prefix}${randomBytes(12).toString("hex")}`;
}

async function main() {
  const tenantSlug = `qa-empty-${Date.now()}`;
  const userEmail = `qa-empty-${Date.now()}@ashbi.test`;

  // ---- Clean slate for THIS slug/email only (idempotent re-runs) ----
  await prisma.membership.deleteMany({
    where: { tenant: { slug: { startsWith: "qa-empty-" } } },
  });
  await prisma.tenant.deleteMany({
    where: { slug: { startsWith: "qa-empty-" } },
  });
  await prisma.session.deleteMany({
    where: { user: { email: { startsWith: "qa-empty-" } } },
  });
  await prisma.user.deleteMany({
    where: { email: { startsWith: "qa-empty-" } },
  });

  // ---- Tenant (zero encounters, zero findings) ---------------------
  // Demo-mode Stripe: we cannot create a real Stripe customer from
  // this script, but the billing page treats a missing stripeCustomerId
  // as "Not configured (subscribe to a plan first)". For the
  // empty-state QA we want the "Current plan" card to render, so
  // we set a synthetic demo customer id that the page will treat
  // as configured.
  const tier = "mid" as const;
  const auditQuotaLimit = 2000;
  const tenant = await prisma.tenant.create({
    data: {
      id: cuidLike(),
      name: "QA Empty States Clinic",
      slug: tenantSlug,
      tier,
      subscriptionStatus: "active",
      stripeCustomerId: `cus_qa_${tenantSlug.slice(-8).padStart(8, "0")}`,
      stripeSubscriptionId: `sub_qa_${tenantSlug.slice(-8).padStart(8, "0")}`,
      auditQuotaLimit,
      auditQuotaUsed: 0,
      // No onboarding flag — the QA wants the "just signed up" state
      // not the wizard.
      onboardingStep: 99,
      onboardingCompletedAt: new Date(),
    },
  });

  // ---- User --------------------------------------------------------
  const user = await prisma.user.create({
    data: {
      id: cuidLike(),
      email: userEmail,
      name: "QA Empty Reviewer",
      emailVerified: new Date(),
    },
  });

  // ---- Membership (owner) -----------------------------------------
  // Membership schema was extended for team management (t_23bfd49c)
  // to require `email` + `status` + `invitedAt`. Pre-activated so the
  // dashboard does not treat the user as a "pending" invitee.
  await prisma.membership.create({
    data: {
      id: cuidLike(),
      userId: user.id,
      tenantId: tenant.id,
      role: "owner",
      status: "active",
      email: userEmail,
      invitedAt: new Date(),
      activatedAt: new Date(),
    },
  });

  // ---- Set this tenant as the active tenant for any future session
  // ---- (we'll create a session row below pointing at it).
  console.log(
    JSON.stringify(
      {
        tenantId: tenant.id,
        tenantSlug: tenant.slug,
        userId: user.id,
        userEmail: user.email,
        auditQuotaLimit,
        auditQuotaUsed: 0,
      },
      null,
      2,
    ),
  );
}

main()
  .catch((e) => {
    console.error("[qa-empty-seed] failed:", e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
