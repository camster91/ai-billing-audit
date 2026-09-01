import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { prisma } from "../src/lib/prisma";
import {
  ClientEngagementError,
  createClientEngagement,
  createClientEngagementSchema,
  clientEngagementMutationSchema,
  updateClientEngagement,
} from "../src/lib/client-engagement";
import {
  CompanyTaskError,
  companyTaskMutationSchema,
  createCompanyTask,
  createCompanyTaskSchema,
  updateCompanyTask,
} from "../src/lib/company-task";

const PREFIX = "client-engagement-test-";
const operator = {
  userId: `${PREFIX}owner`,
  userEmail: `${PREFIX}owner@example.test`,
  role: "owner" as const,
};

async function cleanup() {
  await prisma.platformAuditEvent.deleteMany({ where: { actorUserId: { startsWith: PREFIX } } });
  await prisma.companyTask.deleteMany({ where: { engagement: { lead: { email: { startsWith: PREFIX } } } } });
  await prisma.clientEngagement.deleteMany({ where: { lead: { email: { startsWith: PREFIX } } } });
  await prisma.platformUserRole.deleteMany({ where: { userId: { startsWith: PREFIX } } });
  await prisma.lead.deleteMany({ where: { email: { startsWith: PREFIX } } });
  await prisma.user.deleteMany({ where: { email: { startsWith: PREFIX } } });
}

async function setup(status = "pilot_signed") {
  await cleanup();
  await prisma.user.createMany({
    data: [
      { id: operator.userId, email: operator.userEmail },
      { id: `${PREFIX}success`, email: `${PREFIX}success@example.test` },
      { id: `${PREFIX}sales`, email: `${PREFIX}sales@example.test` },
    ],
  });
  await prisma.platformUserRole.createMany({
    data: [
      { userId: operator.userId, role: "owner", grantedBy: PREFIX },
      { userId: `${PREFIX}success`, role: "client_success", grantedBy: PREFIX },
      { userId: `${PREFIX}sales`, role: "sales", grantedBy: PREFIX },
    ],
  });
  return prisma.lead.create({
    data: {
      name: "Client Contact",
      clinicName: "Client Clinic",
      email: `${PREFIX}lead@example.test`,
      billingSetup: "in_house",
      status,
    },
  });
}

function input(overrides: Record<string, unknown> = {}) {
  return {
    mutationId: randomUUID(),
    ownerUserId: `${PREFIX}success`,
    offerReference: "Pilot offer PO-2026-001",
    pilotStartAt: "2026-09-15T13:00:00.000Z",
    pilotEndAt: "2026-10-15T13:00:00.000Z",
    ...overrides,
  };
}

test("conversion creates one no-PHI engagement, default tasks, and audit event", async () => {
  const lead = await setup();
  const mutation = createClientEngagementSchema.parse(input());
  const engagement = await createClientEngagement(lead.id, mutation, operator);
  assert.equal(engagement.leadId, lead.id);
  assert.equal(engagement.status, "pilot_planning");
  assert.equal(engagement.privacyApprovalStatus, "pending");
  assert.equal(engagement.tasks.length, 4);
  assert.deepEqual(engagement.tasks.map((task) => task.title), [
    "Confirm approved pilot offer",
    "Record privacy and data approvals",
    "Confirm onboarding owner and timeline",
    "Verify first reviewed audit milestone",
  ]);
  assert.equal(await prisma.platformAuditEvent.count({ where: { requestId: mutation.mutationId } }), 1);

  const replay = await createClientEngagement(lead.id, mutation, operator);
  assert.equal(replay.id, engagement.id);
  assert.equal(await prisma.clientEngagement.count({ where: { leadId: lead.id } }), 1);
  assert.equal(await prisma.companyTask.count({ where: { engagementId: engagement.id } }), 4);
  await cleanup();
});

test("conversion rejects unapproved leads and sales ownership", async () => {
  const lead = await setup("demo_scheduled");
  await assert.rejects(
    createClientEngagement(lead.id, createClientEngagementSchema.parse(input()), operator),
    (error: unknown) => error instanceof ClientEngagementError && error.code === "lead_not_approved",
  );
  await prisma.lead.update({ where: { id: lead.id }, data: { status: "pilot_signed" } });
  await assert.rejects(
    createClientEngagement(
      lead.id,
      createClientEngagementSchema.parse(input({ ownerUserId: `${PREFIX}sales` })),
      operator,
    ),
    (error: unknown) => error instanceof ClientEngagementError && error.code === "invalid_owner",
  );
  assert.equal(await prisma.clientEngagement.count({ where: { leadId: lead.id } }), 0);
  await cleanup();
});

