import { test } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";

import { buildFastApiAuthHeaders } from "../src/lib/fastapi-principal";

const secret = "principal-signing-secret-at-least-32-bytes";

test("builds a five-minute tenant-bound principal for the FastAPI", () => {
  const headers = buildFastApiAuthHeaders(
    { subject: "user-1", tenantId: "clinic-a", portalRole: "auditor" },
    {
      bearerToken: "service-bearer",
      signingSecret: secret,
      nowSeconds: 1_700_000_000,
    },
  );

  assert.equal(headers.Authorization, "Bearer service-bearer");
  const encoded = headers["X-Zorva-Principal"];
  const payload = JSON.parse(
    Buffer.from(encoded, "base64url").toString("utf8"),
  );
  assert.deepEqual(payload, {
    expires_at: 1_700_000_300,
    role: "biller",
    subject: "user-1",
    tenant_id: "clinic-a",
  });
  assert.equal(
    headers["X-Zorva-Signature"],
    createHmac("sha256", secret).update(encoded, "ascii").digest("hex"),
  );
});

test("maps owner to admin and unknown portal roles to viewer", () => {
  const owner = buildFastApiAuthHeaders(
    { subject: "owner-1", tenantId: "clinic-a", portalRole: "owner" },
    { bearerToken: "bearer", signingSecret: secret, nowSeconds: 1 },
  );
  const unknown = buildFastApiAuthHeaders(
    { subject: "user-2", tenantId: "clinic-a", portalRole: "custom" },
    { bearerToken: "bearer", signingSecret: secret, nowSeconds: 1 },
  );

  assert.equal(
    JSON.parse(Buffer.from(owner["X-Zorva-Principal"], "base64url").toString()).role,
    "admin",
  );
  assert.equal(
    JSON.parse(Buffer.from(unknown["X-Zorva-Principal"], "base64url").toString()).role,
    "viewer",
  );
});

test("fails closed when either server-side credential is missing or weak", () => {
  const principal = {
    subject: "user-1",
    tenantId: "clinic-a",
    portalRole: "viewer",
  };
  assert.throws(
    () =>
      buildFastApiAuthHeaders(principal, {
        bearerToken: "",
        signingSecret: secret,
      }),
    /FASTAPI_BEARER_TOKEN is required/,
  );
  assert.throws(
    () =>
      buildFastApiAuthHeaders(principal, {
        bearerToken: "bearer",
        signingSecret: "short",
      }),
    /FASTAPI_PRINCIPAL_SIGNING_SECRET must be at least 32 bytes/,
  );
});
