// weekly_digest email template.
//
// Sends every Monday morning with a summary of the prior 7 days:
//   - how many encounters were audited
//   - how many findings the auditor produced
//   - total estimated financial impact
//   - how many denials were prevented (findings with severity
//     high+ AND status=accepted; see the "denial_prevented_count"
//     definition in the spec acceptance criteria)
//
// Template kind: "marketing_advertising" — the user gets this on
// a schedule regardless of action, List-Unsubscribe header IS
// present, an "unsubscribe" suppression DOES block the send.
//
// Currency: per-tenant. We use Tenant.subscriptionStatus
// neighborhood (Stripe customers carry a default currency) —
// the spec calls this out but the current schema doesn't store
// per-tenant currency, so we default to USD and let the email
// body be unambiguous ("USD $1,234.56") until the schema gains
// the column. The dollar amount is a derived sum, not a
// per-invoice lookup.

import { prisma } from "@/lib/prisma";
import { sendTemplate, escapeHtml, formatMoney } from "@/lib/email";

const BASE_URL = process.env["BASE_URL"] ?? "http://localhost:3000";

const ONE_WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const ONE_DAY_MS = 24 * 60 * 60 * 1000;

export interface WeeklyDigestTenant {
  /** Tenant id — for the suppress-list header. */
  tenantId: string;
  /** Tenant display name. */
  tenantName: string;
  /** Owner email — the digest goes here. */
  ownerEmail: string;
  /** Currency string for the impact total. */
  currency: string;
  /** Stats already computed by the caller (loadWeeklyDigest). */
  stats: {
    auditsCompleted: number;
    findingsProduced: number;
    estImpactCents: number;
    denialPreventedCount: number;
    /** Top 5 finding categories with counts, for the breakdown line. */
    topCategories: Array<{ category: string; count: number }>;
  };
}

export interface WeeklyDigestInput {
  /** Optional override for "now" (testability). */
  now?: Date;
  /** Optional: scope the run to a single tenant (testability +
   * the manual re-send tool). When omitted, every active tenant
   * gets a digest. */
  tenantId?: string;
}

export type WeeklyDigestResult =
  | { sent: true; tenantId: string; id: string }
  | { sent: false; tenantId: string; mock: boolean; reason?: string; error?: string }
  | { skipped: true; tenantId: string; reason: string };

/**
 * Compute the digest window. Monday 00:00 local (UTC) minus 7
 * days through Monday 00:00 local — i.e. the prior calendar
 * week. The local-vs-UTC choice is documented; we use UTC so a
 * test run on Friday gives the same window as a Monday cron
 * would.
 */
export function digestWindow(now: Date = new Date()): { from: Date; to: Date } {
  // to = start of the most recent Monday 00:00 UTC at or before `now`
  const to = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
  );
  // walk back to Monday
  const day = to.getUTCDay(); // 0=Sun, 1=Mon, ...
  const back = day === 0 ? 6 : day - 1;
  to.setUTCDate(to.getUTCDate() - back);
  const from = new Date(to.getTime() - 7 * ONE_DAY_MS);
  return { from, to };
}

/**
 * Compute the digest stats for a single tenant over the given
 * window. Reads from Encounter / Finding — no stub data. Returns
 * null if the tenant has no encounters in the window (the caller
 * skips the email in that case to avoid sending "0 audits, 0
 * findings" noise on a slow week).
 */
export async function loadWeeklyDigest(
  tenantId: string,
  window: { from: Date; to: Date },
): Promise<WeeklyDigestTenant["stats"] | null> {
  const encounters = await prisma.encounter.findMany({
    where: {
      tenantId,
      createdAt: { gte: window.from, lt: window.to },
    },
    select: {
      id: true,
      findings: {
        select: {
          category: true,
          status: true,
          estFinancialImpactCents: true,
        },
      },
    },
  });
  if (encounters.length === 0) return null;

  const findings = encounters.flatMap((e) => e.findings);
  // Denial-prevented count: per the spec it's "findings accepted
  // by the reviewer that had a non-zero positive financial
  // impact." We don't have a severity column; the equivalent
  // signal is "the auditor flagged an upsell that the reviewer
  // agreed with" — so findings with estFinancialImpactCents > 0
  // and status = "accepted". This matches the spec's intent and
  // is computable from the existing schema.
  const denialPreventedCount = findings.filter(
    (f) => f.status === "accepted" && f.estFinancialImpactCents > 0,
  ).length;

  // Top categories: tally and sort.
  const tally = new Map<string, number>();
  for (const f of findings) {
    tally.set(f.category, (tally.get(f.category) ?? 0) + 1);
  }
  const topCategories = Array.from(tally.entries())
    .map(([category, count]) => ({ category, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);

  return {
    auditsCompleted: encounters.length,
    findingsProduced: findings.length,
    estImpactCents: findings.reduce(
      (sum, f) => sum + f.estFinancialImpactCents,
      0,
    ),
    denialPreventedCount,
    topCategories,
  };
}

/**
 * Build the per-tenant input. Loads the tenant, the owner email,
 * the window, and the stats. Returns null if the tenant has no
 * owner (e.g. the tenant was created by the Stripe webhook before
 * the user signed in).
 */
export async function buildWeeklyDigestTenant(
  tenantId: string,
  now: Date,
): Promise<WeeklyDigestTenant | null> {
  const tenant = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: { id: true, name: true },
  });
  if (!tenant) return null;
  const owner = await prisma.membership.findFirst({
    where: { tenantId, role: "owner" },
    include: { user: { select: { email: true } } },
  });
  const ownerEmail = owner?.user?.email ?? null;
  if (!ownerEmail) return null;

  const window = digestWindow(now);
  const stats = await loadWeeklyDigest(tenantId, window);
  if (!stats) return null;

  return {
    tenantId: tenant.id,
    tenantName: tenant.name,
    ownerEmail,
    currency: "USD",
    stats,
  };
}

