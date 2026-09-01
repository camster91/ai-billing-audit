// E2E smoke harness helpers.
//
// The 8-step smoke flow (smoke.spec.ts) is intentionally a single
// file with ordered tests. The helpers here are not test files
// (playwright.config.ts excludes anything not matching *.spec.ts),
// so they do not run on their own.
//
// What lives here:
//   - DEFAULT_USER_EMAIL / DEFAULT_TENANT_SLUG: the seed user the
//     dev server expects (seeded by scripts/e2e_acceptance_seed.ts).
//   - captureMagicLinkFromLog: tail the dev server's stdout looking
//     for the [auth] magic link line. Returns the URL or throws after
//     a 20s deadline.
//   - loginViaMagicLink: drives NextAuth's /api/auth/signin/resend
//     form endpoint with a CSRF token, then visits the magic link
//     to land the user on /dashboard.
//   - postCheckout: drives /api/billing/checkout (demo mode in dev
//     returns a sessionId without contacting Stripe).
//   - postSeedEncounter: spawns scripts/e2e_acceptance_post_seed.ts
//     to write the encounter + 2 findings + invoice that step 5/6/7/8
//     exercise. Returns the JSON payload the script prints on its
//     last line.

import * as path from "node:path";
import { spawnSync, type SpawnSyncReturns } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";

import type { APIRequestContext, Page } from "@playwright/test";

// Default E2E user. The original acceptance script uses the same
// literal default — that placeholder is invalid as an actual address
// (NextAuth's email validator rejects it). CI / local dev set
// E2E_USER_EMAIL to a real address; the helper + seed read it from
// the env. Default below is intentionally a syntactically valid
// address (e.g. "user@e2e.local") so the suite runs even if the
// env is not set.
export const DEFAULT_USER_EMAIL = process.env["E2E_USER_EMAIL"] ?? "e2e+e2e-clinic@ai-billing-audit.test";
export const DEFAULT_TENANT_SLUG = process.env["E2E_TENANT_SLUG"] ?? "e2e-clinic";

// /tmp/portal-dev.log is the default dev server log path used by
// `pnpm dev:background`. When the dev server is already attached to
// a TTY the magic link prints to the terminal instead — in that case
// the helper falls back to a 5s grace and assumes the user is
// already signed in.
const DEV_LOG = process.env["E2E_DEV_LOG"] ?? "/tmp/portal-dev.log";
const AUTH_CAPTURE_FILE = process.env["E2E_AUTH_CAPTURE_FILE"];

/** Dev inbox: transactional emails are (dev mock)'d to the dev log. */
export interface DevEmail {
  to: string;
  from: string;
  subject: string;
  templateId: string;
  raw: string;
}

/** Tail the dev log looking for the most recent (dev mock) email
 * sent to `to` matching `templateId`. Returns the parsed payload
 * or throws after timeoutMs. The 10-step acceptance flow uses
 * this for the welcome email and weekly digest verification
 * (steps 4 + 9 in the original body). */
export async function captureDevEmail(
  to: string,
  templateId: string,
  logFile: string = DEV_LOG,
  timeoutMs = 30_000,
): Promise<DevEmail> {
  const deadline = Date.now() + timeoutMs;
  // Scan the current log as well as new content. Callers trigger the send
  // before entering this helper, so snapshotting the current size would skip
  // the message that was just emitted.
  while (Date.now() < deadline) {
    let content = "";
    try {
      content = readFileSync(logFile, "utf8");
    } catch {
      content = "";
    }
    // Reparse the complete log on each poll. Console output can become visible
    // after the header but before the subject/body lines; advancing a byte
    // cursor at that point would discard the only header for this email.
    const match = parseDevEmail(content, to, templateId);
    if (match) return match;
    await new Promise((r) => setTimeout(r, 250));
  }
  let observedHeaders = "none";
  try {
    observedHeaders =
      readFileSync(logFile, "utf8")
        .split("\n")
        .filter((line) => line.includes("[email]"))
        .slice(-8)
        .join(" | ") || "none";
  } catch {
    observedHeaders = "log unreadable";
  }
  throw new Error(
    `no (dev mock) email for to=${to} templateId=${templateId} in ${logFile} within ${timeoutMs}ms; observed email headers: ${observedHeaders}`,
  );
}

