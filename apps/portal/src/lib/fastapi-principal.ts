import { createHmac } from "node:crypto";

export interface FastApiPrincipal {
  subject: string;
  tenantId: string;
  portalRole: string;
}

interface FastApiCredentialOptions {
  bearerToken?: string;
  signingSecret?: string;
  nowSeconds?: number;
}

function fastApiRole(portalRole: string): "admin" | "biller" | "viewer" {
  if (portalRole === "owner" || portalRole === "admin") return "admin";
  if (portalRole === "auditor" || portalRole === "biller") return "biller";
  return "viewer";
}

export function buildFastApiAuthHeaders(
  principal: FastApiPrincipal,
  options: FastApiCredentialOptions = {},
): Record<string, string> {
  const bearerToken = options.bearerToken ?? process.env.FASTAPI_BEARER_TOKEN ?? "";
  const signingSecret =
    options.signingSecret ?? process.env.FASTAPI_PRINCIPAL_SIGNING_SECRET ?? "";
  if (!bearerToken) {
    throw new Error("FASTAPI_BEARER_TOKEN is required");
  }
  if (Buffer.byteLength(signingSecret, "utf8") < 32) {
    throw new Error(
      "FASTAPI_PRINCIPAL_SIGNING_SECRET must be at least 32 bytes",
    );
  }
  if (!principal.subject || !principal.tenantId) {
    throw new Error("FastAPI principal requires subject and tenantId");
  }

  const nowSeconds = options.nowSeconds ?? Math.floor(Date.now() / 1000);
  const payload = {
    expires_at: nowSeconds + 300,
    role: fastApiRole(principal.portalRole),
    subject: principal.subject,
    tenant_id: principal.tenantId,
  };
  const encoded = Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
  const signature = createHmac("sha256", signingSecret)
    .update(encoded, "ascii")
    .digest("hex");

  return {
    Authorization: `Bearer ${bearerToken}`,
    "X-Zorva-Principal": encoded,
    "X-Zorva-Signature": signature,
  };
}
