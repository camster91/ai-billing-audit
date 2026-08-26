// Accessibility audit script. Runs axe-core against every public + authed route
// in apps/portal. Outputs per-page violation/incomplete reports as JSON.
import { chromium } from "playwright";
import { writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE_URL || "http://127.0.0.1:3102";
const COOKIE = process.env.SESSION_TOKEN;
const OUT = process.env.A11Y_OUT || fileURLToPath(new URL("../../docs/a11y", import.meta.url));
if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

const ROUTES = [
  // public marketing
  { name: "marketing-home",         path: "/",                       auth: false },
  { name: "marketing-pricing",      path: "/pricing",                auth: false },
  { name: "marketing-how-it-works", path: "/how-it-works",           auth: false },
  { name: "marketing-security",     path: "/security",               auth: false },
  { name: "contact",                path: "/contact",                auth: false },
  { name: "login",                  path: "/login",                  auth: false },
  { name: "verify-request",         path: "/verify-request",         auth: false },
  { name: "auth-error",             path: "/auth/error?error=Verification", auth: false },
  // public but not for the marketing funnel
  { name: "readyz",                 path: "/readyz",                 auth: false },
  // authed portal
  { name: "dashboard",              path: "/dashboard",              auth: true },
  { name: "encounters-list",        path: "/encounters",             auth: true },
  { name: "encounter-detail",       path: "/encounters/enc-list-0001", auth: true },
  { name: "findings",               path: "/findings",               auth: true },
  { name: "billing",                path: "/billing",                auth: true },
  { name: "settings",               path: "/settings",               auth: true },
  { name: "team",                   path: "/team",                   auth: true },
  { name: "onboarding",             path: "/portal/onboarding",      auth: true },
  { name: "portal-billing",         path: "/portal/billing",         auth: true },
  { name: "not-found",              path: "/this-route-does-not-exist-9e3a", auth: false },
];

const AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.0/axe.min.js";

async function loadAxeSource() {
  const response = await fetch(AXE_CDN);
  if (!response.ok) {
    throw new Error(`axe download failed with HTTP ${response.status}`);
  }
  return response.text();
}

async function injectAxe(page, axeSource) {
  // Evaluate through Playwright's browser protocol rather than adding a
  // <script> tag, so the application's CSP remains unchanged and enforced.
  await page.evaluate(axeSource);
  const loaded = await page.evaluate(() => Boolean(window.axe));
  if (!loaded) throw new Error("axe failed to initialize");
}

async function runAxe(page) {
  return await page.evaluate(async () => {
    if (!window.axe) throw new Error("axe not loaded");
    const result = await window.axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    });
    return {
      url: window.location.href,
      scannedAt: new Date().toISOString(),
      summary: {
        violations: result.violations.length,
        incomplete: result.incomplete.length,
        passes: result.passes.length,
      },
      violations: result.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        description: v.description,
        help: v.help,
        helpUrl: v.helpUrl,
        nodeCount: v.nodes.length,
        samples: v.nodes.slice(0, 5).map((n) => ({
          target: n.target.join(" > "),
          html: (n.html || "").slice(0, 200),
          failureSummary: n.failureSummary,
        })),
      })),
      incomplete: result.incomplete.map((v) => ({
        id: v.id,
        impact: v.impact,
        description: v.description,
        help: v.help,
        helpUrl: v.helpUrl,
        nodeCount: v.nodes.length,
        samples: v.nodes.slice(0, 3).map((n) => ({
          target: n.target.join(" > "),
          html: (n.html || "").slice(0, 200),
        })),
      })),
    };
  });
}

async function main() {
  const axeSource = await loadAxeSource();
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: "dark",
  });
  if (COOKIE) {
    await context.addCookies([{
      name: "authjs.session-token",
      value: COOKIE,
      domain: "127.0.0.1",
      path: "/",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    }]);
  }
  const page = await context.newPage();

  const allResults = [];
  for (const route of ROUTES) {
    const url = BASE + route.path;
    process.stdout.write(`[${route.name}] ${url} ... `);
    try {
      const resp = await page.goto(url, { waitUntil: "load", timeout: 30000 });
      const status = resp ? resp.status() : "no-response";
      // give dynamic content time
      await page.waitForTimeout(800);
      try {
        await injectAxe(page, axeSource);
        const r = await runAxe(page);
        r.route = route.name;
        r.path = route.path;
        r.httpStatus = status;
        allResults.push(r);
        console.log(`HTTP ${status} | V=${r.summary.violations} I=${r.summary.incomplete} P=${r.summary.passes}`);
      } catch (axeErr) {
        console.log(`AXE FAILED: ${axeErr.message}`);
        allResults.push({ route: route.name, path: route.path, httpStatus: status, error: axeErr.message });
      }
    } catch (e) {
      console.log(`NAV FAILED: ${e.message.slice(0, 80)}`);
      allResults.push({ route: route.name, path: route.path, error: e.message });
    }
  }

  writeFileSync(join(OUT, "axe-results.json"), JSON.stringify(allResults, null, 2));
  console.log("\nWrote", join(OUT, "axe-results.json"));

  // Block when an expected route could not be scanned or when axe
  // reports a serious / critical violation.
  const blockOnViolations = process.env.ZORVA_A11Y_GATE !== "0";
  let gateFailed = false;
  if (blockOnViolations) {
    const scanErrors = allResults.filter((r) => r.error);
    const blocking = allResults.flatMap((r) =>
      (r.violations ?? [])
        .filter((v) => v.impact === "serious" || v.impact === "critical")
        .map((v) => ({
          route: r.route,
          path: r.path,
          id: v.id,
          impact: v.impact,
          nodeCount: v.nodeCount,
        })),
    );

    if (scanErrors.length > 0) {
      gateFailed = true;
      console.error(`\n[axe-gate] ${scanErrors.length} route scan(s) failed:`);
      for (const failure of scanErrors) {
        console.error(`  - ${failure.route} (${failure.path}): ${failure.error}`);
      }
    }
    if (blocking.length > 0) {
      gateFailed = true;
      console.error(`\n[axe-gate] ${blocking.length} serious/critical violation(s):`);
      for (const violation of blocking) {
        console.error(
          `  - ${violation.route} (${violation.path}) ${violation.id} [${violation.impact}] x${violation.nodeCount}`,
        );
      }
    }
  }

  await browser.close();
  if (gateFailed) process.exitCode = 1;
}

main().catch((e) => { console.error(e); process.exit(1); });
