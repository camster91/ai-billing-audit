import assert from "node:assert/strict";
import { test } from "node:test";
import { NextRequest } from "next/server";
import middleware from "../src/middleware";
import robots from "../src/app/robots";
import sitemap from "../src/app/sitemap";

test("marketing sitemap exposes only reviewed core routes", () => {
  assert.deepEqual(
    sitemap().map((entry) => entry.url),
    [
      "https://zorva.ashbi.ca",
      "https://zorva.ashbi.ca/contact",
      "https://zorva.ashbi.ca/how-it-works",
    ],
  );
});

test("robots disallows deferred marketing routes", () => {
  const rules = robots().rules;
  assert.ok(Array.isArray(rules));
  const disallow = rules[0]?.disallow;
  assert.ok(Array.isArray(disallow));
  assert.ok(disallow.includes("/status"));
  assert.ok(disallow.includes("/pricing"));
  assert.ok(disallow.includes("/security"));
  assert.ok(disallow.includes("/case-studies"));
});

test("deferred marketing responses emit noindex", () => {
  const response = middleware(
    new NextRequest("https://zorva.ashbi.ca/status"),
  );
  assert.equal(response.headers.get("X-Robots-Tag"), "noindex, nofollow");
});

test("reviewed core routes remain indexable", () => {
  const response = middleware(
    new NextRequest("https://zorva.ashbi.ca/contact"),
  );
  assert.equal(response.headers.get("X-Robots-Tag"), null);
});
