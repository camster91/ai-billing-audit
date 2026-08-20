// Unit tests for the encounter-search helper extracted from
// apps/portal/src/app/not-found.tsx (issue #67).
//
// Verifies the four-state outcome contract:
//   - 2xx with results:[]         → { outcome: "empty" }
//   - 2xx with results:[...]      → { outcome: "results", results }
//   - non-2xx                     → { outcome: "http_error", status }
//   - fetch or JSON parse throws  → { outcome: "network_error", message }

import assert from "node:assert/strict";
import { test } from "node:test";
import { searchEncounters } from "../src/app/encounter-search";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("searchEncounters returns 'empty' on 2xx with no results", async () => {
  const fetchMock: typeof fetch = async () => jsonResponse({ results: [] });
  const outcome = await searchEncounters("nope", fetchMock);
  assert.deepEqual(outcome, { outcome: "empty" });
});

test("searchEncounters returns 'results' on 2xx with entries", async () => {
  const rows = [
    { id: "enc_1", dateOfService: "2026-05-15", patientHash: "h1", isFlagged: false },
    { id: "enc_2", dateOfService: "2026-05-16", patientHash: "h2", isFlagged: true },
  ];
  const fetchMock: typeof fetch = async () => jsonResponse({ results: rows });
  const outcome = await searchEncounters("anything", fetchMock);
  assert.equal(outcome.outcome, "results");
  if (outcome.outcome === "results") {
    assert.equal(outcome.results.length, 2);
    assert.equal(outcome.results[0].id, "enc_1");
  }
});

test("searchEncounters returns 'http_error' with status on non-2xx", async () => {
  const fetchMock: typeof fetch = async () => jsonResponse({ error: "unauthenticated" }, 401);
  const outcome = await searchEncounters("q", fetchMock);
  assert.deepEqual(outcome, { outcome: "http_error", status: 401 });
});

test("searchEncounters returns 'http_error' on 5xx without throwing", async () => {
  const fetchMock: typeof fetch = async () => jsonResponse({ error: "boom" }, 503);
  const outcome = await searchEncounters("q", fetchMock);
  assert.deepEqual(outcome, { outcome: "http_error", status: 503 });
});

test("searchEncounters returns 'network_error' when fetch throws", async () => {
  const fetchMock: typeof fetch = async () => {
    throw new TypeError("NetworkError: fetch failed");
  };
  const outcome = await searchEncounters("q", fetchMock);
  assert.equal(outcome.outcome, "network_error");
  if (outcome.outcome === "network_error") {
    assert.match(outcome.message, /NetworkError/);
  }
});

test("searchEncounters returns 'network_error' when response JSON is malformed", async () => {
  const fetchMock: typeof fetch = async () =>
    new Response("not actually json {", { status: 200 });
  const outcome = await searchEncounters("q", fetchMock);
  assert.equal(outcome.outcome, "network_error");
});

test("searchEncounters URL-encodes the query string", async () => {
  let captured: string | null = null;
  const fetchMock: typeof fetch = async (input) => {
    captured = String(input);
    return jsonResponse({ results: [] });
  };
  await searchEncounters("hello world & friends", fetchMock);
  assert.equal(captured, "/api/encounters/search?q=hello%20world%20%26%20friends");
});

test("searchEncounters treats missing 'results' field as empty", async () => {
  const fetchMock: typeof fetch = async () => jsonResponse({});
  const outcome = await searchEncounters("q", fetchMock);
  assert.deepEqual(outcome, { outcome: "empty" });
});
