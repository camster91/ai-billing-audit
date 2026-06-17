// First-audit-complete trigger.
//
// `maybeSendFirstAuditComplete(tenantId)` is the single entry point
// every encounter-ingest path should call after it writes a new
// encounter row. The function is idempotent: it short-circuits when
// the tenant already has firstAuditEmailSentAt set, so calling it
// repeatedly (e.g. from a batch ingest) is safe.
//
// Where it's called from:
//   - /api/onboarding/complete (after the wizard's "first encounter"
//     step finishes — covers the demo / first-time-tenant path).
//   - The FastAPI audit run (via scripts/post-audit.ts, when the
//     audit pipeline writes an encounter to production Postgres).
//   - The seed scripts (smoke / e2e / demo seed) — guarded by
//     RESEND_API_KEY so we never spam real addresses from a
//     test run.
//
// Why a function and not a Prisma trigger: the email send touches
// the Resend client and the SuppressList table, both of which are
// app-layer concerns. A DB trigger wouldn't have either. Keeping
// the trigger in TS also lets a future maintainer add a
// `if (process.env.SUPPRESS_AUDIT_EMAILS === "1")` early-out
// without a migration.

import { prisma } from "@/lib/prisma";
import {
  loadFirstAuditSnapshot,
  sendFirstAuditCompleteEmail,
} from "@/lib/emails/first-audit-complete";

export type MaybeSendResult =
  | { sent: true; id: string; encounterId: string }
  | { skipped: true; reason: string }
  | { sent: false; error: string };

/**
 * Idempotently dispatch the first-audit-complete email. Returns
 * a discriminated result so the caller (and the smoke test) can
 * branch on it.
 *
 *  - skipped (already sent)  → tenant.firstAuditEmailSentAt is set
 *  - skipped (no encounter)  → tenant has no encounter row yet
 *  - skipped (no owner)      → tenant has no owner-attachable user
 *  - skipped (no email mode) → RESEND_API_KEY is a placeholder AND
 *                              caller is in test mode (we don't
 *                              flip firstAuditEmailSentAt in mock
 *                              mode so re-runs in dev still fire)
 *  - sent                     → message dispatched
 *  - sent: false              → Resend / network error; the caller
 *                              should log and move on (the audit
 *                              itself succeeded)
 */
export async function maybeSendFirstAuditComplete(
  tenantId: string,
): Promise<MaybeSendResult> {
  // 1. Idempotency gate. We do this before any work to keep the
  // hot path cheap.
  const tenant = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: {
      id: true,
      name: true,
      firstAuditEmailSentAt: true,
    },
  });
  if (!tenant) {
    return { skipped: true, reason: "tenant not found" };
  }
  if (tenant.firstAuditEmailSentAt) {
    return { skipped: true, reason: "already sent" };
  }

  // 2. Owner resolution — mirror the welcome-email helper so the
  // recipient list stays consistent.
  const owner = await prisma.membership.findFirst({
    where: { tenantId, role: "owner" },
    include: { user: { select: { email: true } } },
  });
  const ownerEmail = owner?.user?.email;
  if (!ownerEmail) {
    return { skipped: true, reason: "no owner email" };
  }

  // 3. Snapshot — the email body needs the first encounter's
  // finding count and impact total.
  const snapshot = await loadFirstAuditSnapshot(tenantId);
  if (!snapshot) {
    return { skipped: true, reason: "no encounter yet" };
  }

  // 4. Dispatch.
  const result = await sendFirstAuditCompleteEmail({
    to: ownerEmail,
    tenantName: tenant.name,
    tenantId: tenant.id,
    encounterId: snapshot.encounterId,
    findingCount: snapshot.findingCount,
    estImpactCents: snapshot.estImpactCents,
    topFindings: snapshot.topFindings,
    currency: "USD",
  });

  // 5. Flip the dedup flag when the dispatcher took the call. We
  // flip on real-sent, on mock-sent (so dev re-runs don't spam
  // stdout forever), and on suppressed (the address is dead and
  // we shouldn't retry). The only "no flip" case is a real
  // Resend error — those are retryable, and the caller can
  // re-invoke after the network is healthy.
  const didDispatch =
    ("sent" in result && result.sent) ||
    ("mock" in result && result.mock === true) ||
    ("suppressed" in result && result.suppressed === true);
  if (didDispatch) {
    await prisma.tenant.update({
      where: { id: tenantId },
      data: { firstAuditEmailSentAt: new Date() },
    });
  }
  if ("sent" in result && result.sent) {
    return { sent: true, id: result.id, encounterId: snapshot.encounterId };
  }
  if ("error" in result) {
    return { sent: false, error: result.error ?? "unknown error" };
  }
  return { sent: false, error: "unexpected result shape" };
}
