// Unit tests for the portal /readyz endpoint (issue #65).
//
// The route is exercised by stubbing process.env + prisma and
// calling GET() directly. No HTTP server required; node:test is
// the test runner (matches the rest of apps/portal/tests).

import assert from "node:assert/strict";
import { test } from "node:test";
import { GET } from "../src/app/readyz/route";

const SAVED_ENV = { ...process.env };

function restoreEnv(): void {
  for (const k of Object.keys(process.env)) delete (process.env as Record<string, unknown>)[k];
  for (const [k, v] of Object.entries(SAVED_ENV)) {
    (process.env as Record<string, unknown>)[k] = v;
  }
}

test("returns 503 with per-check reasons when env is empty", async () => {
  restoreEnv();
  delete process.env.DATABASE_URL;
  delete process.env.AUTH_SECRET;
  delete process.env.RESEND_API_KEY;
  delete process.env.AUTH_RESEND_KEY;
  delete process.env.LEADS_SLACK_WEBHOOK_URL;

  // The database probe will fail because there's no real DB in
  // node:test. We only assert the env-driven checks.
  const res = await GET();
  const body = (await res.json()) as {
    status: string;
    service: string;
    checks: Record<string, { ok: boolean; reason?: string }>;
  };
  assert.equal(body.service, "portal");
  assert.equal(res.status, 503);
  assert.equal(body.checks.database_url_configured.ok, false);
  assert.equal(body.checks.database_url_configured.reason, "missing");
  assert.equal(body.checks.auth_secret_configured.ok, false);
  assert.equal(body.checks.auth_resend_key_configured.ok, false);
});

test("treats a too-short AUTH_SECRET as not configured", async () => {
  restoreEnv();
  process.env.DATABASE_URL = "postgresql://placeholder:placeholder@127.0.0.1:5432/db";
  process.env.AUTH_SECRET = "short";
  process.env.AUTH_RESEND_KEY = "x".repeat(40);
  process.env.LEADS_SLACK_WEBHOOK_URL = "***";

  const res = await GET();
  const body = (await res.json()) as {
    checks: Record<string, { ok: boolean; reason?: string }>;
  };
  assert.equal(body.checks.auth_secret_configured.ok, false);
  assert.equal(body.checks.auth_secret_configured.reason, "too_short");
});

test("accepts AUTH_SECRET at the documented minimum (32 bytes)", async () => {
  restoreEnv();
  process.env.DATABASE_URL = "postgresql://placeholder:placeholder@127.0.0.1:5432/db";
  process.env.AUTH_SECRET = "a".repeat(32);
  process.env.AUTH_RESEND_KEY = "b".repeat(40);

  const res = await GET();
  const body = (await res.json()) as {
    checks: Record<string, { ok: boolean; reason?: string }>;
  };
  assert.equal(body.checks.auth_secret_configured.ok, true);
});

test("treats a too-short RESEND key as not configured", async () => {
  restoreEnv();
  process.env.DATABASE_URL = "postgresql://placeholder:placeholder@127.0.0.1:5432/db";
  process.env.AUTH_SECRET = "a".repeat(40);
  process.env.AUTH_RESEND_KEY = "tiny";

  const res = await GET();
  const body = (await res.json()) as {
    checks: Record<string, { ok: boolean; reason?: string }>;
  };
  assert.equal(body.checks.auth_resend_key_configured.ok, false);
  assert.equal(body.checks.auth_resend_key_configured.reason, "too_short");
});

test("does not treat the leads Resend key as authentication-ready", async () => {
  restoreEnv();
  process.env.DATABASE_URL = "postgresql://placeholder:placeholder@127.0.0.1:5432/db";
  process.env.AUTH_SECRET = "a".repeat(40);
  process.env.RESEND_API_KEY = "l".repeat(40);
  delete process.env.AUTH_RESEND_KEY;

  const res = await GET();
  const body = (await res.json()) as {
    checks: Record<string, { ok: boolean; reason?: string }>;
  };
  assert.equal(body.checks.leads_resend_key_configured.ok, true);
  assert.equal(body.checks.auth_resend_key_configured.ok, false);
  assert.equal(body.checks.auth_resend_key_configured.reason, "missing");
});

test("does not echo any secret value in the JSON body", async () => {
  restoreEnv();
  process.env.DATABASE_URL = "postgresql://placeholder:placeholder@127.0.0.1:5432/db";
  process.env.AUTH_SECRET = "secret-value-32-bytes-AAAAAAAAA";
  process.env.AUTH_RESEND_KEY = "resend-value-40-bytes-AAAAAAAAAAA";
  process.env.LEADS_SLACK_WEBHOOK_URL = "https://hooks.slack.test/AAA";

  const res = await GET();
  const text = JSON.stringify(await res.json());
  assert.ok(!text.includes("secret-value-32-bytes"), "AUTH_SECRET leaked");
  assert.ok(!text.includes("resend-value-40-bytes"), "RESEND key leaked");
  assert.ok(
    !text.includes("hooks.slack.test/AAA"),
    "slack webhook URL leaked",
  );
});

test("Slack mock mode is treated as ready (no webhook configured)", async () => {
  restoreEnv();
  process.env.DATABASE_URL = "postgresql://placeholder:placeholder@127.0.0.1:5432/db";
  process.env.AUTH_SECRET = "a".repeat(40);
  process.env.AUTH_RESEND_KEY = "b".repeat(40);
  delete process.env.LEADS_SLACK_WEBHOOK_URL;

  const res = await GET();
  const body = (await res.json()) as {
    checks: Record<string, { ok: boolean; reason?: string }>;
  };
  // The endpoint merges the slack check into the response but
  // does not fail the overall readiness when slack is unset (the
  // lead-funnel is allowed to operate in mock mode).
  assert.equal(body.checks.slack_webhook_configured.ok, true);
});
