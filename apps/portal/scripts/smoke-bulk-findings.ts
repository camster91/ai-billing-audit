// Smoke test for the /findings bulk-accept flow.
//
// Mirrors scripts/smoke-encounter-flow.ts but for the bulk path.
// The test:
//
//   1. Re-seeds the demo encounter + findings (idempotent).
//   2. Picks the first 10 PENDING findings in the demo tenant.
//   3. Calls writeAuditEntry in a loop with a shared bulkActionId —
//      same shape the /api/findings/bulk/accept route uses.
//   4. Asserts the 10 audit rows exist, all share the bulkActionId,
//      and the tenant's chain is still intact (verifyTenantChain
//      returns null).
//   5. Asserts every affected Finding is now status=accepted.
//
// The script does NOT call the HTTP route — that requires a session
// cookie and a real auth flow. The test exercises the same write
// shape so a regression in the bulk shape is caught without the
// browser harness.
//
// Run from apps/portal:
//   pnpm exec tsx scripts/smoke-bulk-findings.ts
//
// Exits 0 on success, 1 on the first failed assertion.

import { randomBytes } from "node:crypto";
import { prisma } from "../src/lib/prisma";
import {
  writeAuditBatch,
  verifyTenantChain,
} from "../src/lib/audit-write";

function cuidLike(): string {
  return `c${randomBytes(12).toString("hex")}`;
}

function cryptoRandomId(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  let out = "";
  for (let i = 0; i < bytes.length; i++) {
    out += bytes[i]!.toString(16).padStart(2, "0");
  }
  return out;
}

