// Seed script: one tenant, one user (membership), one encounter with
// three findings (matching the SAMPLE fixture in the auditor
// FastAPI app at templates/dashboard/split_review.html). Idempotent —
// safe to run repeatedly in dev. Re-creates the demo row on each
// invocation so the seed stays current with schema changes.
//
// Run from apps/portal:
//   pnpm exec tsx scripts/seed-demo-encounter.ts
// or via the project root:
//   cd apps/portal && pnpm exec tsx scripts/seed-demo-encounter.ts
//
// Out of scope for production: a "real" onboarding flow creates the
// tenant + user via the magic-link signin. The seed below is the dev
// fast path that gives the /encounters/[id] page something to render
// without going through Resend.

import { randomBytes } from "node:crypto";
import { prisma } from "../src/lib/prisma";
import { wrapEvidenceQuotes } from "../src/lib/encounter-format";
import { hashPatientId } from "../src/lib/patient-hash";
import { encryptPortalString } from "../src/lib/data-encryption";

function cuidLike(): string {
  return `c${randomBytes(12).toString("hex")}`;
}

async function main() {
  const tenantSlug = "demo-clinic";
  const userEmail = "[email protected]";

  // ---- Tenant ----------------------------------------------------------
  const tenant = await prisma.tenant.upsert({
    where: { slug: tenantSlug },
    update: {},
    create: {
      id: cuidLike(),
      name: "Demo Family Clinic",
      slug: tenantSlug,
      tier: "small",
      subscriptionStatus: "active",
      auditQuotaLimit: 100,
    },
  });

  // ---- User + membership ----------------------------------------------
  const user = await prisma.user.upsert({
    where: { email: userEmail },
    update: {},
    create: {
      id: cuidLike(),
      email: userEmail,
      name: "Demo Reviewer",
      emailVerified: new Date(),
    },
  });
  await prisma.membership.upsert({
    where: { userId_tenantId: { userId: user.id, tenantId: tenant.id } },
    update: { role: "admin" },
    create: {
      user: { connect: { id: user.id } },
      tenant: { connect: { id: tenant.id } },
      role: "admin",
      status: "active",
      email: userEmail,
    },
  });

  // ---- Claim + encounter + findings ----------------------------------
  // The clinical narrative is the SAMPLE text from the auditor fixture
  // (templates/dashboard/split_review.html). The three findings
  // mirror the auditor's own sample so the same evidence quotes
  // resolve to the same `<mark>` spans on both UIs.
  const clinicalNote =
    "Established patient, 58F with HTN and dyslipidemia, returns for " +
    "follow-up. BP 138/86, HR 72. Meds reviewed and adjusted. " +
    "Discussed lifestyle modifications. Plan: continue current " +
    "regimen, recheck lipids in 3 months.";

  const patientId = "patient-demo-001";
  // Peppered SHA-256 — see src/lib/patient-hash.ts. The pepper comes
  // from the PATIENT_HASH_PEPPER env var; the dev fallback is used in
  // non-production. Do not log the env var or the digest in the seed
  // output (no PHI exposure in the demo script's stdout).
  const patientHash = hashPatientId(patientId);

  const claimId = cuidLike();
  const claim = await prisma.encounterClaim.upsert({
    where: { id: claimId },
    update: {},
    create: {
      id: claimId,
      payer: "OHIP",
      providerNpi: "1234567890",
      providerName: "Dr. A. Demo",
      cptCodesJson: JSON.stringify({
        lines: [
          { code: "99214", modifier: null, units: 1, description: "Office visit, established, moderate MDM" },
        ],
        totalCents: 13800,
        payer: "OHIP",
        providerNpi: "1234567890",
        providerName: "Dr. A. Demo",
        dateOfService: "2026-06-12",
      }),
      billedCents: 13800,
    },
  });

  const encounterId = "enc-demo-0001";
  await prisma.encounter.upsert({
    where: { id: encounterId },
    update: {
      claimId: claim.id,
    },
    create: {
      id: encounterId,
      tenantId: tenant.id,
      patientHash,
      dateOfService: new Date("2026-06-12T00:00:00Z"),
      specialty: "cardiology",
      clinicalNote: encryptPortalString(clinicalNote),
      claimId: claim.id,
      status: "awaiting_review",
    },
  });

  // Findings — three, matching the auditor fixture verbatim.
  const findings = [
    {
      id: "f-demo-0001",
      category: "em_level",
      billingRuleReference: "AMA CPT 2026 §99214 (moderate MDM)",
      currentCode: "99213",
      suggestedCode: "99214",
      evidenceQuote: "Meds reviewed and adjusted",
      estFinancialImpactCents: 4840,
    },
    {
      id: "f-demo-0002",
      category: "documentation",
      billingRuleReference: "CMS 2026 E/M Documentation — time requirement",
      currentCode: "99214",
      suggestedCode: "99214",
      evidenceQuote: "Plan: continue current regimen, recheck lipids in 3 months.",
      estFinancialImpactCents: 0,
    },
    {
      id: "f-demo-0003",
      category: "medical_necessity",
      billingRuleReference: "OHIP Schedule of Benefits — chronic disease follow-up",
      currentCode: "99214",
      suggestedCode: null,
      evidenceQuote: "Established patient, 58F with HTN and dyslipidemia, returns for follow-up.",
      estFinancialImpactCents: 0,
    },
  ];
  for (const f of findings) {
    await prisma.finding.upsert({
      where: { id: f.id },
      update: {
        category: f.category,
        billingRuleReference: f.billingRuleReference,
        currentCode: f.currentCode,
        suggestedCode: f.suggestedCode,
        evidenceQuote: encryptPortalString(f.evidenceQuote),
        estFinancialImpactCents: f.estFinancialImpactCents,
      },
      create: {
        id: f.id,
        encounterId,
        category: f.category,
        billingRuleReference: f.billingRuleReference,
        currentCode: f.currentCode,
        suggestedCode: f.suggestedCode,
        evidenceQuote: encryptPortalString(f.evidenceQuote),
        estFinancialImpactCents: f.estFinancialImpactCents,
        status: "pending",
      },
    });
  }

  // Sanity-check the wrap-evidence-quotes helper end-to-end against
  // the seeded narrative so the dev knows the page will render with
  // highlight marks on the seeded findings.
  const { matches } = wrapEvidenceQuotes(
    clinicalNote,
    findings.map((f) => ({ id: f.id, quote: f.evidenceQuote })),
  );
  console.log(
    `[seed] wrapped ${matches.length} evidence span(s) for encounter ${encounterId}`,
  );

  console.log(
    `[seed] done. Visit /encounters/${encounterId} after signing in as ${userEmail}.`,
  );
}

main()
  .catch((err) => {
    console.error("[seed] failed", err);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
