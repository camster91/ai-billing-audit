// Smoke test for the pricing → checkout → webhook → onboarding flow.
//
// Runs against a live dev server. Assumes:
//   1. The Next.js dev server is up at $BASE_URL (default http://localhost:3000).
//   2. The .env has STRIPE_SECRET_KEY=*** (demo mode).
//   3. The Prisma DB has been pushed.
//
// What this verifies:
//   - GET /api/billing/tiers returns the 3 expected tiers with correct prices
//   - POST /api/billing/checkout with each (tier, currency) pair returns
//     a demo session + redirect URL pointing at /portal/onboarding
//   - POST /api/billing/webhook refuses events in demo mode (503)
//   - GET /portal/onboarding with a demo session_id renders
//   - GET /pricing renders 3 tier cards with 3 prices each
//
// What this does NOT verify (requires real test keys + Stripe CLI):
//   - The actual Stripe Checkout Session flow with test card 4242 4242 4242 4242
//   - A real webhook signature being accepted by /api/billing/webhook
//   - The Tenant row being created in the DB from a real checkout
//
// Out-of-scope per task body: tax, coupons, proration.

import { strict as assert } from "node:assert";

const BASE = process.env["BASE_URL"] || "http://localhost:3000";

interface CheckoutResp {
  sessionId: string;
  url: string;
  demo: boolean;
}

interface Tier {
  id: string;
  name: string;
  auditCap: number;
  priceCAD: number;
  priceUSD: number;
  stripePriceIdCAD: string | null;
  stripePriceIdUSD: string | null;
  features: string[];
}

interface TiersResp {
  currency: { primary: string; secondary: string };
  tiers: Tier[];
  compliance: { framework: string; specReference: string };
}

async function getTiers(): Promise<TiersResp> {
  const r = await fetch(`${BASE}/api/billing/tiers`);
  assert.equal(r.status, 200, `GET /api/billing/tiers returned ${r.status}`);
  return (await r.json()) as TiersResp;
}

