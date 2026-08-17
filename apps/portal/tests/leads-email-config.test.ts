import assert from "node:assert/strict";
import { test } from "node:test";
import { resolveLeadsResendKey } from "../src/lib/leads-email";

test("lead notifications reuse the configured Auth.js Resend key", () => {
  assert.equal(
    resolveLeadsResendKey({ AUTH_RESEND_KEY: "auth-resend-key" }),
    "auth-resend-key",
  );
});

test("a dedicated lead key takes precedence over the Auth.js key", () => {
  assert.equal(
    resolveLeadsResendKey({
      AUTH_RESEND_KEY: "auth-resend-key",
      RESEND_API_KEY: "lead-resend-key",
    }),
    "lead-resend-key",
  );
});
