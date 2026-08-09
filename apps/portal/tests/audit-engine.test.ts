import assert from "node:assert/strict";
import test from "node:test";

import * as fastapi from "../src/lib/fastapi";
import * as submission from "../src/lib/audit-submission";

const principal = {
  subject: "user-1",
  tenantId: "tenant-1",
  portalRole: "auditor",
};

test("portal claim lines accept the canonical stored payload and legacy arrays", () => {
  assert.equal(typeof submission.parsePortalClaimLines, "function");
  assert.deepEqual(
    submission.parsePortalClaimLines(JSON.stringify({
      lines: [{ code: "99213", modifier: "25" }],
      totalCents: 4200,
      payer: "AHCIP",
      providerNpi: "1234567890",
      providerName: "Dr Test",
      dateOfService: "2026-08-08",
    })),
    [{ code: "99213", modifier: "25" }],
  );
  assert.deepEqual(
    submission.parsePortalClaimLines(JSON.stringify([{ code: "99214" }])),
    [{ code: "99214" }],
  );
});

test("submitPortalAudit sends one authenticated idempotent claim-plus-note request", async () => {
  assert.equal(typeof fastapi.submitPortalAudit, "function");
  let captured: { url: string; init?: RequestInit } | null = null;
  const fetchImpl: typeof fetch = async (input, init) => {
    captured = { url: String(input), init };
    return new Response(
      JSON.stringify({
        job_id: "job-123",
        encounter_id: "enc-1",
        status: "queued",
        status_url: "/encounters/upload/jobs/job-123",
        dedup_hit: false,
      }),
      { status: 202, headers: { "Content-Type": "application/json" } },
    );
  };

  const result = await fastapi.submitPortalAudit(
    {
      encounterId: "enc-1",
      patientHash: "patient-hash",
      providerNpi: "1234567890",
      dateOfService: "2026-08-08",
      cptCodes: ["99213-25"],
      diagnosisCodes: ["I10"],
      clinicalNote: "Assessment and plan documented.",
    },
    principal,
    { fetchImpl, bearerToken: "bearer", signingSecret: "s".repeat(32) },
  );

  assert.deepEqual(result, {
    kind: "ok",
    jobId: "job-123",
    statusUrl: "/encounters/upload/jobs/job-123",
    dedupHit: false,
  });
  assert.ok(captured);
  const request = captured as { url: string; init?: RequestInit };
  assert.equal(request.url, "https://ai-billing-audit.ashbi.ca/api/audits");
  assert.equal(request.init?.method, "POST");
  const headers = request.init?.headers as Record<string, string>;
  assert.equal(headers.Authorization, "Bearer bearer");
  assert.ok(headers["X-Zorva-Principal"]);
  assert.ok(headers["X-Zorva-Signature"]);
  assert.match(headers["Idempotency-Key"], /^portal-audit-[a-f0-9]{64}$/);
  assert.deepEqual(JSON.parse(String(request.init?.body)), {
    encounter_id: "enc-1",
    patient_id: "patient-hash",
    NPI: "1234567890",
    date_of_service: "2026-08-08",
    CPT_codes: ["99213-25"],
    diagnosis_codes: ["I10"],
    clinical_note: "Assessment and plan documented.",
  });
});

test("fetchPortalAuditJob returns a typed terminal engine result", async () => {
  assert.equal(typeof fastapi.fetchPortalAuditJob, "function");
  const fetchImpl: typeof fetch = async () =>
    new Response(
      JSON.stringify({
        job_id: "job-123",
        encounter_id: "enc-1",
        status: "done",
        error: null,
        result: {
          summary: "One finding.",
          findings: [
            {
              finding_id: "f-1",
              category: "code_mismatch",
              severity: 3,
              rule_id: "R-1",
              rule_ids: ["R-1"],
              suggested_code: "99214",
              quote: "Assessment and plan",
              explanation: "Higher complexity documented.",
            },
          ],
        },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );

  const result = await fastapi.fetchPortalAuditJob("job-123", principal, {
    fetchImpl,
    bearerToken: "bearer",
    signingSecret: "s".repeat(32),
  });

  assert.equal(result.kind, "ok");
  if (result.kind === "ok") {
    assert.equal(result.job.status, "done");
    assert.equal(result.job.result?.findings[0]?.finding_id, "f-1");
  }
});
