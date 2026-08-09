import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import test from "node:test";

import { decryptPortalString, encryptPortalString } from "../src/lib/data-encryption";
import type { EngineFinding } from "../src/lib/fastapi";
import { prisma } from "../src/lib/prisma";
import * as resultModule from "../src/lib/audit-results";

test("engine findings without ids receive stable distinct storage keys", () => {
  assert.equal(typeof resultModule.engineFindingStorageKey, "function");
  const first: EngineFinding = {
    finding_id: "",
    category: "documentation",
    severity: 2,
    rule_id: "RULE-A",
    quote: "first evidence",
    explanation: "first",
  };
  const second: EngineFinding = {
    ...first,
    rule_id: "RULE-B",
    quote: "second evidence",
  };
  assert.equal(
    resultModule.engineFindingStorageKey(first),
    resultModule.engineFindingStorageKey({ ...first }),
  );
  assert.notEqual(
    resultModule.engineFindingStorageKey(first),
    resultModule.engineFindingStorageKey(second),
  );
});

test("terminal audit import encrypts evidence and never resets a reviewed finding", async () => {
  assert.equal(typeof resultModule.importEngineAuditResult, "function");
  process.env.ZORVA_PHI_ENCRYPTION_KEY = randomBytes(32).toString("base64url");
  const tag = randomBytes(5).toString("hex");
  const tenant = await prisma.tenant.create({
    data: { name: `Result ${tag}`, slug: `result-${tag}`, auditQuotaLimit: 5 },
  });
  const claim = await prisma.encounterClaim.create({
    data: {
      payer: "AHCIP",
      providerNpi: "1234567890",
      providerName: "Dr Result",
      cptCodesJson: JSON.stringify([{ code: "99213" }]),
    },
  });
  const encounter = await prisma.encounter.create({
    data: {
      tenantId: tenant.id,
      patientHash: "b".repeat(64),
      dateOfService: new Date("2026-08-08T00:00:00Z"),
      specialty: "family_medicine",
      clinicalNote: encryptPortalString("Documented assessment and plan."),
      claimId: claim.id,
      status: "auditing",
    },
  });
  await prisma.auditDispatch.create({
    data: {
      tenantId: tenant.id,
      encounterId: encounter.id,
      engineJobId: `job-${tag}`,
      engineStatusUrl: `/encounters/upload/jobs/job-${tag}`,
      status: "queued",
      quotaReserved: false,
      quotaChargedAt: new Date(),
      submittedAt: new Date(),
    },
  });
  const findings: EngineFinding[] = [{
    finding_id: "engine-finding-1",
    category: "code_mismatch",
    severity: 3,
    rule_id: "RULE-1",
    suggested_code: "99214",
    quote: "assessment and plan",
    explanation: "Documented complexity supports review.",
  }];

  try {
    const first = await resultModule.importEngineAuditResult({
      tenantId: tenant.id,
      encounterId: encounter.id,
      engineJobId: `job-${tag}`,
      findings,
    });
    assert.equal(first.kind, "imported");
    const stored = await prisma.finding.findFirstOrThrow({
      where: { encounterId: encounter.id },
    });
    assert.notEqual(stored.evidenceQuote, findings[0].quote);
    assert.equal(decryptPortalString(stored.evidenceQuote), findings[0].quote);
    assert.equal(stored.billingRuleReference, "RULE-1");
    assert.equal(stored.status, "pending");

    await prisma.finding.update({ where: { id: stored.id }, data: { status: "accepted" } });
    const again = await resultModule.importEngineAuditResult({
      tenantId: tenant.id,
      encounterId: encounter.id,
      engineJobId: `job-${tag}`,
      findings: [{ ...findings[0], quote: "changed engine quote" }],
    });
    assert.equal(again.kind, "already_imported");
    const reviewed = await prisma.finding.findUniqueOrThrow({ where: { id: stored.id } });
    assert.equal(reviewed.status, "accepted");
    assert.equal(decryptPortalString(reviewed.evidenceQuote), findings[0].quote);
  } finally {
    await prisma.tenant.delete({ where: { id: tenant.id } }).catch(() => {});
    await prisma.encounterClaim.delete({ where: { id: claim.id } }).catch(() => {});
  }
});
