// first-audit-complete email template.
//
// Fired the first time an encounter transitions to a state where the
// biller should look — for now we treat "first awaiting_review per
// tenant" as the trigger. A later iteration can fire on every
// completed audit; the spec is explicit about the first one only.
//
// Template kind: "transactional" — the user actively submitted the
// encounter, the email is part of the operational loop, no
// List-Unsubscribe header.
//
// Rendered content: a short summary of the findings the auditor
// produced (category, suggested code, est. financial impact) and a
// deep link to the encounter detail page.

import { prisma } from "@/lib/prisma";
import { sendTemplate, escapeHtml, formatMoney } from "@/lib/email";

const BASE_URL = process.env["BASE_URL"] ?? "http://localhost:3000";

export interface FirstAuditCompleteInput {
  /** Recipient email — the tenant owner. */
  to: string;
  /** Tenant display name. */
  tenantName: string;
  /** Tenant id — used for the suppress-list header. */
  tenantId: string;
  /** Encounter id that just finished. */
  encounterId: string;
  /** Total findings the auditor produced. */
  findingCount: number;
  /** Sum of estFinancialImpactCents across all findings. */
  estImpactCents: number;
  /** Top 3 findings (pre-sorted by impact desc by the caller). */
  topFindings: Array<{
    category: string;
    currentCode: string | null;
    suggestedCode: string | null;
    estFinancialImpactCents: number;
  }>;
  /** Currency string (e.g. "USD"). */
  currency: string;
}

/**
 * Send the "your first audit is ready" email. Returns the
 * discriminated SendResult from the shared dispatcher — callers
 * (the trigger in the encounter upload route, the weekly digest
 * catch-up) branch on it.
 */
export async function sendFirstAuditCompleteEmail(
  input: FirstAuditCompleteInput,
): Promise<
  | { sent: true; id: string }
  | { sent: false; mock: boolean; reason?: string; error?: string }
> {
  const subject = `Your first audit is ready — ${input.tenantName}`;
  const encounterUrl = `${BASE_URL.replace(/\/$/, "")}/encounters/${encodeURIComponent(input.encounterId)}`;

  const text = [
    `Hi ${input.tenantName} team,`,
    "",
    `Your first audit just finished. Here's what the auditor found:`,
    `  - Findings: ${input.findingCount}`,
    `  - Estimated impact: ${formatMoney(input.estImpactCents, input.currency)}`,
    "",
    "Open the encounter to review and accept / dismiss each finding:",
    encounterUrl,
    "",
    "If you have questions, reply to this email.",
    "",
    "— The AI Billing Portal team",
  ].join("\n");

  const topRows = input.topFindings
    .slice(0, 3)
    .map((f) => {
      const code = f.suggestedCode
        ? `${f.currentCode ?? "—"} → ${f.suggestedCode}`
        : f.currentCode ?? "—";
      const impact = formatMoney(f.estFinancialImpactCents, input.currency);
      return `      <tr><td>${escapeHtml(f.category)}</td><td>${escapeHtml(code)}</td><td>${escapeHtml(impact)}</td></tr>`;
    })
    .join("");

  const html = [
    "<p>Hi <strong>",
    escapeHtml(input.tenantName),
    "</strong> team,</p>",
    "<p>Your first audit just finished.</p>",
    "<ul>",
    `  <li>Findings: <strong>${input.findingCount}</strong></li>`,
    `  <li>Estimated impact: <strong>${escapeHtml(formatMoney(input.estImpactCents, input.currency))}</strong></li>`,
    "</ul>",
    topRows
      ? [
          "<p>Top findings:</p>",
          '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">',
          "  <thead><tr><th>Category</th><th>Code change</th><th>Est. impact</th></tr></thead>",
          "  <tbody>",
          topRows,
          "  </tbody>",
          "</table>",
        ].join("")
      : "",
    '<p><a href="',
    escapeHtml(encounterUrl),
    '">Open the encounter</a></p>',
    "<p>— The AI Billing Portal team</p>",
  ].join("");

  const result = await sendTemplate({
    to: input.to,
    templateId: "first_audit_complete",
    kind: "transactional",
    subject,
    text,
    html,
    tenantId: input.tenantId,
    metadata: {
      encounterId: input.encounterId,
      findingCount: input.findingCount,
      estImpactCents: input.estImpactCents,
    },
  });

  if (result.sent) return { sent: true, id: result.id };
  if ("suppressed" in result && result.suppressed) {
    return { sent: false, mock: false, reason: result.reason };
  }
  if ("error" in result) {
    return { sent: false, mock: false, error: result.error };
  }
  return { sent: false, mock: result.mock };
}

/**
 * Query the data the email needs: a tenant's most-recent encounter
 * with its findings. Returns null if the tenant has no encounters.
 *
 * Used by both the trigger and the weekly digest catch-up.
 */
export interface FirstAuditSnapshot {
  encounterId: string;
  findingCount: number;
  estImpactCents: number;
  topFindings: Array<{
    category: string;
    currentCode: string | null;
    suggestedCode: string | null;
    estFinancialImpactCents: number;
  }>;
}

export async function loadFirstAuditSnapshot(
  tenantId: string,
): Promise<FirstAuditSnapshot | null> {
  const encounter = await prisma.encounter.findFirst({
    where: { tenantId, status: { in: ["awaiting_review", "completed"] } },
    orderBy: { createdAt: "asc" },
    include: {
      findings: {
        orderBy: { estFinancialImpactCents: "desc" },
        select: {
          category: true,
          currentCode: true,
          suggestedCode: true,
          estFinancialImpactCents: true,
        },
      },
    },
  });
  if (!encounter) return null;
  return {
    encounterId: encounter.id,
    findingCount: encounter.findings.length,
    estImpactCents: encounter.findings.reduce(
      (sum, f) => sum + f.estFinancialImpactCents,
      0,
    ),
    topFindings: encounter.findings,
  };
}