function parseDevEmail(
  fresh: string,
  to: string,
  templateId: string,
): DevEmail | null {
  // sendTemplate() puts the template id in the header rather than on a
  // separate `template:` line. Capture that id and terminate at the next
  // application log block (or real end-of-input). JavaScript has no `\Z`
  // anchor, so using it here would silently make an end-of-file email
  // impossible to match.
  const re =
    /\[email\]\s+\(dev mock\) would send\s+([a-zA-Z0-9_-]+)[^\n]*:\s*\n([\s\S]*?)(?=\n(?:\[email\]|\[auth\])|$)/g;
  let m: RegExpExecArray | null;
  let lastMatch: DevEmail | null = null;
  while ((m = re.exec(fresh)) !== null) {
    const loggedTemplateId = m[1];
    const block = m[2];
    const toMatch = /to:\s*([^\n]+)/.exec(block);
    const fromMatch = /from:\s*([^\n]+)/.exec(block);
    const subjMatch = /subject:\s*([^\n]+)/.exec(block);
    const tmplMatch = /template:\s*([a-zA-Z0-9_-]+)/.exec(block);
    if (!toMatch || !subjMatch) continue;
    if (!toMatch[1].includes(to)) continue;
    if (loggedTemplateId !== templateId) continue;
    if (tmplMatch && tmplMatch[1] !== templateId) continue;
    lastMatch = {
      to: toMatch[1].trim(),
      from: fromMatch ? fromMatch[1].trim() : "",
      subject: subjMatch[1].trim(),
      templateId: loggedTemplateId,
      raw: block,
    };
  }
  return lastMatch;
}

export function resolvePortalCwd(): string {
  // tests/e2e/helpers.ts -> apps/portal
  return path.resolve(__dirname, "..", "..");
}

/** Wait for the [auth] magic link line in the dev server log. */
export async function captureMagicLinkFromLog(
  email: string,
  logFile: string = DEV_LOG,
  timeoutMs = 20_000,
): Promise<string> {
  if (AUTH_CAPTURE_FILE) {
    const { createHash } = await import("node:crypto");
    const identifier =
      "sha256:" +
      createHash("sha256").update(email.toLowerCase()).digest("hex").slice(0, 8);
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const capture = JSON.parse(readFileSync(AUTH_CAPTURE_FILE, "utf8")) as {
          identifier?: string;
          url?: string;
        };
        if (capture.identifier === identifier && capture.url) return capture.url;
      } catch {
        // The file may not exist yet or may be between atomic runner writes.
      }
      await new Promise((r) => setTimeout(r, 250));
    }
    throw new Error(`no captured magic link appeared within ${timeoutMs}ms`);
  }
  if (!existsSync(logFile)) {
    throw new Error(
      `dev log not found at ${logFile}. The dev server is not writing to a log file — ` +
        "the magic link will not be capturable. Start the dev server with `pnpm dev:background`.",
    );
  }
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const text = readFileSync(logFile, "utf8");
      const lines = text.split("\n");
      let i = lines.length - 1;
      while (i >= 0) {
        const line = lines[i]!;
        if (line.includes("[auth] magic link for " + email + ":")) {
          for (let j = i + 1; j < Math.min(i + 4, lines.length); j++) {
            const candidate = lines[j]!.trim();
            if (candidate.startsWith("http://") || candidate.startsWith("https://")) {
              return candidate;
            }
          }
        }
        i--;
      }
    } catch {
      // log might be being written; retry
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(
    `no magic link for ${email} appeared in ${logFile} within ${timeoutMs}ms`,
  );
}

/**
 * Sign in by POSTing NextAuth's /api/auth/signin/resend directly,
 * capturing the magic link from the dev log, and visiting it.
 * Bypasses the React Server Action form which doesn't hydrate
 * reliably under headless Playwright in Turbopack dev mode.
 */
export async function loginViaMagicLink(
  page: Page,
  email: string = DEFAULT_USER_EMAIL,
  callbackUrl = "/dashboard",
): Promise<void> {
  // page.request is an APIRequestContext with baseURL already set from
  // playwright.config.ts, so absolute paths resolve against the dev
  // server automatically.
  const csrfRes = await page.request.get(`/api/auth/csrf`);
  const csrfBody = (await csrfRes.json()) as { csrfToken: string };
  const signinRes = await page.request.post(
    `/api/auth/signin/resend`,
    {
      form: { email, csrfToken: csrfBody.csrfToken, callbackUrl },
      maxRedirects: 0,
    },
  );
  if (signinRes.status() !== 302) {
    throw new Error(
      `signin returned HTTP ${signinRes.status()}, expected 302 to /api/auth/verify-request`,
    );
  }
  const link = await captureMagicLinkFromLog(email);
  await page.goto(link, { waitUntil: "domcontentloaded" });
  // The callbackUrl is the path the user lands on AFTER the
  // /api/auth/callback route finishes. The helper's regex
  // builder escapes `/` only; for a callbackUrl with a query
  // string, we instead test page.url() contains the path
  // portion of the callback, ignoring querystring.
  const path = callbackUrl.split("?")[0] ?? callbackUrl;
  await page.waitForURL(
    (url) => url.pathname === path || url.pathname.startsWith(`${path}/`),
    { timeout: 30_000 },
  );
}

export interface CheckoutResult {
  sessionId: string;
  url: string;
  demo: boolean;
}

