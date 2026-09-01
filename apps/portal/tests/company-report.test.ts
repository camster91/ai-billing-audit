import assert from "node:assert/strict";
import test from "node:test";
import { loadCompanyReport } from "../src/lib/company-report";
import { prisma } from "../src/lib/prisma";

const PREFIX = "company-report-test-";

async function cleanup() {
  await prisma.supportActivity.deleteMany({ where: { supportCase: { engagement: { lead: { email: { startsWith: PREFIX } } } } } });
  await prisma.supportCase.deleteMany({ where: { engagement: { lead: { email: { startsWith: PREFIX } } } } });
  await prisma.companyTask.deleteMany({ where: { engagement: { lead: { email: { startsWith: PREFIX } } } } });
  await prisma.clientEngagement.deleteMany({ where: { lead: { email: { startsWith: PREFIX } } } });
  await prisma.leadActivity.deleteMany({ where: { lead: { email: { startsWith: PREFIX } } } });
  await prisma.lead.deleteMany({ where: { email: { startsWith: PREFIX } } });
}

test("company report uses dated source records and represents missing business data honestly", async () => {
  await cleanup();
  const periodStart = new Date("2031-01-01T00:00:00.000Z");
  const periodEnd = new Date("2031-02-01T00:00:00.000Z");
  const pilotLead = await prisma.lead.create({
    data: {
      name: "Pilot operator",
      clinicName: "Report Pilot Clinic",
      email: `${PREFIX}pilot@example.test`,
      billingSetup: "in_house",
      status: "pilot_signed",
      createdAt: new Date("2031-01-03T00:00:00.000Z"),
      activities: { create: { actorRole: "owner", kind: "stage_changed", fromValue: "demo_scheduled", toValue: "pilot_signed", mutationId: `${PREFIX}pilot`, occurredAt: new Date("2031-01-10T00:00:00.000Z") } },
    },
  });
  await prisma.lead.create({
    data: {
      name: "Lost operator",
      clinicName: "Report Lost Clinic",
      email: `${PREFIX}lost@example.test`,
      billingSetup: "hybrid",
      status: "lost",
      createdAt: new Date("2031-01-04T00:00:00.000Z"),
      activities: { create: { actorRole: "owner", kind: "stage_changed", fromValue: "contacted", toValue: "lost", mutationId: `${PREFIX}lost`, occurredAt: new Date("2031-01-11T00:00:00.000Z") } },
    },
  });
  const engagement = await prisma.clientEngagement.create({
    data: {
      leadId: pilotLead.id,
      clinicName: pilotLead.clinicName,
      status: "pilot_active",
      healthStatus: "at_risk",
      firstValueAt: new Date("2031-01-15T00:00:00.000Z"),
      createdAt: new Date("2031-01-12T00:00:00.000Z"),
    },
  });
  await prisma.supportCase.create({
    data: {
      engagementId: engagement.id,
      category: "product",
      severity: "high",
      status: "resolved",
      safeSummary: "Report fixture without clinical data",
      createdAt: new Date("2031-01-20T00:00:00.000Z"),
      resolvedAt: new Date("2031-01-21T12:00:00.000Z"),
    },
  });

  const report = await loadCompanyReport(periodStart, periodEnd, new Date("2031-02-01T00:00:00.000Z"));
  const metrics = Object.fromEntries(report.metrics.map((item) => [item.key, item]));
  assert.equal(metrics.acquired_leads.value, 2);
  assert.equal(metrics.pilot_decisions.value, 1);
  assert.equal(metrics.pilot_conversion.value, 50);
  assert.equal(metrics.engagements_created.value, 1);
  assert.equal(metrics.first_value.value, 1);
  assert.equal(metrics.at_risk_clients.value, 1);
  assert.equal(metrics.support_opened.value, 1);
  assert.equal(metrics.support_resolution.value, 36);
  assert.equal(metrics.revenue.state, "unavailable");
  assert.equal(metrics.revenue.value, null);
  assert.equal(metrics.cost_to_serve.state, "unavailable");
  assert.deepEqual(report.campaignOutcomes, []);
  await cleanup();
});

test("company report returns unknown rates instead of manufacturing a zero denominator", async () => {
  const report = await loadCompanyReport(
    new Date("2041-01-01T00:00:00.000Z"),
    new Date("2041-02-01T00:00:00.000Z"),
    new Date("2041-02-01T00:00:00.000Z"),
  );
  const conversion = report.metrics.find((item) => item.key === "pilot_conversion");
  assert.equal(conversion?.value, null);
  assert.equal(conversion?.state, "unknown");
});
