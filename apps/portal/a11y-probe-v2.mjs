// Better a11y diagnostic — uses Playwright's accessibility snapshot for ARIA
// + a real color probe that walks up to find the actual painted background.
import { chromium } from "@playwright/test";
import { writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE_URL || "http://127.0.0.1:3102";
const COOKIE = process.env.SESSION_TOKEN;
const OUT = process.env.A11Y_OUT || fileURLToPath(new URL("../../docs/a11y", import.meta.url));
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

async function runProbe(page) {
  return await page.evaluate(() => {
    const out = {};
    const h = document.querySelectorAll("h1,h2,h3,h4,h5,h6");
    out.headings = Array.from(h).map(x => ({ level: x.tagName, text: (x.textContent||"").trim().slice(0, 80) }));
    out.h1Count = document.querySelectorAll("h1").length;
    out.images = Array.from(document.querySelectorAll("img")).map(i => ({
      alt: i.getAttribute("alt"),
      ariaHidden: i.getAttribute("aria-hidden"),
      role: i.getAttribute("role"),
    }));
    out.unlabeledInputs = Array.from(document.querySelectorAll("input,select,textarea")).filter(el => {
      if (el.type === "hidden") return false;
      if (el.getAttribute("aria-label") || el.getAttribute("aria-labelledby")) return false;
      if (el.id && document.querySelector('label[for="' + el.id + '"]')) return false;
      if (el.closest("label")) return false;
      return true;
    }).map(el => ({ tag: el.tagName, type: el.type||"", id: el.id, name: el.name }));
    out.unnamedButtons = Array.from(document.querySelectorAll("button")).filter(b => {
      return !b.textContent.trim() && !b.getAttribute("aria-label") && !b.getAttribute("aria-labelledby") && !b.getAttribute("title");
    }).length;
    out.unnamedLinks = Array.from(document.querySelectorAll("a[href]")).filter(a => {
      return !a.textContent.trim() && !a.getAttribute("aria-label") && !a.getAttribute("aria-labelledby") && !a.getAttribute("title");
    }).length;
    out.landmarks = {
      header: document.querySelectorAll("header").length,
      nav: document.querySelectorAll("nav").length,
      main: document.querySelectorAll("main").length,
      footer: document.querySelectorAll("footer").length,
      aside: document.querySelectorAll("aside").length,
    };
    out.htmlLang = document.documentElement.getAttribute("lang");
    out.liveRegions = Array.from(document.querySelectorAll('[aria-live], [role="alert"], [role="status"]')).length;
    out.pageTitle = document.title;
    const vp = document.querySelector('meta[name="viewport"]');
    out.viewport = vp ? vp.getAttribute("content") : null;

    // Color probe — better bg detection.
    const parseRGB = (s) => {
      const m = s.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const parts = m[1].split(",").map(x => parseFloat(x.trim()));
      return { r: parts[0], g: parts[1], b: parts[2], a: parts[3] ?? 1 };
    };
    const blend = (fg, bg) => {
      // alpha compositing
      const a = fg.a;
      return {
        r: fg.r * a + bg.r * (1 - a),
        g: fg.g * a + bg.g * (1 - a),
        b: fg.b * a + bg.b * (1 - a),
      };
    };
    const lum = (rgb) => {
      const a = [rgb.r, rgb.g, rgb.b].map(v => {
        v = v / 255;
        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
      });
      return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2];
    };
    const findBg = (el) => {
      // Walk from the element up; for each ancestor with a non-transparent
      // backgroundColor, treat it as a paint layer on top of the previous.
      // Paint order: outermost first (the page), each subsequent ancestor
      // composites on top with its own alpha.
      const layers = [];
      let n = el;
      while (n) {
        const s = getComputedStyle(n);
        if (s.backgroundColor && s.backgroundColor !== "rgba(0, 0, 0, 0)") {
          layers.push({ bg: parseRGB(s.backgroundColor), el: n.tagName + (n.className ? "." + String(n.className).slice(0, 30) : "") });
        }
        n = n.parentElement;
      }
      // layers[0] is the innermost (closest to el) = painted on top.
      // Paint from outermost (page) inward, blending the next layer on top.
      // We start from the LAST element in the array (outermost, e.g. BODY)
      // and composite each next-closer ancestor on top.
      let result = { r: 255, g: 255, b: 255, a: 1 };
      for (let i = layers.length - 1; i >= 0; i--) {
        result = blend(layers[i].bg, result);
      }
      return result;
    };
    const candidates = document.querySelectorAll("p, span, a, button, label, h1, h2, h3, h4, h5, h6, li, td, th, dt, dd");
    const ccResults = [];
    let ccount = 0;
    for (const el of candidates) {
      if (ccount >= 60) break;
      const text = (el.textContent||"").trim();
      if (!text || text.length < 2) continue;
      const style = getComputedStyle(el);
      const fg = parseRGB(style.color);
      if (!fg) continue;
      if (fg.a < 1) continue; // skip text with transparency — unreliable
      const bg = findBg(el);
      const fontSize = parseFloat(style.fontSize);
      const fontWeight = parseInt(style.fontWeight, 10) || 400;
      const l1 = lum(fg) + 0.05;
      const l2 = lum(bg) + 0.05;
      const ratio = l1 > l2 ? l1 / l2 : l2 / l1;
      const isLarge = fontSize >= 18 || (fontSize >= 14 && fontWeight >= 700);
      const required = isLarge ? 3 : 4.5;
      if (ratio < required) {
        ccResults.push({
          text: text.slice(0, 50),
          ratio: ratio.toFixed(2),
          required,
          fontSize, fontWeight,
          tag: el.tagName,
          fg: style.color,
        });
        ccount++;
      }
    }
    out.colorProbe = ccResults;
    return out;
  });
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
      const resp = await page.goto(url, { waitUntil: "load", timeout: 30000 });
      await page.waitForTimeout(800);
      const r = await runProbe(page);
      r.route = route.name; r.path = route.path; r.httpStatus = resp ? resp.status() : null;
      all.push(r);
      const issues = (r.unlabeledInputs?.length||0) + r.unnamedButtons + r.unnamedLinks + (r.colorProbe?.length||0);
      console.log(`h1=${r.h1Count} inputs=${r.unlabeledInputs?.length||0} btns=${r.unnamedButtons} links=${r.unnamedLinks} contrast=${r.colorProbe?.length||0}`);
    } catch (e) {
      console.log(`FAIL: ${e.message.slice(0, 80)}`);
      all.push({ route: route.name, path: route.path, error: e.message });
    }
  }
  writeFileSync(join(OUT, "manual-v2.json"), JSON.stringify(all, null, 2));
  console.log("\nWrote", join(OUT, "manual-v2.json"));
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
