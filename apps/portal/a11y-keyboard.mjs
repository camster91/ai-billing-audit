// Keyboard navigation audit. For each route: tab through every focusable
// element, record (1) is the focus indicator visible (2) does the order
// make visual sense (3) are there focus traps.
import { chromium } from "playwright";
import { writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";

const BASE = process.env.BASE_URL || "http://127.0.0.1:3102";
const COOKIE = process.env.SESSION_TOKEN;
const OUT = "/Users/biancabienaime/projects/ai-billing-audit/docs/a11y";
if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

const ROUTES = [
  { name: "marketing-home",         path: "/",                       auth: false },
  { name: "marketing-pricing",      path: "/pricing",                auth: false },
  { name: "marketing-how-it-works", path: "/how-it-works",           auth: false },
  { name: "marketing-security",     path: "/security",               auth: false },
  { name: "login",                  path: "/login",                  auth: false },
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

async function auditKeyboard(page, route) {
  // Reset to top, focus body, then tab through.
  await page.evaluate(() => { window.scrollTo(0, 0); document.body.focus(); });
  const elements = [];
  const maxTabs = 50;
  for (let i = 0; i < maxTabs; i++) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      const a = document.activeElement;
      if (!a || a === document.body) return null;
      const s = getComputedStyle(a);
      const rect = a.getBoundingClientRect();
      return {
        tag: a.tagName,
        type: a.getAttribute("type") || "",
        text: (a.textContent || a.getAttribute("aria-label") || a.getAttribute("title") || "").trim().slice(0, 60),
        href: a.getAttribute("href") || "",
        outlineWidth: s.outlineWidth,
        outlineStyle: s.outlineStyle,
        outlineColor: s.outlineColor,
        boxShadow: s.boxShadow.slice(0, 80),
        // visible-on-screen check
        visible: rect.width > 0 && rect.height > 0,
        rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
      };
    });
    if (!info) break;
    elements.push(info);
  }
  return elements;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "dark" });
  if (COOKIE) {
    await context.addCookies([{
      name: "authjs.session-token", value: COOKIE, domain: "127.0.0.1",
      path: "/", httpOnly: true, secure: false, sameSite: "Lax",
    }]);
  }
  const page = await context.newPage();
  const all = [];
  for (const route of ROUTES) {
    const url = BASE + route.path;
    process.stdout.write(`[${route.name}] ... `);
    try {
      const resp = await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
      await page.waitForTimeout(800);
      const tabOrder = await auditKeyboard(page, route);
      // Detect focus indicator visibility — count elements with no outline AND no box-shadow
      const noFocusIndicator = tabOrder.filter(e => {
        const ow = e.outlineWidth;
        const noOutline = ow === "0px" || e.outlineStyle === "none";
        const noShadow = e.boxShadow === "none" || e.boxShadow === "";
        return noOutline && noShadow;
      });
      all.push({
        route: route.name,
        path: route.path,
        httpStatus: resp ? resp.status() : null,
        tabCount: tabOrder.length,
        noFocusIndicatorCount: noFocusIndicator.length,
        noFocusIndicatorSamples: noFocusIndicator.slice(0, 5).map(e => ({ tag: e.tag, text: e.text })),
        tabOrder: tabOrder,
      });
      console.log(`tabs=${tabOrder.length} noFocusIndicator=${noFocusIndicator.length}`);
    } catch (e) {
      console.log(`FAIL: ${e.message.slice(0, 80)}`);
      all.push({ route: route.name, path: route.path, error: e.message });
    }
  }
  writeFileSync(join(OUT, "keyboard-results.json"), JSON.stringify(all, null, 2));
  console.log("\nWrote", join(OUT, "keyboard-results.json"));
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