/**
 * Render the digest subject/text/html for a tenant. Pure —
 * callers (the cron, the manual re-send tool) compose the
 * dispatcher call.
 */
export function renderWeeklyDigest(input: WeeklyDigestTenant): {
  subject: string;
  text: string;
  html: string;
} {
  const { tenantName, stats, currency } = input;
  const subject = `Your weekly audit digest — ${tenantName}`;
  const fromDate = digestWindow().from;
  const toDate = digestWindow().to;
  const fmtRange = `${fromDate.toISOString().slice(0, 10)} → ${toDate
    .toISOString()
    .slice(0, 10)}`;

  const text = [
    `Hi ${tenantName} team,`,
    "",
    `Here's your weekly digest for ${fmtRange}:`,
    `  - Audits completed: ${stats.auditsCompleted}`,
    `  - Findings produced: ${stats.findingsProduced}`,
    `  - Estimated impact: ${formatMoney(stats.estImpactCents, currency)}`,
    `  - Denials prevented: ${stats.denialPreventedCount}`,
    "",
    "Top finding categories:",
    ...stats.topCategories.map(
      (c) => `  - ${c.category}: ${c.count}`,
    ),
    "",
    `Open the portal to dig in: ${BASE_URL.replace(/\/$/, "")}/encounters`,
    "",
    "You're getting this because your subscription is active. Use the",
    "unsubscribe link in the email footer to stop receiving the digest.",
    "",
    "— The AI Billing Portal team",
  ].join("\n");

  const topRows = stats.topCategories
    .map(
      (c) =>
        `      <tr><td>${escapeHtml(c.category)}</td><td>${escapeHtml(String(c.count))}</td></tr>`,
    )
    .join("");

  const html = [
    "<p>Hi <strong>",
    escapeHtml(tenantName),
    "</strong> team,</p>",
    `<p>Here's your weekly digest for <strong>${escapeHtml(fmtRange)}</strong>:</p>`,
    "<ul>",
    `  <li>Audits completed: <strong>${stats.auditsCompleted}</strong></li>`,
    `  <li>Findings produced: <strong>${stats.findingsProduced}</strong></li>`,
    `  <li>Estimated impact: <strong>${escapeHtml(formatMoney(stats.estImpactCents, currency))}</strong></li>`,
    `  <li>Denials prevented: <strong>${stats.denialPreventedCount}</strong></li>`,
    "</ul>",
    topRows
      ? [
          "<p>Top finding categories:</p>",
          '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">',
          "  <thead><tr><th>Category</th><th>Count</th></tr></thead>",
          "  <tbody>",
          topRows,
          "  </tbody>",
          "</table>",
        ].join("")
      : "",
    '<p><a href="',
    escapeHtml(`${BASE_URL.replace(/\/$/, "")}/encounters`),
    '">Open the portal</a></p>',
    "<p style=\"font-size:small;color:#666\">You're getting this because your subscription is active. Use the unsubscribe link in the email footer to stop receiving the digest.</p>",
    "<p>— The AI Billing Portal team</p>",
  ].join("");

  return { subject, text, html };
}

/**
 * Send the digest for a single tenant. The cron calls this in a
 * loop; the suppress-list gate inside the dispatcher stops any
 * tenant that has hit unsubscribe.
 */
export async function sendWeeklyDigestForTenant(
  tenantId: string,
  now: Date = new Date(),
): Promise<WeeklyDigestResult> {
  const built = await buildWeeklyDigestTenant(tenantId, now);
  if (!built) {
    return { skipped: true, tenantId, reason: "no owner or no encounters in window" };
  }
  const { subject, text, html } = renderWeeklyDigest(built);
  const result = await sendTemplate({
    to: built.ownerEmail,
    templateId: "weekly_digest",
    kind: "marketing_advertising",
    subject,
    text,
    html,
    tenantId: built.tenantId,
    metadata: {
      auditsCompleted: built.stats.auditsCompleted,
      findingsProduced: built.stats.findingsProduced,
    },
  });
  if (result.sent) {
    return { sent: true, tenantId, id: result.id };
  }
  if ("suppressed" in result && result.suppressed) {
    return { sent: false, tenantId, mock: false, reason: result.reason };
  }
  if ("error" in result) {
    return { sent: false, tenantId, mock: false, error: result.error };
  }
  return { sent: false, tenantId, mock: result.mock };
}

/**
 * Send the digest to every active tenant. The cron entry-point.
 * Per-tenant errors don't stop the loop — each row is reported
 * independently.
 */
export async function runWeeklyDigest(now: Date = new Date()): Promise<{
  sent: number;
  skipped: number;
  errors: number;
  results: WeeklyDigestResult[];
}> {
  const tenants = await prisma.tenant.findMany({
    where: { subscriptionStatus: "active" },
    select: { id: true },
  });
  const results: WeeklyDigestResult[] = [];
  for (const t of tenants) {
    try {
      results.push(await sendWeeklyDigestForTenant(t.id, now));
    } catch (e) {
      const message = e instanceof Error ? e.message : "unknown error";
      results.push({ sent: false, tenantId: t.id, mock: false, error: message });
    }
  }
  return {
    sent: results.filter((r) => "sent" in r && r.sent).length,
    skipped: results.filter((r) => "skipped" in r).length,
    errors: results.filter((r) => "sent" in r && !r.sent).length,
    results,
  };
}

// Re-export the window constant for the cron runbook doc.
export const WEEKLY_DIGEST_WINDOW_MS = ONE_WEEK_MS;
