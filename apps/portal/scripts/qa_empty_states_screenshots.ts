// Capture empty-state screenshots for a fresh QA tenant.
//
// Loads the auth cookie (printed by qa_empty_states_session.ts) and
// hits each portal page in turn. Saves PNGs under
// docs/screenshots/portal/empty/ with stable names so the QA doc
// can reference them by relative path.
//
// Run from apps/portal:
//   QA_SESSION_COOKIE="authjs.session-token=<hex>" pnpm exec tsx scripts/qa_empty_states_screenshots.ts
//
// The script will also fall back to reading /tmp/qa_empty_session.json
// (produced by the previous step) if the env var is not set.

import { chromium } from "playwright";
import { readFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

interface SessionInfo {
  cookieName: string;
  cookieValue: string;
  userEmail: string;
  tenantSlug: string;
}

function loadSession(): SessionInfo {
  if (process.env.QA_SESSION_COOKIE) {
    // env form: "authjs.session-token=<hex>"
    const [name, ...rest] = process.env.QA_SESSION_COOKIE.split("=");
    return {
      cookieName: name,
      cookieValue: rest.join("="),
      userEmail: process.env.QA_USER_EMAIL ?? "(from env)",
      tenantSlug: process.env.QA_TENANT_SLUG ?? "(from env)",
    };
  }
  const json = readFileSync("/tmp/qa_empty_session.json", "utf8");
  return JSON.parse(json) as SessionInfo;
}

async function main() {
  const session = loadSession();
  const base = process.env.QA_BASE_URL ?? "http://127.0.0.1:3000";
  const outDir = resolve(
    process.env.QA_OUT_DIR ??
      "../../docs/screenshots/portal/empty/qa-fresh-signup",
  );
  mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 957 },
    deviceScaleFactor: 1,
  });
  await context.addCookies([
    {
      name: session.cookieName,
      value: session.cookieValue,
      domain: "127.0.0.1",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);

  const pages: Array<{ path: string; name: string; waitFor?: string }> = [
    { path: "/dashboard", name: "qa-empty__dashboard.png" },
    { path: "/encounters", name: "qa-empty__encounters.png" },
    { path: "/findings", name: "qa-empty__findings.png" },
    { path: "/billing", name: "qa-empty__billing.png" },
  ];

  const page = await context.newPage();
  const results: Array<{
    path: string;
    out: string;
    title: string;
    consoleErrors: string[];
    failedRequests: string[];
  }> = [];

  for (const p of pages) {
    const url = `${base}${p.path}`;
    const consoleErrors: string[] = [];
    const failedRequests: string[] = [];
    page.removeAllListeners("console");
    page.removeAllListeners("requestfailed");
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("requestfailed", (req) => {
      failedRequests.push(`${req.method()} ${req.url()} — ${req.failure()?.errorText ?? ""}`);
    });

    const resp = await page.goto(url, { waitUntil: "networkidle" });
    await page.waitForLoadState("domcontentloaded");
    // Give the page a beat for any client-component hydration so the
    // empty state is fully rendered (not the loading skeleton).
    await page.waitForTimeout(400);

    const out = join(outDir, p.name);
    await page.screenshot({ path: out, fullPage: true });

    const title = await page.title();
    results.push({
      path: p.path,
      out,
      title,
      consoleErrors,
      failedRequests,
    });
    console.log(
      `[qa-empty-shot] ${p.path} -> ${out} (HTTP ${resp?.status() ?? "?"})`,
    );
  }

  await browser.close();
  console.log(
    "[qa-empty-shot] " + JSON.stringify(results, null, 2) + "\n",
  );
}

main().catch((e) => {
  console.error("[qa-empty-shot] failed:", e);
  process.exit(1);
});