test("conversion input rejects clinical references and reversed pilot dates", () => {
  assert.equal(createClientEngagementSchema.safeParse(input({ offerReference: "Patient claim record" })).success, false);
  assert.equal(
    createClientEngagementSchema.safeParse(input({ pilotEndAt: "2026-09-01T13:00:00.000Z" })).success,
    false,
  );
});

test("company task update is versioned, idempotent, audited, and no-PHI", async () => {
  const lead = await setup();
  const engagement = await createClientEngagement(
    lead.id,
    createClientEngagementSchema.parse(input()),
    operator,
  );
  const task = engagement.tasks[0];
  assert.ok(task);
  const mutation = companyTaskMutationSchema.parse({
    expectedVersion: 0,
    mutationId: randomUUID(),
    status: "in_progress",
    priority: "high",
    ownerUserId: `${PREFIX}success`,
    dueAt: "2026-09-10T15:00:00.000Z",
    evidenceReference: "approval/PO-2026-001",
  });
  const updated = await updateCompanyTask(engagement.id, task.id, mutation, operator);
  assert.equal(updated.version, 1);
  assert.equal(updated.status, "in_progress");
  assert.equal(updated.ownerUserId, `${PREFIX}success`);
  assert.equal(await prisma.platformAuditEvent.count({ where: { requestId: mutation.mutationId } }), 1);

  const replay = await updateCompanyTask(engagement.id, task.id, mutation, operator);
  assert.equal(replay.version, 1);
  await assert.rejects(
    updateCompanyTask(
      engagement.id,
      task.id,
      companyTaskMutationSchema.parse({ ...mutation, mutationId: randomUUID(), priority: "low" }),
      operator,
    ),
    (error: unknown) => error instanceof CompanyTaskError && error.code === "version_conflict",
  );
  assert.equal(
    companyTaskMutationSchema.safeParse({ ...mutation, mutationId: randomUUID(), evidenceReference: "patient claim 123" }).success,
    false,
  );
  await cleanup();
});

test("engagement milestones are versioned, retry-safe, and audited", async () => {
  const lead = await setup();
  const engagement = await createClientEngagement(lead.id, createClientEngagementSchema.parse(input()), operator);
  const mutation = clientEngagementMutationSchema.parse({
    expectedVersion: 0,
    mutationId: randomUUID(),
    status: "active_pilot",
    privacyApprovalStatus: "approved",
    firstValueAt: "2026-09-20T15:00:00.000Z",
    healthStatus: "healthy",
  });
  const updated = await updateClientEngagement(engagement.id, mutation, operator);
  assert.equal(updated.version, 1);
  assert.equal(updated.status, "active_pilot");
  assert.equal(updated.privacyApprovalStatus, "approved");
  assert.equal(updated.healthStatus, "healthy");
  assert.equal(updated.firstValueAt?.toISOString(), "2026-09-20T15:00:00.000Z");
  assert.equal(await prisma.platformAuditEvent.count({ where: { requestId: mutation.mutationId } }), 1);

  const replay = await updateClientEngagement(engagement.id, mutation, operator);
  assert.equal(replay.version, 1);
  await assert.rejects(
    updateClientEngagement(
      engagement.id,
      clientEngagementMutationSchema.parse({ ...mutation, mutationId: randomUUID(), healthStatus: "watch" }),
      operator,
    ),
    (error: unknown) => error instanceof ClientEngagementError && error.code === "version_conflict",
  );
  await cleanup();
});

test("custom company tasks are no-PHI, owner-controlled, retry-safe, and audited", async () => {
  const lead = await setup();
  const engagement = await createClientEngagement(lead.id, createClientEngagementSchema.parse(input()), operator);
  const mutation = createCompanyTaskSchema.parse({
    mutationId: randomUUID(),
    title: "Prepare kickoff agenda",
    priority: "high",
    ownerUserId: `${PREFIX}success`,
    dueAt: "2026-09-12T15:00:00.000Z",
  });
  const task = await createCompanyTask(engagement.id, mutation, operator);
  assert.equal(task.title, "Prepare kickoff agenda");
  assert.equal(task.ownerUserId, `${PREFIX}success`);
  assert.equal(await prisma.platformAuditEvent.count({ where: { requestId: mutation.mutationId } }), 1);

  const replay = await createCompanyTask(engagement.id, mutation, operator);
  assert.equal(replay.id, task.id);
  await assert.rejects(
    createCompanyTask(
      engagement.id,
      createCompanyTaskSchema.parse({ ...mutation, mutationId: randomUUID(), ownerUserId: `${PREFIX}sales` }),
      operator,
    ),
    (error: unknown) => error instanceof CompanyTaskError && error.code === "invalid_owner",
  );
  assert.equal(createCompanyTaskSchema.safeParse({ ...mutation, mutationId: randomUUID(), title: "Review patient claim" }).success, false);
  await cleanup();
});