/** POST /api/billing/checkout — returns the demo sessionId. */
export async function postCheckout(
  request: APIRequestContext,
  tier: "small" | "mid" | "large" = "mid",
  currency: "CAD" | "USD" = "CAD",
): Promise<CheckoutResult> {
  const res = await request.post(`/api/billing/checkout`, {
    data: { tierId: tier, currency },
    headers: { "content-type": "application/json" },
  });
  const body = (await res.json()) as Partial<CheckoutResult> & { error?: string };
  if (res.status() !== 200 || !body.sessionId) {
    throw new Error(
      `checkout returned HTTP ${res.status()}: ${JSON.stringify(body).slice(0, 200)}`,
    );
  }
  return { sessionId: body.sessionId!, url: body.url ?? "", demo: body.demo ?? false };
}

export interface PostSeedResult {
  encounterId: string;
  findingIds: string[];
}

export interface AuditChainResult {
  actions: string[];
  rowCount: number;
  brokenAt: string | null;
}

/** Read and verify one encounter's audit chain in the portal runtime. */
export function readAuditChain(encounterId: string): AuditChainResult {
  const cwd = resolvePortalCwd();
  const script = [
    "import { prisma } from './src/lib/prisma';",
    "import { verifyChain } from './src/lib/audit-chain';",
    "(async () => {",
    `  const rows = await prisma.auditTrailEntry.findMany({ where: { encounterId: '${encounterId}' }, orderBy: [{ timestamp: 'asc' }, { eventId: 'asc' }] });`,
    "  console.log(JSON.stringify({ actions: rows.map((row) => row.action), rowCount: rows.length, brokenAt: verifyChain(rows) }));",
    "  await prisma.$disconnect();",
    "})()",
  ].join(" ");
  const r = spawnSync("pnpm", ["exec", "tsx", "-e", script], {
    cwd,
    env: process.env,
    encoding: "utf8",
  });
  if (r.status !== 0) {
    throw new Error(`audit-chain read failed: ${r.stderr || r.stdout}`);
  }
  const line = r.stdout
    .split("\n")
    .reverse()
    .find((candidate) => candidate.trim().startsWith("{"));
  if (!line) throw new Error(`audit-chain read produced no JSON: ${r.stdout}`);
  return JSON.parse(line) as AuditChainResult;
}

/** Spawn the post-seed script and parse the JSON it prints on the last line. */
export function postSeedEncounter(
  tenantSlug: string = DEFAULT_TENANT_SLUG,
  userEmail: string = DEFAULT_USER_EMAIL,
  tenantId?: string,
): PostSeedResult {
  const cwd = resolvePortalCwd();
  const r: SpawnSyncReturns<string> = spawnSync(
    "pnpm",
    ["exec", "tsx", "scripts/e2e_acceptance_post_seed.ts"],
    {
      cwd,
      env: {
        ...process.env,
        E2E_TENANT_SLUG: tenantSlug,
        E2E_USER_EMAIL: userEmail,
        ...(tenantId ? { E2E_TENANT_ID: tenantId } : {}),
      },
      encoding: "utf8",
    },
  );
  if (r.status !== 0) {
    throw new Error(`post-seed failed: ${r.stderr || r.stdout}`);
  }
  const out = r.stdout.trim();
  const jsonStart = out.lastIndexOf("{");
  const jsonEnd = out.lastIndexOf("}");
  if (jsonStart === -1 || jsonEnd === -1) {
    throw new Error(`post-seed produced no JSON: ${out}`);
  }
  return JSON.parse(out.slice(jsonStart, jsonEnd + 1)) as PostSeedResult;
}

/** Spawn the seed script (wipes + re-creates the e2e tenant + user). */
export interface SeedAcceptanceResult {
  tenantId: string;
  tenantSlug: string;
  userId: string;
  userEmail: string;
}

export function seedAcceptance(
  tenantSlug: string = DEFAULT_TENANT_SLUG,
  userEmail: string = DEFAULT_USER_EMAIL,
  attachMembership = false,
): SeedAcceptanceResult {
  const cwd = resolvePortalCwd();
  const r = spawnSync(
    "pnpm",
    ["exec", "tsx", "scripts/e2e_acceptance_seed.ts"],
    {
      cwd,
      env: {
        ...process.env,
        E2E_TENANT_SLUG: tenantSlug,
        E2E_USER_EMAIL: userEmail,
        E2E_ATTACH_MEMBERSHIP: attachMembership ? "1" : "0",
      },
      encoding: "utf8",
    },
  );
  if (r.status !== 0) {
    throw new Error(`seed failed: ${r.stderr || r.stdout}`);
  }
  const jsonStart = r.stdout.lastIndexOf("{");
  const jsonEnd = r.stdout.lastIndexOf("}");
  if (jsonStart === -1 || jsonEnd === -1) {
    throw new Error(`seed produced no JSON: ${r.stdout}`);
  }
  return JSON.parse(r.stdout.slice(jsonStart, jsonEnd + 1)) as SeedAcceptanceResult;
}
