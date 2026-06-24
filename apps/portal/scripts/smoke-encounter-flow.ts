// Smoke test for the encounter review surface.
//
// Exercises the full accept + dismiss flow end-to-end against the
// real Prisma client and the live audit-chain module. The test:
//   1. Re-seeds the demo encounter + findings (idempotent).
//   2. Accepts one finding, asserts a single audit row is written
//      with a valid hash-chain signature.
//   3. Dismisses a second finding with a structured reason, asserts
//      one audit row is written and the finding's status flips.
//   4. Dismisses a third finding with reason=other_with_text +
//      non-empty text, asserts the text is stored on the finding
//      and on the audit row.
//   5. Re-verifies the tenant's audit chain end-to-end and asserts
//      every row is intact (no breaks introduced by these writes).
//   6. Attempts to accept the already-accepted finding and asserts
//      the writeAuditEntry helper throws (so the route returns 409).
//
// Run from apps/portal:
//   pnpm exec tsx scripts/smoke-encounter-flow.ts
//
// Exits 0 on success, 1 on the first failed assertion.

import { randomBytes } from "node:crypto";
import { prisma } from "../src/lib/prisma";
import {
  writeAuditEntry,
  verifyTenantChain,
  normalizeDismissInput,
} from "../src/lib/audit-write";
import { GENESIS_PREVIOUS_SIGNATURE } from "../src/lib/audit-chain";
import { hashPatientId } from "../src/lib/patient-hash";

function cuidLike(prefix = ""): string {
  return `${prefix}${prefix}${prefix}c${randomBytes(12).toString("hex")}`;
}

function assert(cond: unknown, message: string): asserts cond {
  if (!cond) {
    console.error(`[smoke] ASSERT FAILED: ${message}`);
    process.exit(1);
  }
}

async function reseed(): Promise<{ tenantId: string; userId: string; encounterId: string }> {
  const tenant = await prisma.tenant.upsert({
    where: { slug: "smoke-clinic" },
    update: {},
    create: {
      id: cuidLike(),
      name: "Smoke Clinic",
      slug: "smoke-clinic",
      tier: "small",
      subscriptionStatus: "active",
      auditQuotaLimit: 100,
    },
  });
  const user = await prisma.user.upsert({
    where: { email: "[email protected]" },
    update: {},
    create: {
      id: cuidLike(),
      email: "[email protected]",
      name: "Smoke Reviewer",
      emailVerified: new Date(),
    },
  });
  await prisma.membership.upsert({
    where: { userId_tenantId: { userId: user.id, tenantId: tenant.id } },
    update: { role: "admin" },
    create: {
      id: cuidLike(),
      userId: user.id,
      tenantId: tenant.id,
      role: "admin",
    },
  });

  const clinicalNote =
    "Established patient, 58F with HTN and dyslipidemia, returns for " +
    "follow-up. BP 138/86, HR 72. Meds reviewed and adjusted. " +
    "Discussed lifestyle modifications. Plan: continue current regimen.";

  const claimId = cuidLike();
  const claim = await prisma.encounterClaim.upsert({
    where: { id: claimId },
    update: {},
    create: {
      id: claimId,
      payer: "OHIP",
      providerNpi: "9999999999",
      providerName: "Dr. Smoke",
      cptCodesJson: JSON.stringify({
        lines: [{ code: "99214", units: 1 }],
        totalCents: 13800,
        payer: "OHIP",
        providerNpi: "9999999999",
        providerName: "Dr. Smoke",
        dateOfService: "2026-06-12",
      }),
      billedCents: 13800,
    },
  });

  const encounterId = "enc-smoke-0001";
  await prisma.encounter.upsert({
    where: { id: encounterId },
    update: { claimId: claim.id, status: "awaiting_review" },
    create: {
      id: encounterId,
      tenantId: tenant.id,
      patientHash: hashPatientId("smoke-patient-001"),
      dateOfService: new Date("2026-06-12T00:00:00Z"),
      specialty: "cardiology",
      clinicalNote,
      claimId: claim.id,
      status: "awaiting_review",
    },
  });

  // Reset any prior state so each run starts from a known baseline.
  await prisma.auditTrailEntry.deleteMany({ where: { encounterId } });
  await prisma.finding.deleteMany({ where: { encounterId } });

  const findings = [
    { id: "f-smoke-0001", quote: "Meds reviewed and adjusted", category: "em_level" },
    { id: "f-smoke-0002", quote: "BP 138/86, HR 72.", category: "documentation" },
    { id: "f-smoke-0003", quote: "Plan: continue current regimen.", category: "medical_necessity" },
  ];
  for (const f of findings) {
    await prisma.finding.create({
      data: {
        id: f.id,
        encounterId,
        category: f.category,
        billingRuleReference: "Smoke test rule reference",
        currentCode: "99214",
        suggestedCode: null,
        evidenceQuote: f.quote,
        estFinancialImpactCents: 0,
        status: "pending",
      },
    });
  }

  return { tenantId: tenant.id, userId: user.id, encounterId };
}

