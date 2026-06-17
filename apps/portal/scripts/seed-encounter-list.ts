// Seed script: bulk-import 50+ encounters for the demo tenant so
// the /encounters list page (t_2407d2c1) has real pagination,
// sort, and filter coverage to work against.
//
// Why a separate script: the existing seed-demo-encounter.ts
// inserts ONE encounter with the auditor fixture. The list page
// acceptance criteria require 50+ rows so server-paginated
// navigation is exercised. This script adds 50+ rows to the same
// demo tenant and is idempotent — running it twice leaves the DB
// in the same state.
//
// Idempotency: each generated encounter has a deterministic id of
// the form `enc-list-NNNN`. The script upserts on `id`; on second
// run the rows are touched in place (date/status/claim updated),
// and the related findings are re-upserted by their own
// deterministic ids.
//
// Run from apps/portal:
//   pnpm exec tsx scripts/seed-encounter-list.ts
//
// The script is dev-only. Production seeds come from the engine
// pipeline (see apps/engine/ — out of scope).

import { randomBytes } from "node:crypto";
import { prisma } from "../src/lib/prisma";
import { hashPatientId } from "../src/lib/patient-hash";

function cuidLike(): string {
  return `c${randomBytes(12).toString("hex")}`;
}

const PAYERS = ["OHIP", "Aetna", "BCBS", "Cigna", "UnitedHealthcare", "Medicare"] as const;
const PROVIDERS = [
  { name: "Dr. A. Demo", npi: "1234567890" },
  { name: "Dr. B. Chen", npi: "1234567891" },
  { name: "Dr. C. Patel", npi: "1234567892" },
  { name: "Dr. D. Singh", npi: "1234567893" },
  { name: "Dr. E. Okafor", npi: "1234567894" },
] as const;
const SPECIALTIES = [
  "cardiology",
  "family_medicine",
  "internal_medicine",
  "orthopedics",
  "pediatrics",
  "endocrinology",
] as const;
const STATUSES = [
  "pending",
  "auditing",
  "awaiting_review",
  "completed",
] as const;
const CATEGORIES = [
  "em_level",
  "documentation",
  "medical_necessity",
  "modifier",
  "code_mismatch",
  "payer_policy",
  "other",
] as const;
const RULES = {
  em_level: "AMA CPT 2026 §99214 (moderate MDM)",
  documentation: "CMS 2026 E/M Documentation — time requirement",
  medical_necessity: "OHIP Schedule of Benefits — chronic disease follow-up",
  modifier: "AMA CPT 2026 Modifier 25 reference",
  code_mismatch: "ICD-10-CM 2026 — code specificity",
  payer_policy: "Payer LCD — cardiology follow-up",
  other: "Internal audit rule — general",
} as const;

function pick<T>(arr: readonly T[], seed: number): T {
  return arr[seed % arr.length] as T;
}

const ENCOUNTER_COUNT = 60;

