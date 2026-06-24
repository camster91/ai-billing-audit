// Browser-equivalent smoke test for the /contact form (t_fa2149e1).
//
// We can't drive an actual browser here (no playwright/puppeteer in the
// project), but the form is a thin client wrapper around fetch(/api/leads).
// So this test simulates the browser by:
//   1. Loading the /contact page through the dev server to confirm it
//      returns 200 and renders the form fields (we grep the HTML for
//      the field labels).
//   2. POSTing a valid payload to /api/leads and asserting the 200 +
//      leadId response shape.
//   3. Verifying the row landed in the DB with exactly the 5 fields
//      the spec mandates (no IP, no UA, no PII beyond the input).
//   4. POSTing a disposable-email address and asserting 400 +
//      disposable_email, then checking the DB row count is unchanged.
//   5. POSTing a malformed payload and asserting 400 + invalid_input.
//
// Run: `pnpm test:contact-form` (or directly with node --import tsx
// --test). Requires the dev server to be running on PORT (default 3000).
// The script reads PORT from env, defaulting to 3000.
//
// The dev server is *not* started by this test — a separate process
// owns it (the worker that wrote this file was the one that started
// it). If the server isn't running, the first assertion fails and the
// suite exits non-zero.

import { test } from "node:test";
import assert from "node:assert/strict";
import { prisma } from "../src/lib/prisma";

const PORT = Number(process.env.PORT ?? 3000);
const BASE = `http://127.0.0.1:${PORT}`;

// A unique tag so re-runs don't collide with rows left by prior tests
// or real users submitting the form during a dev session.
const TAG = `smoke-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

test("contact form: GET /contact renders the form", async () => {
  const res = await fetch(`${BASE}/contact`);
  assert.equal(res.status, 200, "GET /contact should return 200");
  const html = await res.text();
  for (const label of [
    "Your name",
    "Clinic name",
    "Work email",
    "Monthly claim volume",
    "Current billing setup",
    "Talk to sales",
  ]) {
    assert.ok(
      html.includes(label),
      `expected /contact HTML to contain "${label}"`,
    );
  }
});

test("contact form: valid POST returns 200 + leadId, row in DB", async () => {
  const before = await prisma.lead.count();

  const payload = {
    name: `Smoke Test ${TAG}`,
    clinicName: `Smoke Clinic ${TAG}`,
    email: `smoke-${TAG}@clinic.test`,
    claimVolume: 1234,
    billingSetup: "hybrid" as const,
  };

  const res = await fetch(`${BASE}/api/leads`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  assert.equal(res.status, 200, "valid POST should return 200");
  const body = (await res.json()) as { ok?: boolean; leadId?: string };
  assert.equal(body.ok, true);
  assert.ok(typeof body.leadId === "string" && body.leadId.length > 0);

  // Row landed with exactly the 5 fields we submitted.
  const row = await prisma.lead.findUnique({ where: { id: body.leadId! } });
  assert.ok(row, "row should exist in DB");
  assert.equal(row!.name, payload.name);
  assert.equal(row!.clinicName, payload.clinicName);
  assert.equal(row!.email, payload.email.toLowerCase());
  assert.equal(row!.claimVolume, 1234);
  assert.equal(row!.billingSetup, "hybrid");
  // No IP / UA / referrer columns leaked into the row.
  assert.ok(!("ip" in row!));
  assert.ok(!("userAgent" in row!));
  assert.ok(!("referrer" in row!));

  // Row count grew by exactly 1.
  const after = await prisma.lead.count();
  assert.equal(after, before + 1);
});

test("contact form: disposable email rejected, no row created", async () => {
  const before = await prisma.lead.count();

  const res = await fetch(`${BASE}/api/leads`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      name: `Spam ${TAG}`,
      clinicName: `Spam Co ${TAG}`,
      email: "throwaway@mailinator.com",
      claimVolume: 1,
      billingSetup: "in_house",
    }),
  });
  assert.equal(res.status, 400);
  const body = (await res.json()) as { error?: string };
  assert.equal(body.error, "disposable_email");

  const after = await prisma.lead.count();
  assert.equal(after, before, "disposable email must not insert a row");
});

test("contact form: invalid payload returns 400 + invalid_input", async () => {
  const res = await fetch(`${BASE}/api/leads`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name: "only" }),
  });
  assert.equal(res.status, 400);
  const body = (await res.json()) as {
    error?: string;
    details?: { fieldErrors?: Record<string, string[]> };
  };
  assert.equal(body.error, "invalid_input");
  // Zod should have flagged the missing required fields.
  const fieldErrs = body.details?.fieldErrors ?? {};
  assert.ok(fieldErrs.clinicName, "clinicName should be flagged");
  assert.ok(fieldErrs.email, "email should be flagged");
  assert.ok(fieldErrs.billingSetup, "billingSetup should be flagged");
});

test("contact form: home page exposes Talk to sales CTA", async () => {
  const res = await fetch(`${BASE}/`);
  assert.equal(res.status, 200, "GET / should return 200 (public)");
  const html = await res.text();
  assert.ok(html.includes("Talk to sales"), "home should have Talk to sales CTA");
  assert.ok(html.includes('href="/contact"'), "home should link to /contact");
});

test("contact form: marketing nav includes /contact", async () => {
  const res = await fetch(`${BASE}/pricing`);
  const html = await res.text();
  assert.ok(
    html.includes('href="/contact"'),
    "pricing page nav should link to /contact",
  );
});
