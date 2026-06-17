import { randomBytes } from "node:crypto";
import { prisma } from "../src/lib/prisma.ts";
import "dotenv/config";
import fs from "node:fs";

const SESSION = process.env.E2E_SESSION;
const USER_ID = process.env.E2E_USER_ID;
const EMAIL = process.env.E2E_EMAIL;
const BASE = process.env.E2E_BASE || "http://localhost:3000";
if (!SESSION || !USER_ID || !EMAIL) { console.error("env missing"); process.exit(1); }

// NextAuth v5 + PrismaAdapter uses DATABASE session strategy here —
// the auth() helper looks up the Session row by raw sessionToken, not
// a signed JWT. Persist a Session row, then send the token as the
// cookie value.
const token = randomBytes(32).toString("hex");
await prisma.session.create({
  data: {
    sessionToken: token,
    userId: USER_ID,
    expires: new Date(Date.now() + 1000 * 60 * 60),
  },
});
fs.writeFileSync("/tmp/e2e-jwt.txt", token);
console.log("TOKEN_LEN", token.length);

const cookieJar = `authjs.session-token=${token}`;

async function call(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { cookie: cookieJar, "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  let json = null;
  try { json = await res.json(); } catch {}
  return { status: res.status, json };
}

const results = [];
const r1 = await call("POST", "/api/onboarding/redeem", { sessionId: SESSION });
results.push({ step: "redeem", status: r1.status, body: r1.json });
console.log("REDEEM_RESPONSE:", r1.status, JSON.stringify(r1.json).slice(0, 500));
if (r1.status !== 200) throw new Error("redeem failed");
if (!r1.json?.tenant?.id) throw new Error("no tenant: " + JSON.stringify(r1.json));
const tenantId = r1.json.tenant.id;

for (const [step, body] of [
  ["clinic-profile", { tenantId, clinicName: "E2E Test Clinic", clinicNpi: "1234567890", clinicTimezone: "America/Toronto" }],
  ["region", { tenantId, region: "ca-central-1" }],
  ["ehr", { tenantId, mode: "manual" }],
  ["first-encounter", { tenantId, mode: "skipped" }],
  ["complete", { tenantId }],
]) {
  const r = await call("POST", `/api/onboarding/${step}`, body);
  results.push({ step, status: r.status, body: r.json });
  if (r.status !== 200) throw new Error(`${step} failed: ${JSON.stringify(r)}`);
}

const r7 = await call("POST", "/api/onboarding/redeem", { sessionId: SESSION });
results.push({ step: "replay-redeem", status: r7.status, body: r7.json });
if (r7.status !== 200) throw new Error("replay-redeem failed");

// Replaying from a different user must be rejected
const other = await prisma.user.create({ data: { email: "e2e-other-" + randomBytes(4).toString("hex") + "@example.com" } });
const otherToken = randomBytes(32).toString("hex");
await prisma.session.create({
  data: { sessionToken: otherToken, userId: other.id, expires: new Date(Date.now() + 3600 * 1000) },
});
const r8 = await fetch(`${BASE}/api/onboarding/redeem`, {
  method: "POST",
  headers: { cookie: `authjs.session-token=${otherToken}`, "content-type": "application/json" },
  body: JSON.stringify({ sessionId: SESSION }),
});
const r8json = await r8.json();
results.push({ step: "other-user-replay", status: r8.status, body: r8json });
if (r8.status !== 409) throw new Error("other-user-replay should be 409, got " + r8.status);

const t = await prisma.tenant.findUnique({ where: { id: tenantId } });
const m = await prisma.membership.findFirst({ where: { tenantId } });
const ledger = await prisma.redeemedCheckoutSession.findUnique({ where: { sessionId: SESSION } });
const memberships = await prisma.membership.count({ where: { tenantId } });
const ledgers = await prisma.redeemedCheckoutSession.count({ where: { sessionId: SESSION } });
const tenants = await prisma.tenant.count({ where: { id: tenantId } });

console.log(JSON.stringify({
  steps: results.map(r => ({ step: r.step, status: r.status, ok: r.status === 200 || (r.step === "other-user-replay" && r.status === 409) })),
  tenant: t && {
    name: t.name, clinicName: t.clinicName, clinicNpi: t.clinicNpi, clinicTimezone: t.clinicTimezone,
    dataResidencyRegion: t.dataResidencyRegion, residencyRegionLocked: t.residencyRegionLocked,
    ehrConnectionMode: t.ehrConnectionMode, firstEncounterUploadMode: t.firstEncounterUploadMode,
    onboardingStep: t.onboardingStep, onboardingCompletedAt: t.onboardingCompletedAt,
  },
  membership: m && { userId: m.userId, role: m.role },
  ledger: ledger && { sessionId: ledger.sessionId, userId: ledger.userId },
  counts: { memberships, ledgers, tenants },
  magicLink: results.find(r => r.step === "complete")?.body?.magicLink ?? null,
  emailMock: results.find(r => r.step === "complete")?.body?.emailMock ?? null,
  emailSent: results.find(r => r.step === "complete")?.body?.emailSent ?? null,
}, null, 2));