async function main() {
  const tenantSlug = "demo-clinic";

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

  // Make sure the demo reviewer (seeded by seed-demo-encounter.ts)
  // is a member of the demo tenant so the /encounters list page has
  // a user to sign in as. Idempotent — safe to re-run.
  const demoUser = await prisma.user.findFirst({
    where: { email: "demo.reviewer@ashbi.test" },
  });
  if (demoUser) {
    await prisma.membership.upsert({
      where: { userId_tenantId: { userId: demoUser.id, tenantId: tenant.id } },
      update: { role: "admin" },
      create: {
        id: cuidLike(),
        userId: demoUser.id,
        tenantId: tenant.id,
        role: "admin",
      },
    });
  }

  // Stable seed for the run. We pick a date 2026-04-01..2026-06-30
  // so the date-range filter has meaningful bounds.
  const base = new Date("2026-04-01T00:00:00.000Z").getTime();
  const end = new Date("2026-06-30T00:00:00.000Z").getTime();
  const span = end - base;

  for (let i = 0; i < ENCOUNTER_COUNT; i += 1) {
    const encId = `enc-list-${String(i + 1).padStart(4, "0")}`;
    const provider = pick(PROVIDERS, i);
    const payer = pick(PAYERS, i + 1);
    const status = pick(STATUSES, i + 2);
    const specialty = pick(SPECIALTIES, i + 3);
    // Deterministic, monotonic date — index 0 = oldest, index N-1 = newest
    const date = new Date(base + (span * i) / (ENCOUNTER_COUNT - 1));
    const patientHash = hashPatientId(`patient-list-${i + 1}`);

    // EncounterClaim — 1:1 with Encounter via claimId. Use a
    // deterministic id pattern so the upsert is stable.
    const claimId = `clm-list-${String(i + 1).padStart(4, "0")}`;
    const cpt = i % 3 === 0 ? "99214" : i % 3 === 1 ? "99213" : "99215";
    const billedCents = cpt === "99213" ? 9200 : cpt === "99214" ? 13800 : 18600;
    await prisma.encounterClaim.upsert({
      where: { id: claimId },
      update: {
        payer,
        providerNpi: provider.npi,
        providerName: provider.name,
        billedCents,
        cptCodesJson: JSON.stringify({
          lines: [{ code: cpt, modifier: null, units: 1, description: "Office visit" }],
          totalCents: billedCents,
          payer,
          providerNpi: provider.npi,
          providerName: provider.name,
          dateOfService: date.toISOString().slice(0, 10),
        }),
      },
      create: {
        id: claimId,
        payer,
        providerNpi: provider.npi,
        providerName: provider.name,
        billedCents,
        cptCodesJson: JSON.stringify({
          lines: [{ code: cpt, modifier: null, units: 1, description: "Office visit" }],
          totalCents: billedCents,
          payer,
          providerNpi: provider.npi,
          providerName: provider.name,
          dateOfService: date.toISOString().slice(0, 10),
        }),
      },
    });

    await prisma.encounter.upsert({
      where: { id: encId },
      update: {
        tenantId: tenant.id,
        patientHash,
        dateOfService: date,
        specialty,
        claimId,
        status,
      },
      create: {
        id: encId,
        tenantId: tenant.id,
        patientHash,
        dateOfService: date,
        specialty,
        clinicalNote: `Bulk-seeded encounter #${i + 1} for ${provider.name}.`,
        claimId,
        status,
      },
    });

    // Findings — between 0 and 3 per encounter. The number + the
    // categories are deterministic per index, so the count and the
    // filter results are stable across re-runs.
    const findingCount = i % 4; // 0..3
    // First clear out any prior findings for this encounter so the
    // upsert shape doesn't accumulate if the count changed.
    await prisma.finding.deleteMany({ where: { encounterId: encId } });
    for (let f = 0; f < findingCount; f += 1) {
      const cat = pick(CATEGORIES, i + f);
      const findingId = `fnd-list-${String(i + 1).padStart(4, "0")}-${f + 1}`;
      const estImpactCents = cat === "em_level"
        ? 4600
        : cat === "documentation"
          ? 0
          : cat === "modifier"
            ? 1200
            : cat === "code_mismatch"
              ? 3200
              : cat === "medical_necessity"
                ? 0
                : cat === "payer_policy"
                  ? 1800
                  : 0;
      await prisma.finding.create({
        data: {
          id: findingId,
          encounterId: encId,
          category: cat,
          billingRuleReference: RULES[cat],
          currentCode: cpt,
          suggestedCode: cat === "em_level" ? "99214" : cpt,
          evidenceQuote: "Bulk-seeded narrative.",
          estFinancialImpactCents: estImpactCents,
          status: "pending",
        },
      });
    }
  }

  // Sanity log — the user can confirm the seed took.
  const total = await prisma.encounter.count({ where: { tenantId: tenant.id } });
  console.log(
    `[seed] demo tenant now has ${total} encounter(s) (target: ${ENCOUNTER_COUNT + 1} including the original demo encounter).`,
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
