// Accessibility audit script. Runs axe-core against every public + authed route
// in apps/portal. Outputs per-page violation/incomplete reports as JSON.
import { chromium } from "playwright";
import { writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";

const BASE = process.env.BASE_URL || "http://127.0.0.1:3102";
const COOKIE = process.env.SESSION_TOKEN;
const OUT = process.env.A11Y_OUT || "/Users/biancabienaime/projects/ai-billing-audit/docs/a11y";
if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

const ROUTES = [
  // public marketing
  { name: "marketing-home",         path: "/",                       auth: false },
  { name: "marketing-pricing",      path: "/pricing",                auth: false },
  { name: "marketing-how-it-works", path: "/how-it-works",           auth: false },
  { name: "marketing-security",     path: "/security",               auth: false },
  { name: "login",                  path: "/login",                  auth: false },
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
];

const AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.0/axe.min.js";

async function injectAxe(page) {
  await page.evaluate((src) => {
    return new Promise((resolve, reject) => {
      if (window.axe) return resolve();
      const s = document.createElement("script");
      s.src = src;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("axe failed to load"));
      document.head.appendChild(s);
    });
  }, AXE_CDN);
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
      const resp = await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
      const status = resp ? resp.status() : "no-response";
      // give dynamic content time
      await page.waitForTimeout(800);
      try {
        await injectAxe(page);
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
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
