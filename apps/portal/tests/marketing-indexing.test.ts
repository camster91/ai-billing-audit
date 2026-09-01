import assert from "node:assert/strict";
import { test } from "node:test";
import { NextRequest } from "next/server";
import middleware from "../src/middleware";
import robots from "../src/app/robots";
import sitemap from "../src/app/sitemap";
import {
  DEFERRED_MARKETING_PREFIXES,
  REVIEWED_MARKETING_ROUTES,
} from "../src/lib/marketing-indexing";
import { publicMarketingMetadata } from "../src/lib/public-marketing-metadata";

test("public metadata fallback stays evidence-conscious", () => {
  const rendered = JSON.stringify(publicMarketingMetadata);

  assert.match(rendered, /human-reviewed pre-submit workflow/i);
  assert.doesNotMatch(rendered, /revenue your billers are leaving/i);
  assert.doesNotMatch(rendered, /reads every Alberta claim/i);
  assert.doesNotMatch(rendered, /underbilled modifiers/i);
  assert.doesNotMatch(rendered, /region-pinned data/i);
});

test("marketing sitemap exposes only reviewed core routes", () => {
  assert.deepEqual(
    sitemap().map((entry) => entry.url),
    REVIEWED_MARKETING_ROUTES.map(
      (route) => `https://zorva.ashbi.ca${route}`,
    ),
  );
});

test("robots disallows protected routes but leaves deferred routes crawlable", () => {
  const rules = robots().rules;
  assert.ok(Array.isArray(rules));
  const disallow = rules[0]?.disallow;
  assert.ok(Array.isArray(disallow));
  for (const route of DEFERRED_MARKETING_PREFIXES) {
    assert.ok(!disallow.includes(route), `${route} must remain crawlable`);
  }
  assert.ok(disallow.includes("/team/"));
  assert.ok(disallow.includes("/onboarding/"));
  assert.ok(disallow.includes("/hq/"));
});

test("all deferred marketing responses redirect with noindex", () => {
  for (const route of DEFERRED_MARKETING_PREFIXES) {
    const response = middleware(
      new NextRequest(`https://zorva.ashbi.ca${route}`),
    );
    assert.equal(
      response.headers.get("X-Robots-Tag"),
      "noindex, nofollow",
      `${route} must emit X-Robots-Tag`,
    );
    assert.equal(response.status, 307, `${route} must redirect temporarily`);
    assert.equal(
      new URL(response.headers.get("location") ?? "").pathname,
      "/contact",
      `${route} must redirect to contact`,
    );
  }
});

test("reviewed core routes remain indexable", () => {
  for (const route of REVIEWED_MARKETING_ROUTES) {
    const response = middleware(
      new NextRequest(`https://zorva.ashbi.ca${route}`),
    );
    assert.equal(response.headers.get("X-Robots-Tag"), null);
  }
});

test("production middleware rejects a non-canonical forwarded host", () => {
  const previousNodeEnv = process.env.NODE_ENV;
  const previousAuthUrl = process.env.AUTH_URL;
  process.env.NODE_ENV = "production";
  process.env.AUTH_URL = "https://zorva.ashbi.ca";

  try {
    const response = middleware(new NextRequest("https://attacker.example/api/auth/session"));
    assert.equal(response.status, 400);
  } finally {
    if (previousNodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = previousNodeEnv;
    if (previousAuthUrl === undefined) delete process.env.AUTH_URL;
    else process.env.AUTH_URL = previousAuthUrl;
  }
});
