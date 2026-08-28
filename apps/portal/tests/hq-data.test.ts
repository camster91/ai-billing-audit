import assert from "node:assert/strict";
import test from "node:test";
import { prisma } from "../src/lib/prisma";
import { loadHqLeads, loadHqOverview } from "../src/lib/hq-data";

const PREFIX = "hq-test-";

async function cleanup() {
  await prisma.platformAuditEvent.deleteMany({ where: { requestId: { startsWith: PREFIX } } });
  await prisma.platformUserRole.deleteMany({ where: { grantedBy: PREFIX } });
  await prisma.lead.deleteMany({ where: { email: { startsWith: PREFIX } } });
  await prisma.membership.deleteMany({ where: { email: { startsWith: PREFIX } } });
  await prisma.tenant.deleteMany({ where: { slug: { startsWith: PREFIX } } });
  await prisma.user.deleteMany({ where: { email: { startsWith: PREFIX } } });
}

test("HQ overview returns only commercial lead fields and sourced counts", async () => {
  await cleanup();
  const now = new Date("2026-08-28T20:00:00.000Z");
  const user = await prisma.user.create({
    data: { email: `${PREFIX}owner@example.test` },
  });
  await prisma.platformUserRole.create({
    data: { userId: user.id, role: "owner", grantedBy: PREFIX },
  });
  await prisma.tenant.create({
    data: { name: "HQ Test Clinic", slug: `${PREFIX}clinic`, subscriptionStatus: "active" },
  });
  await prisma.lead.createMany({
    data: [
      {
        name: "New Lead",
        clinicName: "North Clinic",
        email: `${PREFIX}new@example.test`,
        billingSetup: "in_house",
        status: "new",
        source: "contact_form",
        createdAt: now,
      },
      {
        name: "Owned Lead",
        clinicName: "South Clinic",
        email: `${PREFIX}owned@example.test`,
        billingSetup: "hybrid",
        status: "contacted",
        ownerUserId: user.id,
        lastContactedAt: new Date("2026-08-28T19:00:00.000Z"),
        createdAt: now,
      },
    ],
  });

  const overview = await loadHqOverview(now);
  assert.equal(overview.newLeadCount >= 1, true);
  assert.equal(overview.unownedLeadCount >= 1, true);
  assert.equal(overview.activeClientCount >= 1, true);

  const leads = (await loadHqLeads()).filter((lead) => lead.email.startsWith(PREFIX));
  assert.equal(leads.length, 2);
  assert.deepEqual(Object.keys(leads[0] ?? {}).sort(), [
    "billingSetup",
    "claimVolume",
    "clinicName",
    "createdAt",
    "email",
    "id",
    "lastContactedAt",
    "lostReason",
    "name",
    "nextAction",
    "nextActionAt",
    "ownerUserId",
    "source",
    "status",
    "version",
  ]);
  for (const lead of leads) {
    assert.equal("encounter" in lead, false);
    assert.equal("finding" in lead, false);
    assert.equal("patientHash" in lead, false);
    assert.equal("clinicalNote" in lead, false);
  }

  await cleanup();
});

test("platform operator audit request ids reject duplicate events", async () => {
  await cleanup();
  const user = await prisma.user.create({ data: { email: `${PREFIX}audit@example.test` } });
  const requestId = `${PREFIX}request`;
  await prisma.platformAuditEvent.create({
    data: {
      actorUserId: user.id,
      actorRole: "owner",
      action: "read",
      targetType: "hq_dashboard",
      requestId,
    },
  });
  await assert.rejects(
    prisma.platformAuditEvent.create({
      data: {
        actorUserId: user.id,
        actorRole: "owner",
        action: "read",
        targetType: "hq_dashboard",
        requestId,
      },
    }),
  );
  assert.equal(await prisma.platformAuditEvent.count({ where: { requestId } }), 1);
  await cleanup();
});