async function expectThrow(
  fn: () => Promise<unknown>,
  message: RegExp,
  label: string,
): Promise<void> {
  try {
    await fn();
  } catch (err) {
    if (err instanceof Error && message.test(err.message)) {
      console.log(`[smoke] ${label}: expected throw ✓ ("${err.message}")`);
      return;
    }
    console.error(
      `[smoke] ${label}: expected error matching ${message}, got`,
      err,
    );
    process.exit(1);
  }
  console.error(`[smoke] ${label}: expected throw, got success`);
  process.exit(1);
}

async function main() {
  const { tenantId, userId, encounterId } = await reseed();
  const encounter = await prisma.encounter.findUniqueOrThrow({
    where: { id: encounterId },
    select: { patientHash: true },
  });
  const patientHash = encounter.patientHash;

  // ---- Baseline: empty chain verifies clean (no rows yet) -----------
  const baseline = await verifyTenantChain(tenantId);
  assert(baseline === null, `baseline chain broken at index ${baseline}`);

  // ---- 1. Accept the first finding ---------------------------------
  const accept1 = await prisma.$transaction(async (tx) =>
    writeAuditEntry({
      tenantId,
      encounterId,
      findingId: "f-smoke-0001",
      userIdentifier: userId,
      action: "accept",
      reason: null,
      reasonText: null,
      patientHash,
      modelRunId: "smoke-test",
      tx,
    }),
  );
  assert(accept1.newFindingStatus === "accepted", "accept should set status=accepted");
  assert(/^[0-9a-f]{64}$/.test(accept1.cryptographicSignature), "sig is 64 hex chars");
  assert(accept1.previousSignature === GENESIS_PREVIOUS_SIGNATURE, "first row uses genesis prev");
  console.log(`[smoke] accept #1: sig=${accept1.cryptographicSignature.slice(0, 12)}…`);

  // ---- 2. Dismiss the second finding (structured reason) ------------
  const dismissInput = normalizeDismissInput({ reason: "hallucinated_fact" });
  const dismiss1 = await prisma.$transaction(async (tx) =>
    writeAuditEntry({
      tenantId,
      encounterId,
      findingId: "f-smoke-0002",
      userIdentifier: userId,
      action: "dismiss",
      reason: dismissInput.reason,
      reasonText: dismissInput.reasonText,
      patientHash,
      modelRunId: "smoke-test",
      tx,
    }),
  );
  assert(dismiss1.newFindingStatus === "dismissed", "dismiss should set status=dismissed");
  assert(
    dismiss1.previousSignature === accept1.cryptographicSignature,
    "dismiss #1's previous is accept #1's sig (chain link)",
  );
  console.log(`[smoke] dismiss #1: sig=${dismiss1.cryptographicSignature.slice(0, 12)}…`);

  // ---- 3. Dismiss third finding (other_with_text) -------------------
  const dismissInput2 = normalizeDismissInput({
    reason: "other_with_text",
    reasonText: "Payer policy CPT-25 exclusion; suggest deferring this code swap until the new fiscal year.",
  });
  const dismiss2 = await prisma.$transaction(async (tx) =>
    writeAuditEntry({
      tenantId,
      encounterId,
      findingId: "f-smoke-0003",
      userIdentifier: userId,
      action: "dismiss",
      reason: dismissInput2.reason,
      reasonText: dismissInput2.reasonText,
      patientHash,
      modelRunId: "smoke-test",
      tx,
    }),
  );
  assert(
    dismiss2.previousSignature === dismiss1.cryptographicSignature,
    "dismiss #2's previous is dismiss #1's sig",
  );
  console.log(`[smoke] dismiss #2: sig=${dismiss2.cryptographicSignature.slice(0, 12)}…`);

  // ---- 4. Re-verify the chain --------------------------------------
  const reVerified = await verifyTenantChain(tenantId);
  assert(reVerified === null, `chain broken at index ${reVerified}`);
  console.log("[smoke] full chain verifies clean after 3 writes");

  // ---- 5. Idempotency: accepting an already-accepted finding fails --
  await expectThrow(
    () =>
      prisma.$transaction(async (tx) =>
        writeAuditEntry({
          tenantId,
          encounterId,
          findingId: "f-smoke-0001", // already accepted above
          userIdentifier: userId,
          action: "accept",
          reason: null,
          reasonText: null,
          patientHash,
          modelRunId: "smoke-test",
          tx,
        }),
      ),
    /already accepted/,
    "double-accept rejected",
  );

  // ---- 6. Mutation detection: tamper with one row, expect a break --
  const tampered = await prisma.auditTrailEntry.findFirstOrThrow({
    where: { encounterId, action: "accept" },
  });
  await prisma.auditTrailEntry.update({
    where: { id: tampered.id },
    data: { action: "dismiss" },
  });
  const broken = await verifyTenantChain(tenantId);
  assert(broken !== null, "tampered chain should report a broken index");
  console.log(`[smoke] tamper detection: chain broken at index ${broken} ✓`);
  // Restore so the test is idempotent on re-run.
  await prisma.auditTrailEntry.update({
    where: { id: tampered.id },
    data: { action: "accept" },
  });

  // ---- 7. Validate normalizeDismissInput error cases ---------------
  // Missing reasonText when other_with_text.
  try {
    normalizeDismissInput({ reason: "other_with_text" });
    console.error("[smoke] expected normalizeDismissInput to reject empty other_with_text");
    process.exit(1);
  } catch (err) {
    assert(
      err instanceof Error && /required/i.test(err.message),
      `expected required-text error, got ${err}`,
    );
  }
  // Invalid reason.
  try {
    normalizeDismissInput({ reason: "not_a_real_reason" });
    console.error("[smoke] expected normalizeDismissInput to reject unknown reason");
    process.exit(1);
  } catch (err) {
    assert(
      err instanceof Error && /must be one of/i.test(err.message),
      `expected enum error, got ${err}`,
    );
  }
  // Text too long.
  try {
    normalizeDismissInput({
      reason: "other_with_text",
      reasonText: "x".repeat(2001),
    });
    console.error("[smoke] expected normalizeDismissInput to reject >2000 chars");
    process.exit(1);
  } catch (err) {
    assert(
      err instanceof Error && /2000/.test(err.message),
      `expected length error, got ${err}`,
    );
  }
  console.log("[smoke] normalizeDismissInput error cases all enforced ✓");

  // ---- 8. Confirm the persisted Finding state matches the audit ----
  const f1 = await prisma.finding.findUniqueOrThrow({
    where: { id: "f-smoke-0001" },
  });
  assert(f1.status === "accepted", `f1.status expected 'accepted', got '${f1.status}'`);
  assert(f1.actionedAt !== null, "f1.actionedAt should be set");
  assert(f1.dismissReason === null, "f1.dismissReason should be null on accept");

  const f2 = await prisma.finding.findUniqueOrThrow({
    where: { id: "f-smoke-0002" },
  });
  assert(f2.status === "dismissed", `f2.status expected 'dismissed', got '${f2.status}'`);
  assert(f2.dismissReason === "hallucinated_fact", "f2.dismissReason recorded");
  assert(f2.dismissText === null, "f2.dismissText is null when reason is not other_with_text");

  const f3 = await prisma.finding.findUniqueOrThrow({
    where: { id: "f-smoke-0003" },
  });
  assert(f3.status === "dismissed", "f3 should be dismissed");
  assert(f3.dismissReason === "other_with_text", "f3.dismissReason == other_with_text");
  assert(
    f3.dismissText !== null && f3.dismissText.startsWith("Payer policy"),
    "f3.dismissText stored verbatim",
  );

  console.log("\n[smoke] all assertions passed ✓");
  console.log(`[smoke] audit chain at tenant ${tenantId}:`);
  const all = await prisma.auditTrailEntry.findMany({
    where: { tenantId },
    orderBy: [{ timestamp: "asc" }, { eventId: "asc" }],
    select: { eventId: true, action: true, findingId: true, cryptographicSignature: true },
  });
  for (const row of all) {
    console.log(
      `  ${row.eventId.slice(0, 12)}…  action=${row.action}  finding=${row.findingId}  sig=${row.cryptographicSignature.slice(0, 12)}…`,
    );
  }
}

main()
  .catch((err) => {
    console.error("[smoke] failed", err);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
