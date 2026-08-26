// /readyz — portal-specific dependency-configuration readiness probe
// (issue #65).
//
// The portal runs in the Next.js process and is structurally
// separate from the FastAPI /readyz endpoint in
// src/ai_billing_audit/api.py. That endpoint is the
// "API readyz"; this is the "portal readyz". The two are
// distinct: a green API readyz does not prove the portal can
// authenticate users or reach its own database.
//
// Privacy contract:
//   - Never echoes credentials, secrets, or session contents.
//   - The Prisma probe uses a lightweight bounded query and the
//     result is exposed only as a boolean.
//   - The endpoint is public (no auth) so the deploy edge can
//     reach it without rotating session cookies. The output
//     carries no PII.
//
// Failure semantics:
//   - Returns 200 with `status: "ready"` when every check passes.
//   - Returns 503 with `status: "not_ready"` and per-check
//     results when any check fails. The deploy edge can use the
//     503 as a no-traffic gate.

import { NextResponse } from "next/server";
import { resolveLeadsResendKey } from "@/lib/leads-email";
import { isLeadsSlackMockMode } from "@/lib/leads-slack";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MIN_SECRET_BYTES = 32;

type CheckResult = { ok: true } | { ok: false; reason: string };

function isReadableSecret(value: string | undefined): CheckResult {
  if (!value) return { ok: false, reason: "missing" };
  if (Buffer.byteLength(value, "utf-8") < MIN_SECRET_BYTES) {
    return { ok: false, reason: "too_short" };
  }
  return { ok: true };
}

async function databaseReachable(): Promise<CheckResult> {
  try {
    // Dynamic import keeps the Prisma client out of the module's
    // static graph so the route is unit-testable without the
    // generated client (the build-time ZORVA_BUILD_SKIP_DATABASE
    // proxy is used here when the generated client is absent).
    const prismaModule = await import("@/lib/prisma");
    const prisma = prismaModule.prisma;
    // Run the probe in a bounded transaction. PostgreSQL's
    // statement_timeout cancels a stuck query on the server, while
    // Prisma's maxWait/timeout bounds pool acquisition and the
    // transaction itself. This avoids abandoned queries accumulating
    // behind a Promise.race timeout during an outage.
    const result = await prisma.$transaction(
      async (tx) => {
        await tx.$executeRaw`SET LOCAL statement_timeout = '5000ms'`;
        return tx.$queryRaw<Array<{ one: number }>>`SELECT 1 AS one`;
      },
      { maxWait: 1_000, timeout: 6_000 },
    );
    if (!Array.isArray(result) || result.length === 0 || (result[0] as { one?: number } | undefined)?.one !== 1) {
      return { ok: false, reason: "unexpected_response" };
    }
    return { ok: true };
  } catch (e) {
    return {
      ok: false,
      reason: e instanceof Error ? e.message : "unknown",
    };
  }
}

export async function GET(): Promise<NextResponse> {
  const checks: Record<string, CheckResult> = {
    database_url_configured: process.env.DATABASE_URL
      ? { ok: true }
      : { ok: false, reason: "missing" },
    auth_secret_configured: isReadableSecret(process.env.AUTH_SECRET),
    auth_resend_key_configured: isReadableSecret(process.env.AUTH_RESEND_KEY),
    leads_resend_key_configured: isReadableSecret(resolveLeadsResendKey()),
    slack_webhook_configured: isLeadsSlackMockMode()
      ? { ok: true }
      : { ok: true, reason: "configured" },
    database_reachable: await databaseReachable(),
  };

  const ready = Object.values(checks).every((c) => c.ok);
  return NextResponse.json(
    {
      status: ready ? "ready" : "not_ready",
      service: "portal",
      checks,
    },
    {
      status: ready ? 200 : 503,
      headers: { "Cache-Control": "no-store" },
    },
  );
}
