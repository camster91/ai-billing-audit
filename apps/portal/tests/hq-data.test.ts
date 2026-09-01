import assert from "node:assert/strict";
import test from "node:test";
import { prisma } from "../src/lib/prisma";
import { loadHqClientDetail, loadHqLeads, loadHqOverview } from "../src/lib/hq-data";

const PREFIX = "hq-test-";

async function cleanup() {
  await prisma.supportActivity.deleteMany({ where: { supportCase: { engagement: { lead: { email: { startsWith: PREFIX } } } } } });
  await prisma.supportCase.deleteMany({ where: { engagement: { lead: { email: { startsWith: PREFIX } } } } });
  await prisma.platformAuditEvent.deleteMany({ where: { requestId: { startsWith: PREFIX } } });
  await prisma.companyTask.deleteMany({ where: { engagement: { lead: { email: { startsWith: PREFIX } } } } });
  await prisma.clientEngagement.deleteMany({ where: { lead: { email: { startsWith: PREFIX } } } });
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
  const pilotLead = await prisma.lead.create({
    data: {
      name: "Pilot Lead",
      clinicName: "Pilot Clinic",
      email: `${PREFIX}pilot@example.test`,
      billingSetup: "in_house",
      status: "pilot_signed",
      createdAt: now,
    },
  });
  const engagement = await prisma.clientEngagement.create({
    data: {
      leadId: pilotLead.id,
      clinicName: pilotLead.clinicName,
      tasks: { create: [{ title: "Open client task", dueAt: new Date("2026-08-27T20:00:00.000Z") }] },
    },
  });

  const overview = await loadHqOverview(now);
  assert.equal(overview.newLeadCount >= 1, true);
  assert.equal(overview.unownedLeadCount >= 1, true);
  assert.equal(overview.activeClientCount >= 1, true);
  assert.equal(overview.openCompanyTaskCount, 1);
  assert.equal(overview.overdueCompanyTaskCount, 1);
  assert.equal(overview.openSupportCaseCount, 0);

  const detail = await loadHqClientDetail(engagement.id);
  assert.ok(detail.client);
  const serializedDetail = JSON.stringify(detail.client);
  for (const forbidden of ["encounter", "finding", "patientHash", "clinicalNote", "claimData"]) {
    assert.equal(serializedDetail.includes(forbidden), false, forbidden);
  }

  const leads = (await loadHqLeads()).filter((lead) => lead.email.startsWith(PREFIX));
  assert.equal(leads.length, 3);
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

test("HQ overview does not load or expose modules outside the caller capability scope", async () => {
  await cleanup();
  const overview = await loadHqOverview(new Date("2026-08-28T20:00:00.000Z"), {
    leads: false,
    clients: false,
    support: false,
  });
  assert.equal(overview.newLeadCount, null);
  assert.equal(overview.activeClientCount, null);
  assert.equal(overview.openCompanyTaskCount, null);
  assert.equal(overview.openSupportCaseCount, null);
  assert.deepEqual(overview.recentLeads, []);
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
