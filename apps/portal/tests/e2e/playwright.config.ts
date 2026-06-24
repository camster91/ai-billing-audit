// Playwright config for the marketing -> portal -> findings E2E smoke flow.
//
// Run from apps/portal with the dev server already up at :3000:
//
//   pnpm test:e2e                    # all 8 smoke steps + ordering
//   pnpm test:e2e -- --headed        # visible browser
//   pnpm test:e2e -- --project=chromium
//   pnpm test:e2e -- smoke.spec.ts   # single file
//
// CI: the workflow in .github/workflows/e2e.yml boots the dev server
// before running `npx playwright test --reporter=html,github`. Report
// and traces are uploaded as artifacts.

import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.PORT ?? 3000);
const BASE_URL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: ".",
  // Glob pattern: only pick up *.spec.ts so helpers/fixtures don't run.
  testMatch: /.*\.spec\.ts$/,
  // Run tests in file order — step 01 must precede step 02, etc.
  // We use a single file with ordered tests rather than across files so
  // order is preserved without relying on glob ordering.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Local runs: short suite, no throttle.
  // CI: 5 minute cap; the suite is designed to finish < 2 min.
  timeout: process.env.CI ? 5 * 60_000 : 90_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI
    ? [
        ["list"],
        ["github"],
        ["html", { open: "never", outputFolder: "playwright-report" }],
      ]
    : [["list"]],

  use: {
    baseURL: BASE_URL,
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Sandbox is unavailable in CI; harmless locally.
        launchOptions: { args: ["--no-sandbox", "--disable-dev-shm-usage"] },
      },
    },
  ],
});
