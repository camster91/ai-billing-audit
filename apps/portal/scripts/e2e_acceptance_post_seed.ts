// Post-wizard seed: after the E2E acceptance test walks the onboarding
// wizard to completion, the runner invokes this script to provision
// the encounter + 2 findings + 1 invoice. These simulate the audit
// pipeline having run and Stripe having sent the first invoice.
//
// Run from apps/portal:
//   E2E_TENANT_SLUG=e2e-clinic E2E_USER_EMAIL=... pnpm exec tsx scripts/e2e_acceptance_post_seed.ts

import { randomBytes, createHash } from "node:crypto";
import { prisma } from "../src/lib/prisma";
import { encryptPortalString } from "../src/lib/data-encryption";

function sha256Hex(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function cuidLike(prefix = ""): string {
  return `${prefix}${randomBytes(12).toString("hex")}`;
}

async function main() {
  const tenantSlug = process.env["E2E_TENANT_SLUG"] || "e2e-clinic";
  const userEmail = process.env["E2E_USER_EMAIL"] || "[email protected]";

  const tenant = await prisma.tenant.findUnique({ where: { slug: tenantSlug } });
  if (!tenant) {
    throw new Error(`tenant ${tenantSlug} not found — run the e2e_acceptance_seed.ts first`);
  }
  const user = await prisma.user.findUnique({ where: { email: userEmail } });
  if (!user) {
    throw new Error(`user ${userEmail} not found — wizard must have created them`);
  }
  if (!tenant.onboardingCompletedAt) {
    throw new Error(
      `tenant ${tenantSlug} has not completed onboarding yet — wizard must finish first`,
    );
  }

  // ---- Encounter + claim + 2 findings -------------------------------
  const clinicalNote =
    "Established patient, 58F with HTN and dyslipidemia, returns for " +
    "follow-up. BP 138/86, HR 72. Meds reviewed and adjusted. " +
    "Discussed lifestyle modifications. Plan: continue current " +
    "regimen, recheck lipids in 3 months.";

  const patientHash = sha256Hex("patient-e2e-001");

  const claim = await prisma.encounterClaim.create({
    data: {
      id: cuidLike(),
      payer: "OHIP",
      providerNpi: "1234567890",
      providerName: "Dr. E2E Demo",
      cptCodesJson: JSON.stringify({
        lines: [
          { code: "99214", modifier: null, units: 1, description: "Office visit, established, moderate MDM" },
        ],
        totalCents: 13800,
        payer: "OHIP",
        providerNpi: "1234567890",
        providerName: "Dr. E2E Demo",
        dateOfService: "2026-06-15",
      }),
      billedCents: 13800,
    },
  });

  const encounter = await prisma.encounter.create({
    data: {
      id: cuidLike(),
      tenantId: tenant.id,
      patientHash,
      dateOfService: new Date("2026-06-15"),
      specialty: "Family Medicine",
      clinicalNote: encryptPortalString(clinicalNote),
      claimId: claim.id,
      status: "awaiting_review",
    },
  });

  const finding1 = await prisma.finding.create({
    data: {
      id: cuidLike(),
      encounterId: encounter.id,
      category: "em_level",
      billingRuleReference: "AMA CPT 2026 §99214 (moderate MDM)",
      currentCode: "99214",
      suggestedCode: "99213",
      evidenceQuote: encryptPortalString(
        "BP 138/86, HR 72. Meds reviewed and adjusted.",
      ),
      estFinancialImpactCents: -3500,
      status: "pending",
    },
  });

  const finding2 = await prisma.finding.create({
    data: {
      id: cuidLike(),
      encounterId: encounter.id,
      category: "documentation",
      billingRuleReference: "AMA Documentation Guidelines §3.2",
      currentCode: null,
      suggestedCode: null,
      evidenceQuote: encryptPortalString("Discussed lifestyle modifications."),
      estFinancialImpactCents: 0,
      status: "pending",
    },
  });

  // ---- Synthetic invoice (in lieu of a real Stripe webhook event) ----
  if (tenant.stripeCustomerId) {
    await prisma.invoice.upsert({
      where: { stripeInvoiceId: `in_e2e_${tenantSlug.slice(-8).padStart(8, "0")}` },
      update: {},
      create: {
        id: cuidLike(),
        stripeInvoiceId: `in_e2e_${tenantSlug.slice(-8).padStart(8, "0")}`,
        stripeCustomerId: tenant.stripeCustomerId,
        tenantId: tenant.id,
        stripeSubscriptionId: tenant.stripeSubscriptionId ?? null,
        status: "paid",
        amountCents: 149900, // $1,499.00 CAD
        currency: "cad",
        payloadJson: JSON.stringify({
          id: `in_e2e_${tenantSlug.slice(-8).padStart(8, "0")}`,
          status: "paid",
          amount_paid: 149900,
          currency: "cad",
          customer: tenant.stripeCustomerId,
          description: "E2E test-mode invoice (Mid clinic tier, June 2026)",
        }),
        createdFromEventId: `evt_e2e_${Date.now()}`,
      },
    });
  }

  // Bump audit quota so the dashboard has real numbers.
  await prisma.tenant.update({
    where: { id: tenant.id },
    data: { auditQuotaUsed: 1 },
  });

  console.log(JSON.stringify({
    encounterId: encounter.id,
    claimId: claim.id,
    findingIds: [finding1.id, finding2.id],
    finding1Category: finding1.category,
    finding2Category: finding2.category,
  }, null, 2));
}

main()
  .catch((e) => {
    console.error("[e2e-post-seed] failed:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
