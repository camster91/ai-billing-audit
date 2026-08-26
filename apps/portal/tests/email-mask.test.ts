// Unit tests for the email-mask helper used by /verify-request
// (issue #47). Verifies:
//
//   1. maskEmail hides the local part and most of the domain
//   2. The full address is never returned
//   3. Invalid input returns "" (no PII leakage)
//   4. safeReturnUrl rejects external / protocol-relative / scheme
//      URLs and falls back to a same-origin path

import assert from "node:assert/strict";
import { test } from "node:test";
import { maskEmail, safeReturnUrl } from "../src/lib/email-mask";
import {
  openPendingMagicLink,
  sealPendingMagicLink,
  secondsUntilMagicLinkResend,
} from "../src/lib/pending-magic-link";

test("maskEmail hides the local part beyond the first char", () => {
  const out = maskEmail("jane.smith@clinic.com");
  assert.notEqual(out, "jane.smith@clinic.com");
  // The local part should start with the first char and a bullet,
  // never include the full local.
  assert.ok(/^j•/.test(out) || /^j…/.test(out) || /^j\.\.\./.test(out),
    `expected local to be masked, got ${out}`);
  assert.ok(!out.includes("jane"), `masked output must not contain the full local: ${out}`);
  assert.ok(!out.includes("smith"), `masked output must not contain the full local: ${out}`);
});

test("maskEmail hides the domain label beyond the first char", () => {
  const out = maskEmail("a@example.org");
  assert.notEqual(out, "a@example.org");
  assert.ok(!out.includes("xample"), `masked output must not contain the full domain label: ${out}`);
  // TLD is preserved.
  assert.ok(out.endsWith(".org"), `expected TLD preserved, got ${out}`);
});

test("maskEmail never returns the full address for medium+ addresses", () => {
  // The very-short / single-char case is covered by a dedicated
  // test ("handles very short addresses (no-op for too-short)")
  // where the helper intentionally returns the original because
  // masking would only hide the @.
  for (const e of [
    "alice@company.com",
    "bob.jones@very-long-domain.example.com",
    "user.name+tag@sub.example.org",
  ]) {
    const out = maskEmail(e);
    assert.notEqual(out, e, `maskEmail must not return the full address for ${e}`);
  }
});

test("maskEmail returns empty string for empty / malformed input", () => {
  assert.equal(maskEmail(""), "");
  assert.equal(maskEmail("   "), "");
  assert.equal(maskEmail("noatsign.com"), "");
  assert.equal(maskEmail("@nope.com"), "");
  assert.equal(maskEmail("nope@"), "");
  assert.equal(maskEmail("nope@nodot"), "");
  // Length cap.
  assert.equal(maskEmail("a".repeat(400) + "@x.com"), "");
});

test("maskEmail returns a string parseable as containing '@' and a TLD", () => {
  for (const e of [
    "alice@company.com",
    "user.name@sub.example.org",
    "x@y.io",
  ]) {
    const out = maskEmail(e);
    assert.ok(out.includes("@"), `expected @ in ${out}`);
    assert.ok(/\.[a-z]{2,}$/i.test(out), `expected TLD in ${out}`);
  }
});

test("maskEmail handles localVisible option", () => {
  const out = maskEmail("jane@clinic.com", { localVisible: 3, domainVisible: 1 });
  // 3 chars visible, then bullets
  assert.ok(/^jan•/.test(out) || /^jan…/.test(out),
    `expected first 3 chars visible, got ${out}`);
});

test("maskEmail handles very short addresses (no-op for too-short)", () => {
  // A single-char local + single-char domain label is too short to
  // mask usefully; the helper returns the original.
  const out = maskEmail("a@b.com");
  assert.equal(out, "a@b.com");
});

test("safeReturnUrl accepts same-origin paths", () => {
  assert.equal(safeReturnUrl("/dashboard"), "/dashboard");
  assert.equal(safeReturnUrl("/encounters/abc"), "/encounters/abc");
  assert.equal(safeReturnUrl("/dashboard?tab=open"), "/dashboard?tab=open");
});

test("safeReturnUrl rejects external / protocol-relative / scheme URLs", () => {
  assert.equal(safeReturnUrl("https://evil.example.com"), "/dashboard");
  assert.equal(safeReturnUrl("//evil.example.com"), "/dashboard");
  assert.equal(safeReturnUrl("javascript:alert(1)"), "/dashboard");
  assert.equal(safeReturnUrl("data:text/html,x"), "/dashboard");
  assert.equal(safeReturnUrl("/\\evil.example"), "/dashboard");
  assert.equal(safeReturnUrl("/%5Cevil.example"), "/dashboard");
  assert.equal(safeReturnUrl(""), "/dashboard");
  assert.equal(safeReturnUrl(undefined), "/dashboard");
});

test("safeReturnUrl uses the supplied fallback", () => {
  assert.equal(safeReturnUrl(undefined, "/encounters"), "/encounters");
  assert.equal(safeReturnUrl("https://evil.example.com", "/encounters"), "/encounters");
});

test("pending magic-link state is encrypted and rejects tampering", () => {
  const previous = process.env.AUTH_SECRET;
  process.env.AUTH_SECRET = "test-auth-secret-with-enough-entropy";
  try {
    const state = {
      email: "person@clinic.example",
      from: "/dashboard",
      sentAt: 1_700_000_000_000,
    };
    const sealed = sealPendingMagicLink(state);
    assert.ok(!sealed.includes(state.email));
    assert.deepEqual(openPendingMagicLink(sealed), state);
    assert.equal(secondsUntilMagicLinkResend(state, state.sentAt + 30_000), 30);
    assert.equal(secondsUntilMagicLinkResend(state, state.sentAt + 60_000), 0);

    const tampered = sealed.slice(0, -1) + (sealed.endsWith("a") ? "b" : "a");
    assert.equal(openPendingMagicLink(tampered), null);
  } finally {
    if (previous === undefined) delete process.env.AUTH_SECRET;
    else process.env.AUTH_SECRET = previous;
  }
});
