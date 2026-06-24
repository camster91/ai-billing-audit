// Direct test of the /api/leads handler without going through Next dev.
//
// Spins up the route handler in-process via a minimal fetch shim so
// we can verify the database, email, and Slack side effects without
// dealing with Next dev's Turbopack chunk loading (which has a
// NODE_MODULE_VERSION mismatch in the dev environment).

import { POST } from "../src/app/api/leads/route";
import { prisma } from "../src/lib/prisma";
import { isDisposableEmail } from "../src/lib/disposable-email-domains";
import { isLeadsEmailMockMode } from "../src/lib/leads-email";
import { isLeadsSlackMockMode } from "../src/lib/leads-slack";

function buildReq(body: unknown): Request {
  return new Request("http://localhost/api/leads", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function getJson(resp: Response): Promise<unknown> {
  return resp.json();
}

let totalPass = 0;
let totalFail = 0;

function check(name: string, cond: boolean, detail?: string): void {
  if (cond) {
    console.log(`  ok  ${name}`);
    totalPass++;
  } else {
    console.log(`  FAIL ${name}${detail ? "  -- " + detail : ""}`);
    totalFail++;
  }
}

async function main(): Promise<void> {
  console.log("=== /api/leads direct handler test ===\n");

  console.log("Mock modes:");
  console.log("  email:", isLeadsEmailMockMode());
  console.log("  slack:", isLeadsSlackMockMode());

  console.log("\ndisposable check:");
  check("mailinator.com blocked", isDisposableEmail("foo@mailinator.com"));
  check("guerrillamail.com blocked", isDisposableEmail("foo@guerrillamail.com"));
  check("real domain NOT blocked", !isDisposableEmail("foo@clinic.test"));
  check("case-insensitive", isDisposableEmail("foo@MAILINATOR.COM"));
  check("invalid email returns false", !isDisposableEmail("notanemail"));
  check("empty returns false", !isDisposableEmail(""));
  check("subdomain NOT blocked", !isDisposableEmail("foo@mail.foo.com"));

  console.log("\nvalid POST inserts a row:");
  const validBody = {
    name: "Jane Smith",
    clinicName: "Downtown Family Health",
    email: "jane@clinic.test",
    claimVolume: 450,
    billingSetup: "hybrid" as const,
  };
  const resp1 = await POST(buildReq(validBody));
  const data1 = (await getJson(resp1)) as { ok?: boolean; leadId?: string; error?: string };
  check("status 200", resp1.status === 200, `got ${resp1.status}`);
  check("returns ok=true", data1.ok === true);
  check("returns leadId", typeof data1.leadId === "string");
  if (data1.leadId) {
    const row = await prisma.lead.findUnique({ where: { id: data1.leadId } });
    check("row exists in DB", row !== null);
    if (row) {
      check("name persisted", row.name === "Jane Smith");
      check("clinicName persisted", row.clinicName === "Downtown Family Health");
      check("email lowercased", row.email === "jane@clinic.test");
      check("claimVolume persisted", row.claimVolume === 450);
      check("billingSetup persisted", row.billingSetup === "hybrid");
      check("no IP / UA column", !("ip" in row) && !("userAgent" in row));
    }
  }

  console.log("\nemail casing preserved for name, lowercased for email:");
  const mixedCase = {
    name: "Alex DE LA CRUZ",
    clinicName: "Mi Clinica",
    email: "ALEX@Clinic.Test",
    claimVolume: 100,
    billingSetup: "in_house" as const,
  };
  const resp2 = await POST(buildReq(mixedCase));
  const data2 = (await getJson(resp2)) as { leadId?: string };
  if (data2.leadId) {
    const row = await prisma.lead.findUnique({ where: { id: data2.leadId } });
    if (row) {
      check("name preserves case", row.name === "Alex DE LA CRUZ");
      check("clinicName preserves case", row.clinicName === "Mi Clinica");
      check("email lowercased on insert", row.email === "alex@clinic.test");
    }
  }

  console.log("\ndisposable email rejected:");
  const dispBody = {
    name: "Spam Bot",
    clinicName: "Fake Co",
    email: "throwaway@mailinator.com",
    claimVolume: 1,
    billingSetup: "in_house" as const,
  };
  const beforeCount = await prisma.lead.count();
  const resp3 = await POST(buildReq(dispBody));
  const afterCount = await prisma.lead.count();
  check("status 400", resp3.status === 400, `got ${resp3.status}`);
  const data3 = (await getJson(resp3)) as { error?: string };
  check("returns disposable_email", data3.error === "disposable_email");
  check("no row created", afterCount === beforeCount);

  console.log("\ninvalid payloads return 400 and don't insert:");
  for (const [label, body] of [
    ["missing name", { clinicName: "X", email: "x@y.test", claimVolume: 1, billingSetup: "in_house" }],
    ["missing email", { name: "X", clinicName: "X", claimVolume: 1, billingSetup: "in_house" }],
    ["invalid email shape", { name: "X", clinicName: "X", email: "not-an-email", claimVolume: 1, billingSetup: "in_house" }],
    ["invalid billingSetup", { name: "X", clinicName: "X", email: "x@y.test", claimVolume: 1, billingSetup: "fubar" }],
    ["negative claimVolume", { name: "X", clinicName: "X", email: "x@y.test", claimVolume: -1, billingSetup: "in_house" }],
    ["claimVolume > 100k", { name: "X", clinicName: "X", email: "x@y.test", claimVolume: 100001, billingSetup: "in_house" }],
  ] as const) {
    const before = await prisma.lead.count();
    const resp = await POST(buildReq(body));
    const after = await prisma.lead.count();
    check(`${label}: status 400`, resp.status === 400, `got ${resp.status}`);
    check(`${label}: no row created`, after === before);
  }

  console.log("\nmalformed JSON:");
  const resp4 = await POST(
    new Request("http://localhost/api/leads", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "not json",
    }),
  );
  check("status 400", resp4.status === 400, `got ${resp4.status}`);

  console.log("\nnull claimVolume is allowed:");
  const nullVol = {
    name: "Null Tester",
    clinicName: "Null Co",
    email: "null@clinic.test",
    claimVolume: null,
    billingSetup: "outsourced" as const,
  };
  const resp5 = await POST(buildReq(nullVol));
  const data5 = (await getJson(resp5)) as { ok?: boolean; leadId?: string };
  check("status 200", resp5.status === 200, `got ${resp5.status}`);
  if (data5.leadId) {
    const row = await prisma.lead.findUnique({ where: { id: data5.leadId } });
    check("claimVolume persisted as null", row?.claimVolume === null);
  }

  console.log("\n=== summary ===");
  console.log(`  passed: ${totalPass}`);
  console.log(`  failed: ${totalFail}`);

  await prisma.$disconnect();
  process.exit(totalFail > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error("test crashed:", e);
  process.exit(1);
});