async function postCheckout(
  tierId: string,
  currency: string
): Promise<CheckoutResp> {
  const r = await fetch(`${BASE}/api/billing/checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tierId, currency }),
  });
  const body = (await r.json()) as CheckoutResp & { error?: string };
  assert.equal(r.status, 200, `checkout(${tierId},${currency}) status=${r.status}: ${body.error ?? ""}`);
  assert.ok(body.sessionId, `checkout(${tierId},${currency}) returned no sessionId`);
  assert.ok(body.url, `checkout(${tierId},${currency}) returned no url`);
  assert.equal(body.demo, true, `expected demo mode in this test env`);
  return body;
}

async function postWebhookWithoutSig(): Promise<number> {
  const r = await fetch(`${BASE}/api/billing/webhook`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type: "checkout.session.completed" }),
  });
  return r.status;
}

async function getPricingHtml(): Promise<string> {
  const r = await fetch(`${BASE}/pricing`);
  assert.equal(r.status, 200, `GET /pricing status=${r.status}`);
  return await r.text();
}

async function getOnboardingHtml(sessionId: string): Promise<string> {
  const url = `${BASE}/portal/onboarding?session_id=${encodeURIComponent(sessionId)}`;
  const r = await fetch(url);
  assert.equal(r.status, 200, `GET ${url} status=${r.status}`);
  return await r.text();
}

async function main() {
  console.log(`[smoke] BASE_URL=${BASE}`);

  // 1. /api/billing/tiers
  const tiers = await getTiers();
  assert.equal(tiers.tiers.length, 3, `expected 3 tiers, got ${tiers.tiers.length}`);
  const small = tiers.tiers.find((t) => t.id === "small");
  const mid = tiers.tiers.find((t) => t.id === "mid");
  const large = tiers.tiers.find((t) => t.id === "large");
  assert.ok(small && mid && large, "missing tier");
  assert.equal(small.priceCAD, 499, `small priceCAD: ${small.priceCAD}`);
  assert.equal(mid.priceCAD, 1_499, `mid priceCAD: ${mid.priceCAD}`);
  assert.equal(large.priceCAD, 2_999, `large priceCAD: ${large.priceCAD}`);
  assert.equal(small.priceUSD, 369, `small priceUSD: ${small.priceUSD}`);
  assert.equal(small.auditCap, 500, `small auditCap: ${small.auditCap}`);
  assert.equal(mid.auditCap, 2_000, `mid auditCap: ${mid.auditCap}`);
  assert.equal(large.auditCap, 5_000, `large auditCap: ${large.auditCap}`);
  assert.equal(tiers.currency.primary, "CAD", `primary: ${tiers.currency.primary}`);
  assert.equal(tiers.currency.secondary, "USD", `secondary: ${tiers.currency.secondary}`);
  assert.equal(tiers.compliance.specReference, "Zorva §11", `spec: ${tiers.compliance.specReference}`);
  console.log("[smoke] /api/billing/tiers OK — 3 tiers, correct prices + caps");

  // 2. /api/billing/checkout (3 tiers × 2 currencies = 6 calls)
  for (const tierId of ["small", "mid", "large"]) {
    for (const currency of ["CAD", "USD"]) {
      const c = await postCheckout(tierId, currency);
      assert.match(c.url, /\/portal\/onboarding/, `checkout url should point at /portal/onboarding, got: ${c.url}`);
      assert.match(c.url, /session_id=/, `checkout url should include session_id, got: ${c.url}`);
      console.log(`[smoke] checkout(${tierId},${currency}) OK — sessionId=${c.sessionId.slice(0, 16)}…`);
    }
  }

  // 3. /api/billing/webhook refuses in demo mode
  const whStatus = await postWebhookWithoutSig();
  assert.equal(whStatus, 503, `webhook in demo mode should be 503, got ${whStatus}`);
  console.log(`[smoke] /api/billing/webhook refuses events in demo mode (503 OK)`);

  // 4. /pricing renders 3 cards
  const html = await getPricingHtml();
  // Each tier card has its name + the two price lines.
  for (const name of ["Small practice", "Mid clinic", "Large practice"]) {
    assert.ok(html.includes(name), `/pricing missing tier name "${name}"`);
  }
  for (const amount of ["CA$499", "CA$1,499", "CA$2,999"]) {
    assert.ok(html.includes(amount), `/pricing missing CAD amount "${amount}"`);
  }
  for (const amount of ["$369", "$1,109", "$2,219"]) {
    assert.ok(html.includes(amount), `/pricing missing USD amount "${amount}"`);
  }
  assert.ok(html.includes("Zorva §11"), "/pricing missing Zorva §11 reference");
  // The "Most clinics" badge is rendered via a CSS ::before pseudo-element
  // (same as t_f00717ff's static pricing.html), so it lives in the
  // stylesheet, not the markup. Verify the recommended tier class
  // is applied to the mid-clinic card instead.
  assert.ok(
    /class="[^"]*recommended[^"]*"[\s\S]*?Mid clinic[\s\S]*?<\/article>/.test(html),
    "/pricing missing 'recommended' class on Mid clinic card"
  );
  console.log("[smoke] /pricing OK — 3 tier cards, CAD + USD amounts, compliance block");

  // 5. /portal/onboarding with a demo session renders without error
  const demoSession = (await postCheckout("mid", "CAD")).sessionId;
  const onboardingHtml = await getOnboardingHtml(demoSession);
  assert.ok(onboardingHtml.includes("Demo session"), "onboarding missing 'Demo session' badge");
  console.log("[smoke] /portal/onboarding OK — renders for demo session_id");

  console.log("\n[smoke] ALL CHECKS PASSED");
}

main().catch((e) => {
  console.error("[smoke] FAILED:", e);
  process.exit(1);
});
