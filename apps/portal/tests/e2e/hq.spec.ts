import { spawnSync } from "node:child_process";

import { expect, test } from "@playwright/test";

import {
  loginViaMagicLink,
  resolvePortalCwd,
} from "./helpers";

const HQ_USER_EMAIL = "e2e+hq-owner@ai-billing-audit.test";
const HQ_TENANT_SLUG = "e2e-hq-clinic";
const SYNTHETIC_LEAD_EMAIL = "practice.manager@e2e-alberta-clinic.test";
const SYNTHETIC_CLINIC_NAME = "E2E Alberta Primary Care";

function changePlatformRole(action: "grant" | "revoke") {
  const args = [
    "--import",
    "tsx",
    "scripts/manage-platform-role.ts",
    "--action",
    action,
    "--email",
    HQ_USER_EMAIL,
    "--granted-by",
    "e2e-browser-gate",
    "--confirm-role-change",
  ];
  if (action === "grant") args.push("--role", "owner");

  const result = spawnSync(process.execPath, args, {
    cwd: resolvePortalCwd(),
    env: process.env,
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(`platform role ${action} failed: ${result.stderr || result.stdout}`);
  }
}

function seedHqUser() {
  const result = spawnSync(
    process.execPath,
    ["--import", "tsx", "scripts/e2e_acceptance_seed.ts"],
    {
      cwd: resolvePortalCwd(),
      env: {
        ...process.env,
        E2E_TENANT_SLUG: HQ_TENANT_SLUG,
        E2E_USER_EMAIL: HQ_USER_EMAIL,
        E2E_ATTACH_MEMBERSHIP: "1",
      },
      encoding: "utf8",
    },
  );
  if (result.status !== 0) {
    throw new Error(`HQ seed failed: ${result.stderr || result.stdout}`);
  }
}

test.describe.serial("Zorva HQ authorization and accessible operator entry", () => {
  test.beforeAll(() => {
    seedHqUser();
  });

  test("fails closed, renders accessibly for an owner, and rechecks revoked access", async ({
    page,
  }) => {
    await page.goto("/hq", { waitUntil: "domcontentloaded" });
    expect(page.url()).toContain("/login?callbackUrl=%2Fhq");

    await loginViaMagicLink(page, HQ_USER_EMAIL, "/dashboard");
    const authenticatedOrigin = new URL(page.url()).origin;
    await page.goto(`${authenticatedOrigin}/hq`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("heading", { name: "Today" })).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Zorva HQ sections" })).toHaveCount(0);
    const tenantOnlyApi = await page.request.post(`${authenticatedOrigin}/api/hq/support`, {
      data: {},
    });
    expect(tenantOnlyApi.status()).toBe(403);
    expect(await tenantOnlyApi.json()).toMatchObject({ error: "forbidden" });

    changePlatformRole("grant");
    const ownerResponse = await page.goto(`${authenticatedOrigin}/hq`, {
      waitUntil: "networkidle",
    });
    expect(ownerResponse?.status()).toBe(200);

    await expect(page.getByRole("main")).toHaveAttribute("id", "main");
    await expect(page.getByRole("navigation", { name: "Zorva HQ sections" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Company priorities" })).toBeVisible();
    await expect(page.getByText("Private company workspace · owner")).toBeVisible();
    await expect(page.getByText(/Generated \d{4}-\d{2}-\d{2}T/)).toBeVisible();

    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", { name: "Skip to content" });
    await expect(skipLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/hq#main$/);

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole("navigation", { name: "Zorva HQ sections" })).toBeVisible();
    const geometry = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(geometry.content).toBeLessThanOrEqual(geometry.viewport);
    await page.screenshot({ path: "tests/e2e/screenshots/hq-owner-mobile.png", fullPage: true });

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${authenticatedOrigin}/contact`, { waitUntil: "networkidle" });
    await page.getByLabel("Your name").fill("Avery Practice Manager");
    await page.getByLabel("Clinic name").fill(SYNTHETIC_CLINIC_NAME);
    await page.getByLabel("Work email").fill(SYNTHETIC_LEAD_EMAIL);
    await page.getByLabel("Monthly claim volume").fill("3200");
    await page.getByLabel("Current billing setup").selectOption("in_house");
    const submitLead = page.getByRole("button", { name: "Talk to sales" });
    await expect(submitLead).toBeEnabled();
    await submitLead.click();
    await expect(page.getByRole("heading", { name: "Thanks — we got it." })).toBeVisible();
    await expect(page.getByText(SYNTHETIC_LEAD_EMAIL)).toBeVisible();

    await page.goto(`${authenticatedOrigin}/hq/leads`, { waitUntil: "networkidle" });
    await expect(page.getByRole("heading", { level: 1, name: "Leads" })).toBeVisible();
    // Local reruns may reuse a developer database; assert the newest matching
    // row while CI continues to exercise a fresh database.
    const capturedLead = page
      .getByRole("row")
      .filter({ hasText: SYNTHETIC_CLINIC_NAME })
      .first();
    await expect(capturedLead).toContainText("Avery Practice Manager");
    await expect(capturedLead).toContainText(SYNTHETIC_LEAD_EMAIL);
    await expect(capturedLead).toContainText("new");
    await expect(capturedLead).toContainText("Unknown");
    await page.screenshot({ path: "tests/e2e/screenshots/contact-to-hq-lead.png", fullPage: true });

    changePlatformRole("revoke");
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByRole("heading", { name: "Today" })).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Zorva HQ sections" })).toHaveCount(0);
    const revokedApi = await page.request.post(`${authenticatedOrigin}/api/hq/support`, {
      data: {},
    });
    expect(revokedApi.status()).toBe(403);
    expect(await revokedApi.json()).toMatchObject({ error: "forbidden" });
  });
});
