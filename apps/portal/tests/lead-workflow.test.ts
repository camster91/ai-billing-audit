import assert from "node:assert/strict";
import test from "node:test";
import { randomUUID } from "node:crypto";
import { prisma } from "../src/lib/prisma";
import {
  LeadWorkflowError,
  leadMutationSchema,
  updateLeadWorkflow,
  type LeadMutationInput,
} from "../src/lib/lead-workflow";
import { canTransitionLead } from "../src/lib/lead-workflow-rules";

const PREFIX = "lead-workflow-test-";

const operator = {
  userId: `${PREFIX}owner`,
  userEmail: `${PREFIX}owner@example.test`,
  role: "owner" as const,
};

async function cleanup() {
  await prisma.platformAuditEvent.deleteMany({
    where: {
      OR: [
        { actorUserId: { startsWith: PREFIX } },
        { targetId: { startsWith: PREFIX } },
      ],
    },
  });
  await prisma.leadActivity.deleteMany({ where: { leadId: { startsWith: PREFIX } } });
  await prisma.platformUserRole.deleteMany({ where: { grantedBy: PREFIX } });
  await prisma.lead.deleteMany({ where: { email: { startsWith: PREFIX } } });
  await prisma.user.deleteMany({ where: { email: { startsWith: PREFIX } } });
}

async function setup() {
  await cleanup();
  const owner = await prisma.user.create({ data: { id: operator.userId, email: operator.userEmail } });
  const sales = await prisma.user.create({ data: { id: `${PREFIX}sales`, email: `${PREFIX}sales@example.test` } });
  const support = await prisma.user.create({ data: { id: `${PREFIX}support`, email: `${PREFIX}support@example.test` } });
  await prisma.platformUserRole.createMany({
    data: [
      { userId: owner.id, role: "owner", grantedBy: PREFIX },
      { userId: sales.id, role: "sales", grantedBy: PREFIX },
      { userId: support.id, role: "support", grantedBy: PREFIX },
    ],
  });
  return prisma.lead.create({
    data: {
      id: `${PREFIX}lead`,
      name: "Lead Workflow",
      clinicName: "Workflow Clinic",
      email: `${PREFIX}lead@example.test`,
      billingSetup: "in_house",
      status: "new",
    },
  });
}

function input(overrides: Partial<LeadMutationInput> = {}): LeadMutationInput {
  return {
    expectedVersion: 0,
    mutationId: randomUUID(),
    status: "contacted",
    ownerUserId: `${PREFIX}sales`,
    nextAction: "Confirm discovery-call attendees",
    nextActionAt: "2026-09-01T15:00:00.000Z",
    lostReason: null,
    logContactNow: true,
    ...overrides,
  };
}

test("lead workflow rules permit deliberate progression and reject skipped terminal jumps", () => {
  assert.equal(canTransitionLead("new", "contacted"), true);
  assert.equal(canTransitionLead("new", "lost"), true);
  assert.equal(canTransitionLead("new", "pilot_signed"), false);
  assert.equal(canTransitionLead("contacted", "demo_scheduled"), true);
  assert.equal(canTransitionLead("lost", "contacted"), false);
  assert.equal(canTransitionLead("unknown", "contacted"), false);
});

test("lead input rejects clinical content, incomplete next actions, and missing loss reasons", () => {
  assert.equal(leadMutationSchema.safeParse(input({ nextAction: "Review patient diagnosis", nextActionAt: "2026-09-01T15:00:00.000Z" })).success, false);
  assert.equal(leadMutationSchema.safeParse(input({ nextActionAt: null })).success, false);
  assert.equal(leadMutationSchema.safeParse(input({ status: "lost", nextAction: null, nextActionAt: null, lostReason: null })).success, false);
  assert.equal(leadMutationSchema.safeParse(input({ status: "lost", nextAction: null, nextActionAt: null, lostReason: "No current workflow owner" })).success, true);
});

test("lead update is atomic, field-audited, idempotent, and versioned", async () => {
  const lead = await setup();
  const mutation = input();
  const now = new Date("2026-08-28T22:00:00.000Z");
  const updated = await updateLeadWorkflow(lead.id, mutation, operator, now);
  assert.equal(updated.version, 1);
  assert.equal(updated.status, "contacted");
  assert.equal(updated.ownerUserId, `${PREFIX}sales`);
  assert.equal(updated.lastContactedAt?.toISOString(), now.toISOString());

  const activities = await prisma.leadActivity.findMany({
    where: { mutationId: mutation.mutationId },
    orderBy: { kind: "asc" },
  });
  assert.deepEqual(activities.map((activity) => activity.kind), [
    "assignment_changed",
    "contact_logged",
    "next_action_changed",
    "stage_changed",
  ]);
  assert.equal(await prisma.platformAuditEvent.count({ where: { requestId: mutation.mutationId } }), 1);

  const replay = await updateLeadWorkflow(lead.id, mutation, operator, now);
  assert.equal(replay.version, 1);
  assert.equal(await prisma.leadActivity.count({ where: { mutationId: mutation.mutationId } }), 4);
  await cleanup();
});

test("stale form receives a version conflict instead of overwriting", async () => {
  const lead = await setup();
  await updateLeadWorkflow(lead.id, input(), operator);
  await assert.rejects(
    updateLeadWorkflow(
      lead.id,
      input({ mutationId: randomUUID(), nextAction: "Different stale edit" }),
      operator,
    ),
    (error: unknown) => error instanceof LeadWorkflowError && error.code === "version_conflict",
  );
  const persisted = await prisma.lead.findUniqueOrThrow({ where: { id: lead.id } });
  assert.equal(persisted.nextAction, "Confirm discovery-call attendees");
  assert.equal(persisted.version, 1);
  await cleanup();
});

test("invalid transition and non-sales assignee are rejected without side effects", async () => {
  const lead = await setup();
  await assert.rejects(
    updateLeadWorkflow(lead.id, input({ status: "pilot_signed", nextAction: null, nextActionAt: null }), operator),
    (error: unknown) => error instanceof LeadWorkflowError && error.code === "invalid_transition",
  );
  await assert.rejects(
    updateLeadWorkflow(lead.id, input({ ownerUserId: `${PREFIX}support` }), operator),
    (error: unknown) => error instanceof LeadWorkflowError && error.code === "invalid_owner",
  );
  assert.equal((await prisma.lead.findUniqueOrThrow({ where: { id: lead.id } })).version, 0);
  assert.equal(await prisma.leadActivity.count({ where: { leadId: lead.id } }), 0);
  await cleanup();
});
