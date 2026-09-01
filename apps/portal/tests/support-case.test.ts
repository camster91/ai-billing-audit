import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { prisma } from "../src/lib/prisma";
import { createSupportCase, createSupportCaseSchema, SupportCaseError, supportCaseMutationSchema, updateSupportCase } from "../src/lib/support-case";

const PREFIX = "support-case-test-";
const operator = { userId: `${PREFIX}owner`, userEmail: `${PREFIX}owner@example.test`, role: "owner" as const };

async function cleanup() {
  await prisma.supportActivity.deleteMany({ where: { supportCase: { engagement: { lead: { email: { startsWith: PREFIX } } } } } });
  await prisma.supportCase.deleteMany({ where: { engagement: { lead: { email: { startsWith: PREFIX } } } } });
  await prisma.platformAuditEvent.deleteMany({ where: { actorUserId: { startsWith: PREFIX } } });
  await prisma.clientEngagement.deleteMany({ where: { lead: { email: { startsWith: PREFIX } } } });
  await prisma.platformUserRole.deleteMany({ where: { userId: { startsWith: PREFIX } } });
  await prisma.lead.deleteMany({ where: { email: { startsWith: PREFIX } } });
  await prisma.user.deleteMany({ where: { email: { startsWith: PREFIX } } });
}

async function setup() {
  await cleanup();
  await prisma.user.createMany({ data: [
    { id: operator.userId, email: operator.userEmail },
    { id: `${PREFIX}support`, email: `${PREFIX}support@example.test` },
    { id: `${PREFIX}sales`, email: `${PREFIX}sales@example.test` },
  ] });
  await prisma.platformUserRole.createMany({ data: [
    { userId: operator.userId, role: "owner", grantedBy: PREFIX },
    { userId: `${PREFIX}support`, role: "support", grantedBy: PREFIX },
    { userId: `${PREFIX}sales`, role: "sales", grantedBy: PREFIX },
  ] });
  const lead = await prisma.lead.create({ data: { name: "Support Contact", clinicName: "Support Clinic", email: `${PREFIX}lead@example.test`, billingSetup: "in_house", status: "pilot_signed" } });
  return prisma.clientEngagement.create({ data: { leadId: lead.id, clinicName: lead.clinicName } });
}

test("support cases are no-PHI, retry-safe, owner-controlled, and audited", async () => {
  const engagement = await setup();
  const mutation = createSupportCaseSchema.parse({ mutationId: randomUUID(), engagementId: engagement.id, category: "workflow", severity: "high", safeSummary: "Team cannot access the review workspace", ownerUserId: `${PREFIX}support`, dueAt: "2026-09-02T15:00:00.000Z" });
  const supportCase = await createSupportCase(mutation, operator);
  assert.equal(supportCase.status, "new");
  assert.equal(await prisma.supportActivity.count({ where: { caseId: supportCase.id } }), 1);
  assert.equal(await prisma.platformAuditEvent.count({ where: { requestId: mutation.mutationId } }), 1);
  assert.equal((await createSupportCase(mutation, operator)).id, supportCase.id);
  await assert.rejects(
    createSupportCase(createSupportCaseSchema.parse({ ...mutation, mutationId: randomUUID(), ownerUserId: `${PREFIX}sales` }), operator),
    (error: unknown) => error instanceof SupportCaseError && error.code === "invalid_owner",
  );
  assert.equal(createSupportCaseSchema.safeParse({ ...mutation, mutationId: randomUUID(), safeSummary: "Patient claim is missing" }).success, false);
  await cleanup();
});

test("support updates are versioned, timestamped, retry-safe, and content-safe", async () => {
  const engagement = await setup();
  const created = await createSupportCase(createSupportCaseSchema.parse({ mutationId: randomUUID(), engagementId: engagement.id, category: "access", severity: "normal", safeSummary: "Login link does not reach the workspace", ownerUserId: null, dueAt: null }), operator);
  const mutation = supportCaseMutationSchema.parse({ expectedVersion: 0, mutationId: randomUUID(), category: "access", severity: "high", status: "resolved", safeSummary: "Login link delivery configuration corrected", ownerUserId: `${PREFIX}support`, dueAt: null, linkedIssueReference: "github/issues/123" });
  const now = new Date("2026-09-01T18:00:00.000Z");
  const updated = await updateSupportCase(created.id, mutation, operator, now);
  assert.equal(updated.version, 1); assert.equal(updated.acknowledgedAt?.toISOString(), now.toISOString()); assert.equal(updated.resolvedAt?.toISOString(), now.toISOString());
  assert.equal(await prisma.supportActivity.count({ where: { caseId: created.id } }), 2);
  assert.equal((await updateSupportCase(created.id, mutation, operator, now)).version, 1);
  await assert.rejects(updateSupportCase(created.id, supportCaseMutationSchema.parse({ ...mutation, mutationId: randomUUID(), severity: "urgent" }), operator), (error: unknown) => error instanceof SupportCaseError && error.code === "version_conflict");
  assert.equal(supportCaseMutationSchema.safeParse({ ...mutation, mutationId: randomUUID(), linkedIssueReference: "patient claim issue" }).success, false);
  await cleanup();
});

test("support activity migrations make history append-only in both databases", () => {
  const sqlite = readFileSync(path.join(process.cwd(), "prisma/migrations/20260901130000_add_support_cases/migration.sql"), "utf8");
  const postgres = readFileSync(path.join(process.cwd(), "prisma/postgresql/migrations/20260901130000_add_support_cases/migration.sql"), "utf8");
  assert.match(sqlite, /SupportActivity_immutable_update/);
  assert.match(sqlite, /SupportActivity_immutable_delete/);
  assert.match(postgres, /SupportActivity_immutable/);
  assert.match(postgres, /deny_hq_history_mutation/);
});
