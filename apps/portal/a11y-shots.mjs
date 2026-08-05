import { chromium } from "playwright";
import { mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE_URL || "http://127.0.0.1:3102";
const COOKIE = process.env.SESSION_TOKEN;
const OUT = process.env.A11Y_OUT || fileURLToPath(new URL("../../docs/a11y/screenshots", import.meta.url));
if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

const ROUTES = [
  { name: "marketing-home",         path: "/",                       auth: false },
  { name: "marketing-pricing",      path: "/pricing",                auth: false },
  { name: "marketing-how-it-works", path: "/how-it-works",           auth: false },
  { name: "marketing-security",     path: "/security",               auth: false },
  { name: "login",                  path: "/login",                  auth: false },
  { name: "dashboard",              path: "/dashboard",              auth: true },
  { name: "encounters-list",        path: "/encounters",             auth: true },
  { name: "encounter-detail",       path: "/encounters/enc-list-0060", auth: true },
  { name: "findings",               path: "/findings",               auth: true },
  { name: "billing",                path: "/billing",                auth: true },
  { name: "settings",               path: "/settings",               auth: true },
  { name: "team",                   path: "/team",                   auth: true },
  { name: "onboarding",             path: "/portal/onboarding",      auth: true },
  { name: "portal-billing",         path: "/portal/billing",         auth: true },
];

async function main() {
  const browser = await chromium.launch({ headless: true });
  // Build one context with auth cookies for protected routes
  const publicCtx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "dark" });
  const authCtx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "dark" });
  if (COOKIE) {
    await authCtx.addCookies([{ name: "authjs.session-token", value: COOKIE, domain: "127.0.0.1", path: "/", httpOnly: true, secure: false, sameSite: "Lax" }]);
  }
  for (const route of ROUTES) {
    const ctx = route.auth ? authCtx : publicCtx;
    const page = await ctx.newPage();
    const url = BASE + route.path;
    process.stdout.write(`[${route.name}] ${url} ... `);
    try {
      const resp = await page.goto(url, { waitUntil: "load", timeout: 30000 });
      await page.waitForTimeout(1500);
      const shot = join(OUT, `${route.name}.png`);
      await page.screenshot({ path: shot, fullPage: false });
      const h1 = await page.locator("h1").first().textContent().catch(() => "(none)");
      console.log(`HTTP ${resp.status()} h1=${(h1 || "").trim().slice(0, 40)}`);
    } catch (e) {
      console.log(`FAIL: ${e.message.slice(0, 80)}`);
    }
    await page.close();
  }
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
