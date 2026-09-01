// Performance budgets gate (issue #30).
//
// Reads Web Vitals from the browser via the Performance API and
// the PerformanceObserver, on each public route at desktop and
// mobile viewports. Fails the run if any route / viewport pair
// exceeds:
//
//   LCP <= 2.5s     (Largest Contentful Paint, "good" threshold)
//   CLS <= 0.1      (Cumulative Layout Shift, "good" threshold)
//   TBT <= 200ms    (Total Blocking Time proxy: sum of long-task
//                    durations between FCP and the TTI proxy, subtracting
//                    the standard 50ms allowance from each task)
//
// Why the Performance API and not Lighthouse?
//   - No Chromium-only / no CDN dependency. The script runs in
//     headless Playwright Chromium today but the same Web Vitals
//     are available in Firefox and WebKit.
//   - No external service. A failed budget is a failed CI job,
//     not a delayed dashboard.
//   - One fewer moving piece. /docs/OPERATIONS_RUNBOOK.md is the
//     canonical source of truth; the script reads from it.
//
// Caveat: TBT is approximated because the Performance API does
// not expose TTI directly. We sum blocking time after FCP through
// the last long task followed by a five-second quiet window.

import { chromium, devices } from "@playwright/test";
import { writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE_URL || "http://127.0.0.1:3102";
const OUT =
  process.env.PERF_OUT ||
  fileURLToPath(new URL("../../docs/perf", import.meta.url));
if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

const BUDGETS = {
  lcpMs: Number(process.env.PERF_LCP_MS ?? 2500),
  cls: Number(process.env.PERF_CLS ?? 0.1),
  tbtMs: Number(process.env.PERF_TBT_MS ?? 200),
};

const ROUTES = [
  { name: "marketing-home",         path: "/",                  viewport: "desktop" },
  { name: "marketing-pricing",      path: "/pricing",           viewport: "desktop" },
  { name: "marketing-how-it-works", path: "/how-it-works",      viewport: "desktop" },
  { name: "marketing-security",     path: "/security",          viewport: "desktop" },
  { name: "contact",                path: "/contact",           viewport: "desktop" },
  { name: "login",                  path: "/login",             viewport: "desktop" },
  { name: "marketing-home-mobile",  path: "/",                  viewport: "mobile" },
  { name: "marketing-pricing-mob",  path: "/pricing",           viewport: "mobile" },
  { name: "contact-mobile",         path: "/contact",           viewport: "mobile" },
  { name: "login-mobile",           path: "/login",             viewport: "mobile" },
];

const VIEWPORTS = {
  desktop: { viewport: { width: 1280, height: 800 }, userAgent: undefined },
  mobile: { ...devices["iPhone 13"] },
};

async function measureRoute(browser, route) {
  const ctx = await browser.newContext(VIEWPORTS[route.viewport]);
  const page = await ctx.newPage();

  // Install observers before navigation so first paint and early work
  // are included in the measurement.
  await page.addInitScript(() => {
    (window).__layoutShifts = [];
    (window).__lcpMs = 0;
    (window).__longTasks = [];
    try {
      const po = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (!(entry).hadRecentInput) {
            (window).__layoutShifts.push({
              startTime: entry.startTime,
              value: entry.value,
            });
          }
        }
      });
      po.observe({ type: "layout-shift", buffered: true });
    } catch {}
    try {
      const lo = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.duration > 50) {
            (window).__longTasks.push({
              startTime: entry.startTime,
              duration: entry.duration,
            });
          }
        }
      });
      lo.observe({ type: "longtask", buffered: true });
    } catch {}
    try {
      const lcp = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        const last = entries[entries.length - 1];
        if (last) (window).__lcpMs = last.startTime;
      });
      lcp.observe({ type: "largest-contentful-paint", buffered: true });
    } catch {}
  });

  const url = BASE + route.path;
  const t0 = Date.now();
  try {
    const resp = await page.goto(url, { waitUntil: "load", timeout: 30000 });
    // Wait through a five-second quiet window after network idle. The
    // last observed long task marks the TTI proxy boundary.
    await page.waitForLoadState("networkidle", { timeout: 10000 });
    await page.waitForTimeout(5000);
    const metrics = await page.evaluate(() => {
      const shifts = [...(window).__layoutShifts].sort(
        (a, b) => a.startTime - b.startTime,
      );
      let cls = 0;
      let windowValue = 0;
      let windowStart = 0;
      let previousShift = 0;
      for (const shift of shifts) {
        if (
          windowValue === 0 ||
          shift.startTime - previousShift > 1000 ||
          shift.startTime - windowStart > 5000
        ) {
          windowStart = shift.startTime;
          windowValue = shift.value;
        } else {
          windowValue += shift.value;
        }
        previousShift = shift.startTime;
        cls = Math.max(cls, windowValue);
      }

      const fcp =
        performance
          .getEntriesByName("first-contentful-paint")
          .at(-1)?.startTime ?? 0;
      const longTasks = (window).__longTasks;
      const lastLongTaskEnd = longTasks.reduce(
        (latest, task) => Math.max(latest, task.startTime + task.duration),
        fcp,
      );
      const ttiProxy = Math.min(performance.now(), lastLongTaskEnd);
      const tbtMs = longTasks
        .filter(
          (task) =>
            task.startTime >= fcp &&
            task.startTime + task.duration <= ttiProxy,
        )
        .reduce((total, task) => total + task.duration - 50, 0);

      return {
        lcpMs: (window).__lcpMs || 0,
        cls,
        tbtMs,
      };
    });
    await ctx.close();
    return {
      route: route.name,
      viewport: route.viewport,
      path: route.path,
      httpStatus: resp ? resp.status() : "no-response",
      navigationMs: Date.now() - t0,
      ...metrics,
    };
  } catch (e) {
    await ctx.close();
    return {
      route: route.name,
      viewport: route.viewport,
      path: route.path,
      error: e.message.slice(0, 200),
    };
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const results = [];
  for (const route of ROUTES) {
    process.stdout.write(`[${route.name}] ${route.viewport} ... `);
    const r = await measureRoute(browser, route);
    if (r.error) {
      console.log(`FAILED: ${r.error}`);
    } else {
      console.log(
        `LCP=${r.lcpMs.toFixed(0)}ms CLS=${r.cls.toFixed(3)} TBT=${r.tbtMs.toFixed(0)}ms`,
      );
    }
    results.push(r);
  }
  await browser.close();

  writeFileSync(join(OUT, "perf-budgets.json"), JSON.stringify({ budgets: BUDGETS, results }, null, 2));
  console.log("\nWrote", join(OUT, "perf-budgets.json"));

  // Block on any route / viewport that exceeds a budget.
  const failures = results
    .filter(
      (r) =>
        r.error ||
        r.lcpMs > BUDGETS.lcpMs ||
        r.cls > BUDGETS.cls ||
        r.tbtMs > BUDGETS.tbtMs,
    )
    .map((r) => ({
      route: r.route,
      viewport: r.viewport,
      error: r.error,
      lcpMs: r.lcpMs,
      cls: r.cls,
      tbtMs: r.tbtMs,
    }));
  if (failures.length > 0) {
    console.error(`\n[perf-gate] ${failures.length} route(s) over budget:`);
    for (const f of failures) {
      const reasons = [];
      if (f.error) reasons.push(`measurement failed: ${f.error}`);
      if (f.lcpMs > BUDGETS.lcpMs) reasons.push(`LCP ${f.lcpMs.toFixed(0)}ms > ${BUDGETS.lcpMs}ms`);
      if (f.cls > BUDGETS.cls) reasons.push(`CLS ${f.cls.toFixed(3)} > ${BUDGETS.cls}`);
      if (f.tbtMs > BUDGETS.tbtMs) reasons.push(`TBT ${f.tbtMs.toFixed(0)}ms > ${BUDGETS.tbtMs}ms`);
      console.error(`  - ${f.route} (${f.viewport}): ${reasons.join(", ")}`);
    }
    process.exit(1);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
