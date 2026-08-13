import assert from "node:assert/strict";
import { test } from "node:test";
import { takeLeadSubmission } from "../src/lib/public-rate-limit";

test("lead submissions are limited per client in a ten-minute window", () => {
  const now = Date.UTC(2026, 7, 13, 17, 45, 0);
  const request = new Request("https://zorva.ashbi.ca/api/leads", {
    headers: { "x-real-ip": "203.0.113.55" },
  });

  for (let attempt = 0; attempt < 5; attempt += 1) {
    const result = takeLeadSubmission(request, now);
    assert.equal(result.allowed, true);
  }

  const blocked = takeLeadSubmission(request, now);
  assert.equal(blocked.allowed, false);
  if (!blocked.allowed) assert.equal(blocked.retryAfterSeconds, 600);
});

test("lead submission window resets without relying on client input", () => {
  const now = Date.UTC(2026, 7, 13, 17, 45, 0);
  const request = new Request("https://zorva.ashbi.ca/api/leads", {
    headers: { "x-real-ip": "203.0.113.56" },
  });

  for (let attempt = 0; attempt < 5; attempt += 1) takeLeadSubmission(request, now);

  const reset = takeLeadSubmission(request, now + 10 * 60 * 1000);
  assert.equal(reset.allowed, true);
});
