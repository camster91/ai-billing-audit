// Unit tests for the privacy-conscious analytics event schema
// (issue #75). Verifies:
//
//   1. Allowed event names are the documented four.
//   2. Allowed properties per event match the docs.
//   3. Forbidden keys are rejected (PII guard).
//   4. The UTM helpers round-trip through sessionStorage and never
//      carry non-string values.
//   5. claimVolumeBucket produces the documented coarse bucket
//      string for every value in the 0..100000 slider range.
//   6. truncateText caps at 80 chars and preserves the head.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ALLOWED_EVENTS,
  ALLOWED_PROPS,
  EMPTY_UTM,
  FORBIDDEN_KEYS,
  UTM_KEYS,
  assertSafePayload,
  claimVolumeBucket,
  readUTMFromURL,
  readStoredUTM,
  truncateText,
} from "../src/lib/analytics-events";

test("ALLOWED_EVENTS contains exactly the four documented events", () => {
  assert.deepEqual(
    [...ALLOWED_EVENTS].sort(),
    [
      "contact_start",
      "contact_submit_failure",
      "contact_submit_success",
      "cta_click",
    ].sort(),
  );
});

test("FORBIDDEN_KEYS covers every PII key the contact form holds", () => {
  for (const key of [
    "name",
    "clinicName",
    "email",
    "message",
    "patient",
    "patientHash",
    "phone",
    "claimVolume",
  ]) {
    assert.ok(
      FORBIDDEN_KEYS.has(key),
      `expected ${key} to be in FORBIDDEN_KEYS`,
    );
  }
});

test("assertSafePayload accepts a clean cta_click payload", () => {
  const out = assertSafePayload("cta_click", {
    cta_id: "home_hero_contact",
    page_path: "/",
    href: "/contact",
    text: "Start a conversation",
    utm_source: "newsletter",
  });
  assert.equal(out.cta_id, "home_hero_contact");
  assert.equal(out.utm_source, "newsletter");
});

test("assertSafePayload accepts a clean contact_submit_success payload", () => {
  const out = assertSafePayload("contact_submit_success", {
    claim_volume_bucket: "500-2000",
    billing_setup: "in_house",
    page_path: "/contact",
  });
  assert.equal(out.claim_volume_bucket, "500-2000");
  assert.equal(out.billing_setup, "in_house");
});

test("assertSafePayload rejects unknown event names", () => {
  assert.throws(
    () => assertSafePayload("submit_form", {}),
    /unknown analytics event/,
  );
});

test("assertSafePayload rejects PII keys", () => {
  for (const key of ["name", "email", "clinicName", "claimVolume", "phone"]) {
    assert.throws(
      () =>
        assertSafePayload("cta_click", {
          cta_id: "x",
          page_path: "/",
          [key]: "leaked",
        }),
      /forbidden analytics key|property .* not allowed/,
      `expected ${key} to be rejected`,
    );
  }
});

test("assertSafePayload rejects properties not in the allow-list", () => {
  assert.throws(
    () =>
      assertSafePayload("contact_submit_success", {
        claim_volume_bucket: "500-2000",
        billing_setup: "in_house",
        page_path: "/contact",
        patient_hash: "h1",
      }),
    /property patient_hash not allowed/,
  );
});

test("assertSafePayload rejects object values (PII-leak guard)", () => {
  assert.throws(
    () =>
      assertSafePayload("cta_click", {
        cta_id: "x",
        page_path: "/",
        text: { nested: "value" },
      }),
    /object value not allowed/,
  );
});

test("assertSafePayload drops null and undefined values silently", () => {
  const out = assertSafePayload("contact_start", {
    page_path: "/contact",
    utm_source: undefined,
    utm_medium: null,
  });
  assert.deepEqual(out, { page_path: "/contact" });
});