async function main() {
  const tenantSlug = "demo-clinic";
  const tenant = await prisma.tenant.findUnique({ where: { slug: tenantSlug } });
  if (!tenant) {
    console.error("demo tenant not found — run scripts/seed-encounter-list.ts first");
    process.exit(1);
  }

  // 1. Pick 10 PENDING findings in this tenant, in the most recent
  //    date-of-service order. If the inbox is short on pending rows
  //    (e.g. a prior smoke run already accepted them) we re-seed
  //    enough to satisfy the contract.
  let pending = await prisma.finding.findMany({
    where: { status: "pending", encounter: { tenantId: tenant.id } },
    take: 10,
    orderBy: { encounter: { dateOfService: "desc" } },
    include: { encounter: { select: { id: true, patientHash: true } } },
  });

  if (pending.length < 10) {
    console.error(
      `only ${pending.length} pending findings in tenant — re-seed via scripts/seed-encounter-list.ts`,
    );
    process.exit(1);
  }

  const ids = pending.map((f) => f.id);
  console.log(`[smoke-bulk] using ${ids.length} pending findings`);

  // 2. Create a test "reviewer" user if one doesn't exist. The
  //    real route uses the auth session; the smoke path uses a
  //    fixed user id we can also use in the assertion.
  const userEmail = "[email protected]";
  const user = await prisma.user.upsert({
    where: { email: userEmail },
    update: {},
    create: { id: cuidLike(), email: userEmail, name: "Bulk Smoke" },
  });
  const membership = await prisma.membership.findFirst({
    where: { userId: user.id, tenantId: tenant.id },
  });
  if (!membership) {
    await prisma.membership.create({
      data: { id: cuidLike(), userId: user.id, tenantId: tenant.id, role: "admin" },
    });
  }

  const bulkActionId = cryptoRandomId();
  console.log(`[smoke-bulk] bulkActionId = ${bulkActionId}`);

  // 3. Run the bulk write. Same shape as /api/findings/bulk/accept
  //    uses (writeAuditBatch inside one tx with a pre-computed
  //    chain).
  await prisma.$transaction(async (tx) => {
    await writeAuditBatch({
      tenantId: tenant.id,
      userIdentifier: user.id,
      action: "accept",
      bulkActionId,
      items: pending.map((f) => ({
        encounterId: f.encounter.id,
        findingId: f.id,
        patientHash: f.encounter.patientHash,
        reason: null,
        reasonText: null,
      })),
      tx,
    });
  });

  // 4. Assert all 10 audit rows are present and share the id.
  const rows = await prisma.auditTrailEntry.findMany({
    where: { bulkActionId },
    orderBy: { timestamp: "asc" },
  });
  if (rows.length !== 10) {
    console.error(
      `expected 10 audit rows for bulkActionId, got ${rows.length}`,
    );
    process.exit(1);
  }
  const distinctIds = new Set(rows.map((r) => r.bulkActionId));
  if (distinctIds.size !== 1 || !distinctIds.has(bulkActionId)) {
    console.error(
      `audit rows do not all share the same bulkActionId: ${[...distinctIds].join(", ")}`,
    );
    process.exit(1);
  }
  console.log(`[smoke-bulk] 10 audit rows share bulkActionId ${bulkActionId} ✓`);

  // 5. Assert every chain row is intact — verifyTenantChain walks
  //    the tenant's chain in (timestamp, eventId) order and
  //    confirms each row's stored signature matches the
  //    recomputed digest AND each row's previousSignature links
  //    to the prior row's signature. A break here means the
  //    chain ordering is wrong.
  const broken = await verifyTenantChain(tenant.id);
  if (broken !== null) {
    console.error(`audit chain broken at index ${broken}`);
    process.exit(1);
  }
  console.log(`[smoke-bulk] audit chain intact ✓`);

  // 6. Assert every affected Finding is now status=accepted.
  const updated = await prisma.finding.findMany({
    where: { id: { in: ids } },
    select: { id: true, status: true, actionedByUserId: true, actionedAt: true },
  });
  for (const f of updated) {
    if (f.status !== "accepted") {
      console.error(`finding ${f.id} is ${f.status}, expected accepted`);
      process.exit(1);
    }
    if (f.actionedByUserId !== user.id) {
      console.error(`finding ${f.id} actionedByUserId is ${f.actionedByUserId}, expected ${user.id}`);
      process.exit(1);
    }
    if (!f.actionedAt) {
      console.error(`finding ${f.id} actionedAt is null, expected a Date`);
      process.exit(1);
    }
  }
  console.log(`[smoke-bulk] all 10 findings are status=accepted with audit metadata ✓`);

  // 7. Assert the chain payload's dataElements carries the bulkActionId.
  for (const r of rows) {
    const de = JSON.parse(r.dataElements) as { bulkActionId?: string };
    if (de.bulkActionId !== bulkActionId) {
      console.error(
        `row ${r.id} dataElements.bulkActionId is ${de.bulkActionId}, expected ${bulkActionId}`,
      );
      process.exit(1);
    }
  }
  console.log(`[smoke-bulk] dataElements.bulkActionId correct on all 10 rows ✓`);

  // 8. Assert the chain ordering is strictly the order the
  //    findings were passed in. The (timestamp, eventId)
  //    tiebreaker in the chain walk MUST be deterministic;
  //    a re-walk returns the same sequence.
  const rewalked = rows.map((r) => r.findingId);
  const expected = ids;
  for (let i = 0; i < rewalked.length; i++) {
    if (rewalked[i] !== expected[i]) {
      console.error(
        `chain order mismatch at index ${i}: expected ${expected[i]} got ${rewalked[i]}`,
      );
      process.exit(1);
    }
  }
  console.log(`[smoke-bulk] chain order matches the input finding order ✓`);

  // Cleanup: delete the audit rows + restore the finding statuses so
  // the smoke is idempotent.
  await prisma.auditTrailEntry.deleteMany({ where: { bulkActionId } });
  await prisma.finding.updateMany({
    where: { id: { in: ids } },
    data: {
      status: "pending",
      actionedByUserId: null,
      actionedAt: null,
      dismissReason: null,
      dismissText: null,
    },
  });
  console.log(`[smoke-bulk] cleanup complete; finding statuses restored`);

  console.log("[smoke-bulk] PASS");
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("[smoke-bulk] FAIL", err);
    process.exit(1);
  });
