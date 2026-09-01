import assert from "node:assert/strict";
import test from "node:test";
import { prisma } from "../src/lib/prisma";
import { capturePublicLead, normalizeLeadIdentity } from "../src/lib/lead-capture";

const EMAIL = "lead-capture-test@example.test";

async function cleanup() {
  await prisma.lead.deleteMany({ where: { email: EMAIL } });
}

test("normalized identity is trim- and case-insensitive", () => {
  assert.equal(normalizeLeadIdentity("  Lead-Capture-Test@Example.Test "), EMAIL);
});

test("repeat submissions reuse one canonical lead without rewriting pipeline decisions", async () => {
  await cleanup();
  const first = await capturePublicLead({
    name: "First Contact",
    clinicName: "Canonical Clinic",
    email: "Lead-Capture-Test@Example.Test",
    claimVolume: 1200,
    billingSetup: "in_house",
  }, new Date("2026-09-01T17:00:00.000Z"));
  await prisma.lead.update({
    where: { id: first.id },
    data: {
      status: "contacted",
      qualificationStatus: "qualified",
      qualificationReason: "Approved commercial rationale",
    },
  });

  const repeat = await capturePublicLead({
    name: "Changed Contact",
    clinicName: "Changed Clinic",
    email: `  ${EMAIL.toUpperCase()} `,
    claimVolume: 9000,
    billingSetup: "outsourced",
  }, new Date("2026-09-01T18:00:00.000Z"));

  assert.equal(repeat.id, first.id);
  assert.equal(repeat.deduplicated, true);
  const persisted = await prisma.lead.findUniqueOrThrow({ where: { id: first.id } });
  assert.equal(persisted.submissionCount, 2);
  assert.equal(persisted.lastSubmittedAt?.toISOString(), "2026-09-01T18:00:00.000Z");
  assert.equal(persisted.name, "First Contact");
  assert.equal(persisted.status, "contacted");
  assert.equal(persisted.qualificationStatus, "qualified");
  assert.equal(await prisma.lead.count({ where: { email: EMAIL } }), 1);
  await cleanup();
});
