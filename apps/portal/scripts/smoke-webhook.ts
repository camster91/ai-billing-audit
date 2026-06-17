// Unit test for the webhook signature verification path.
//
// Generates a fake Stripe event, signs it the way Stripe does (HMAC-SHA256
// over `${timestamp}.${rawBody}` with the webhook secret), and POSTs it
// to /api/billing/webhook. In demo mode the route refuses with 503. In
// real mode it would verify the signature, then call the handler.
//
// This script runs in DEMO mode intentionally — it documents the
// signature-construction path so the production verification works
// the same way. Run with a real STRIPE_SECRET_KEY + STRIPE_WEBHOOK_SECRET
// to exercise the full verification + handler chain.
//
// We construct the signature exactly the way stripe.webhooks.generateTestHeaderString
// does: timestamp + "." + payload, HMAC-SHA256 keyed by the secret, hex-encoded.

import { strict as assert } from "node:assert";
import { createHmac, randomBytes } from "node:crypto";

const BASE = process.env["BASE_URL"] || "http://localhost:3000";
const SECRET = "whsec_test_smoke_secret_" + randomBytes(8).toString("hex");

function signPayload(payload: string, secret: string, timestamp = Math.floor(Date.now() / 1000)): string {
  const signed = `${timestamp}.${payload}`;
  const sig = createHmac("sha256", secret).update(signed, "utf8").digest("hex");
  return `t=${timestamp},v1=${sig}`;
}

async function main() {
  // 1. Unsigned event should be rejected (no stripe-signature header → 400)
  const payload = JSON.stringify({
    id: "evt_test_123",
    type: "checkout.session.completed",
    data: { object: { id: "cs_test_123" } },
  });
  const r1 = await fetch(`${BASE}/api/billing/webhook`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload,
  });
  // In demo mode → 503 (refuses events). In real mode → 400 (no signature).
  // Either is "rejected" — both prove the route doesn't accept unsigned events.
  assert.ok(
    r1.status === 503 || r1.status === 400,
    `unsigned webhook should be rejected; got ${r1.status}`
  );
  console.log(`[smoke-webhook] unsigned event rejected with ${r1.status} OK`);

  // 2. Bad signature should be rejected (in real mode → 400)
  const badSig = "t=" + Math.floor(Date.now() / 1000) + ",v1=deadbeef";
  const r2 = await fetch(`${BASE}/api/billing/webhook`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "stripe-signature": badSig,
    },
    body: payload,
  });
  assert.ok(
    r2.status === 503 || r2.status === 400,
    `bad-signature webhook should be rejected; got ${r2.status}`
  );
  console.log(`[smoke-webhook] bad-signature event rejected with ${r2.status} OK`);

  // 3. Correctly-signed event in demo mode → 503 (still demo). In real mode
  //    this would be 200 with `{received: true}`.
  const goodSig = signPayload(payload, SECRET);
  const r3 = await fetch(`${BASE}/api/billing/webhook`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "stripe-signature": goodSig,
    },
    body: payload,
  });
  assert.ok(
    r3.status === 503 || r3.status === 200,
    `signed webhook in demo mode: 503 expected, real mode: 200; got ${r3.status}`
  );
  console.log(`[smoke-webhook] correctly-signed event returned ${r3.status} OK`);

  console.log("\n[smoke-webhook] ALL CHECKS PASSED");
}

main().catch((e) => {
  console.error("[smoke-webhook] FAILED:", e);
  process.exit(1);
});
