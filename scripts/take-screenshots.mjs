// Re-capture full-page screenshots of the demo dashboard after the
// visual-issue fix pass (kanban t_956a359a). Output:
//   docs/screenshots/encounter-index.png
//   docs/screenshots/encounter-<id>.png for every registered encounter
// Captures 1440x900 @ deviceScaleFactor=2 (2880x1800 native) and
// records any console errors / failed network requests during the
// capture so the worker can verify the live page is clean.

import { chromium } from 'playwright';
import { writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const OUT_DIR = join(ROOT, 'docs', 'screenshots');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8765';

mkdirSync(OUT_DIR, { recursive: true });

async function discoverEncounters(page) {
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  const ids = await page.$$eval('.encounter-card__id a', (els) =>
    els.map((a) => a.getAttribute('href').replace(/^\/encounter\//, ''))
  );
  return ids;
}

async function capture(page, path, label) {
  const consoleErrors = [];
  const failedRequests = [];
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  page.on('requestfailed', (r) => {
    const url = r.url();
    if (!/favicon\.ico$/.test(url)) failedRequests.push(`${r.failure()?.errorText} ${url}`);
  });
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(150);
  const out = join(OUT_DIR, `encounter-${label}.png`);
  await page.screenshot({ path: out, fullPage: true });
  return { path: out, consoleErrors, failedRequests };
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();
  const ids = await discoverEncounters(page);
  console.log(`Discovered ${ids.length} encounter(s): ${ids.join(', ')}`);

  const results = [];
  results.push(await capture(page, '/', 'index'));
  for (const id of ids) {
    results.push(await capture(page, `/encounter/${id}`, id));
  }
  await browser.close();

  const summary = {
    base: BASE,
    out_dir: OUT_DIR,
    n_registered: ids.length,
    results: results.map((r) => ({
      path: r.path,
      consoleErrors: r.consoleErrors,
      failedRequests: r.failedRequests,
    })),
  };
  writeFileSync(join(OUT_DIR, 'screenshot-run.json'), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary, null, 2));
})();
