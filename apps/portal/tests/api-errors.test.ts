// Tests for apps/portal/src/lib/api-errors.ts
//
// Covers:
//   - internalErrorResponse returns 500 with the canonical body shape
//     { error: "internal_error", requestId }.
//   - The raw error.message is NEVER in the response body (P11
//     bug-sweep finding).
//   - The x-request-id header is set so support can correlate.
//   - The server-side log includes the route + hint + message +
//     stack.
//   - Non-Error throws (e.g. strings) are coerced to "[object]" or
//     similar — never leaked verbatim.
//   - Override of requestId is honored (for callers that already
//     minted one).

import { test } from "node:test";
import assert from "node:assert/strict";
import { internalErrorResponse } from "../src/lib/api-errors";

test("internalErrorResponse returns 500 with sanitized body", async () => {
  const originalLog = console.error;
  const logs: string[] = [];
  console.error = (...args: unknown[]) => {
    logs.push(args.map(String).join(" "));
  };
  try {
    const resp = internalErrorResponse(
      new Request("https://zorva.ashbi.ca/api/leads"),
      new Error("connection string: postgres://user:hunter2@host/db"),
      "/api/leads",
    );
    // Status code
    assert.equal(resp.status, 500);
    // Body shape
    const body = await resp.json();
    assert.equal(body.error, "internal_error");
    assert.ok(typeof body.requestId === "string" && body.requestId.length > 0);
    // CRITICAL: the raw error message must NOT appear in the body.
    assert.ok(
      !JSON.stringify(body).includes("hunter2"),
      "raw connection-string password leaked into client body",
    );
    assert.ok(
      !JSON.stringify(body).includes("postgres://user"),
      "raw error message leaked into client body",
    );
    // x-request-id header set
    assert.ok(
      resp.headers.get("x-request-id"),
      "missing x-request-id header for support correlation",
    );
    // Server-side log captured the full context
    const combined = logs.join("\n");
    assert.ok(combined.includes("/api/leads"), "route name missing from log");
    assert.ok(combined.includes("hunter2"), "log missing the raw error context");
    assert.ok(
      combined.includes("requestId="),
      "log missing requestId for correlation",
    );
  } finally {
    console.error = originalLog;
  }
});

test("internalErrorResponse coerces non-Error throws", async () => {
  const originalLog = console.error;
  const logs: string[] = [];
  console.error = (...args: unknown[]) => {
    logs.push(args.map(String).join(" "));
  };
  try {
    // Throw a string (non-Error). The helper must not crash and must
    // not put the string in the client body.
    const resp = internalErrorResponse(
      new Request("https://zorva.ashbi.ca/api/x"),
      "raw string error leaked",
      "/api/x",
    );
    assert.equal(resp.status, 500);
    const body = await resp.json();
    assert.equal(body.error, "internal_error");
    assert.ok(!JSON.stringify(body).includes("raw string error leaked"));
    // Server-side log captured the string
    assert.ok(logs.some((l) => l.includes("raw string error leaked")));
  } finally {
    console.error = originalLog;
  }
});

test("internalErrorResponse honors override requestId", async () => {
  const resp = internalErrorResponse(
    null,
    new Error("boom"),
    "/api/y",
    { requestId: "rid_test_12345" },
  );
  assert.equal(resp.headers.get("x-request-id"), "rid_test_12345");
  const body = await resp.json();
  assert.equal(body.requestId, "rid_test_12345");
});

test("internalErrorResponse hint appears in log, not body", async () => {
  const originalLog = console.error;
  const logs: string[] = [];
  console.error = (...args: unknown[]) => {
    logs.push(args.map(String).join(" "));
  };
  try {
    const resp = internalErrorResponse(
      null,
      new Error("DB down"),
      "/api/z",
      { hint: "lead insert failed (constraint X violated)" },
    );
    const body = await resp.json();
    // Hint is operator-only — never in the client body.
    assert.ok(!JSON.stringify(body).includes("constraint X"));
    assert.ok(!JSON.stringify(body).includes("lead insert failed"));
    // But hint IS in the log so support can grep for it.
    assert.ok(
      logs.some((l) => l.includes("lead insert failed")),
      "hint missing from log",
    );
  } finally {
    console.error = originalLog;
  }
});

test("internalErrorResponse mints different requestIds for concurrent calls", async () => {
  const a = internalErrorResponse(null, new Error("a"), "/api/q");
  const b = internalErrorResponse(null, new Error("b"), "/api/q");
  const aId = a.headers.get("x-request-id");
  const bId = b.headers.get("x-request-id");
  assert.ok(aId && bId, "both requestIds present");
  assert.notEqual(aId, bId, "requestIds must be unique per call");
});