test("assertSafePayload drops non-finite numbers (NaN, Infinity)", () => {
  // utm_source is in the allow-list; NaN/Infinity as the value should
  // be dropped silently without the function throwing on the
  // allow-list check.
  const out = assertSafePayload("contact_start", {
    page_path: "/contact",
    utm_source: Number.NaN as unknown as string,
    utm_medium: Number.POSITIVE_INFINITY as unknown as string,
  });
  assert.equal("utm_source" in out, false);
  assert.equal("utm_medium" in out, false);
  assert.equal(out.page_path, "/contact");
});

test("ALLOWED_PROPS does not overlap with FORBIDDEN_KEYS", () => {
  for (const [, props] of Object.entries(ALLOWED_PROPS)) {
    for (const p of props) {
      assert.ok(
        !FORBIDDEN_KEYS.has(p),
        `ALLOWED_PROPS contains a forbidden key: ${p}`,
      );
    }
  }
});

test("claimVolumeBucket returns the documented buckets across the slider range", () => {
  assert.equal(claimVolumeBucket(0), "0-100");
  assert.equal(claimVolumeBucket(50), "0-100");
  assert.equal(claimVolumeBucket(100), "0-100");
  assert.equal(claimVolumeBucket(101), "100-500");
  assert.equal(claimVolumeBucket(500), "100-500");
  assert.equal(claimVolumeBucket(501), "500-2000");
  assert.equal(claimVolumeBucket(2000), "500-2000");
  assert.equal(claimVolumeBucket(2001), "2000-10000");
  assert.equal(claimVolumeBucket(10000), "2000-10000");
  assert.equal(claimVolumeBucket(10001), "10000-100000");
  assert.equal(claimVolumeBucket(100000), "10000-100000");
});

test("truncateText caps at 80 chars and preserves the head", () => {
  const short = "Hello world";
  assert.equal(truncateText(short), short);

  const long = "x".repeat(200);
  const out = truncateText(long);
  assert.equal(out.length, 80);
  assert.equal(out, "x".repeat(80));

  const withSpaces = "   padded   ";
  assert.equal(truncateText(withSpaces), "padded");
});

test("readUTMFromURL parses and persists utm_* params", () => {
  // Simulate a minimal window for the helper.
  const store = new Map<string, string>();
  const w = {
    location: { href: "https://zorva.ashbi.ca/?utm_source=newsletter&utm_medium=email&utm_campaign=launch" },
    sessionStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    },
  };
  const g = globalThis as { window?: unknown };
  const prev = g.window;
  g.window = w;
  try {
    const out = readUTMFromURL();
    assert.equal(out.utm_source, "newsletter");
    assert.equal(out.utm_medium, "email");
    assert.equal(out.utm_campaign, "launch");
    const stored = readStoredUTM();
    assert.equal(stored.utm_source, "newsletter");
  } finally {
    g.window = prev;
  }
});

test("readUTMFromURL returns EMPTY_UTM when no params are present", () => {
  const w = {
    location: { href: "https://zorva.ashbi.ca/" },
    sessionStorage: {
      getItem: () => null,
      setItem: () => {},
    },
  };
  const g = globalThis as { window?: unknown };
  const prev = g.window;
  g.window = w;
  try {
    assert.deepEqual(readUTMFromURL(), EMPTY_UTM);
  } finally {
    g.window = prev;
  }
});

test("readUTMFromURL hard-caps each UTM value at 100 chars", () => {
  const longValue = "a".repeat(500);
  const w = {
    location: {
      href: `https://zorva.ashbi.ca/?utm_source=${longValue}&utm_medium=${longValue}`,
    },
    sessionStorage: {
      getItem: () => null,
      setItem: () => {},
    },
  };
  const g = globalThis as { window?: unknown };
  const prev = g.window;
  g.window = w;
  try {
    const out = readUTMFromURL();
    assert.equal(out.utm_source?.length, 100);
    assert.equal(out.utm_medium?.length, 100);
  } finally {
    g.window = prev;
  }
});

test("UTM_KEYS are the three documented campaign parameters", () => {
  assert.deepEqual([...UTM_KEYS], ["utm_source", "utm_medium", "utm_campaign"]);
});
