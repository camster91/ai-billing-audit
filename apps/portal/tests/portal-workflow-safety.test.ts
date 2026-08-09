import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("audit dispatch reserves before enqueue and charges only after durable engine acknowledgement", async () => {
  const source = await readFile("src/app/api/audit/run/route.ts", "utf8");
  assert.match(source, /reserveAuditDispatch/);
  assert.match(source, /submitPortalAudit/);
  assert.match(source, /finalizeAuditDispatch/);
  assert.ok(source.indexOf("reserveAuditDispatch(") < source.indexOf("submitPortalAudit("));
  assert.ok(source.indexOf("submitPortalAudit(") < source.indexOf("finalizeAuditDispatch("));
  assert.doesNotMatch(source, /consumeAuditQuota/);
  assert.match(source, /decryptPortalString/);
});

test("legacy onboarding no longer calls nonexistent API routes", async () => {
  const source = await readFile("src/app/onboarding/page.tsx", "utf8");
  assert.match(source, /redirect\("\/pricing"\)/);
  assert.doesNotMatch(source, /OnboardingFlow/);
});

test("audit status polling is tenant scoped and imports only terminal engine results", async () => {
  const source = await readFile("src/app/api/audit/status/route.ts", "utf8");
  assert.match(source, /tenantId:\s*tenant\.id/);
  assert.match(source, /fetchPortalAuditJob/);
  assert.match(source, /importEngineAuditResult/);
  assert.match(source, /job\.status === "done"/);
  assert.match(source, /job\.status === "failed"/);
});

test("encounter review exposes audit dispatch and does not claim pending work ran clean", async () => {
  const page = await readFile("src/app/encounters/[id]/page.tsx", "utf8");
  const control = await readFile(
    "src/app/encounters/[id]/_components/audit-run-control.tsx",
    "utf8",
  );
  assert.match(page, /AuditRunControl/);
  assert.match(control, /\/api\/audit\/run/);
  assert.match(control, /\/api\/audit\/status/);
  assert.match(control, /router\.refresh/);
  assert.match(page, /status === "completed"/);
});
