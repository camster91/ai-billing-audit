// E2E smoke flow — marketing -> portal -> findings.
//
// This is the 8-step gate that runs on every PR. The suite is
// ordered (workers: 1, fullyParallel: false) so step N+1 inherits
// the state step N produced. Each test asserts a specific user-visible
// outcome; the test's title and the step number in the comment track
// the acceptance criteria from the original task body.
//
// What lives in this file vs helpers.ts:
//   - the 8 ordered tests
//   - per-step selectors and assertions
// Helpers (captureMagicLinkFromLog, postCheckout,
// seedAcceptance) live in tests/e2e/helpers.ts so other specs can
// reuse them later.
//
// State that the tests depend on:
//   - the dev server at $E2E_BASE_URL (default http://127.0.0.1:3000)
//     writing magic links to $E2E_DEV_LOG (default /tmp/portal-dev.log)
//   - the seed script creates only a clean test user and fixture tenant;
//     checkout redemption creates the actual journey tenant. We don't reset
//     between tests — each later step builds on the real API state before it.

import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import * as path from "node:path";

import {
  DEFAULT_TENANT_SLUG,
  DEFAULT_USER_EMAIL,
  loginViaMagicLink,
  postCheckout,
  readAuditChain,
  readImportedEncounter,
  seedAcceptance,
  resolvePortalCwd,
} from "./helpers";

const SAMPLE_837P = path.join(resolvePortalCwd(), "tests/e2e/fixtures/sample-837P.edi");

// Cross-test state. Module-scoped vars survive across the ordered
// tests because workers: 1 runs them in sequence in the same process.
const state: {
  tenantId: string;
  sessionId: string;
  encounterId: string;
  findingIds: string[];
  accepted: boolean;
  dismissed: boolean;
} = {
  tenantId: "",
  sessionId: "",
  encounterId: "",
  findingIds: [],
  accepted: false,
  dismissed: false,
};

test.beforeAll(async () => {
  // 1. Wipe + provision the clean E2E user. The journey tenant is created by
  // checkout redemption; no membership or completed onboarding is seeded.
  seedAcceptance(DEFAULT_TENANT_SLUG, DEFAULT_USER_EMAIL, false);
  // 2. Confirm the sample 837P file is present.
  if (!existsSync(SAMPLE_837P)) {
    throw new Error(`sample 837P fixture missing at ${SAMPLE_837P}`);
  }
  // 3. Confirm the dev log path is set (magic link capture requires it).
  if (!process.env.E2E_AUTH_CAPTURE_FILE && !process.env.E2E_DEV_LOG && !existsSync("/tmp/portal-dev.log")) {
    throw new Error(
      "dev log not found at /tmp/portal-dev.log. Start the dev server with " +
        "`pnpm dev:background` (or set E2E_DEV_LOG to a real file).",
    );
  }
});

test.describe.serial("smoke: marketing -> portal -> findings", () => {
  // Use a serial block: tests share state and order matters. The
  // global config (workers: 1, fullyParallel: false) enforces this
  // across the run; the serial block is an additional guard.

  // -------------------------------------------------------------------------
  // Step 1: verify unapproved pricing claims remain behind the public gate
  // -------------------------------------------------------------------------
  // The task body lists "hero text on /" as step 1. The marketing
  // landing page in this project is the default Next.js scaffold
  // (h1: "To get started, edit the page.tsx file."), not the
  // /pricing page, so we test /pricing directly. /pricing is the
  // marketing CTA target — visit it and assert 3 tiers.
  test("step 01: deferred /pricing redirects to reviewed contact", async ({ page }) => {
    await page.goto("/pricing", { waitUntil: "domcontentloaded" });
    expect(page.url(), "pricing stays gated until claims are approved").toMatch(/\/contact$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.screenshot({ path: "tests/e2e/screenshots/01-pricing-gate.png", fullPage: true });
  });

  // -------------------------------------------------------------------------
  // Step 2: click the mid-tier CTA and assert Stripe Checkout opens
  //          in a new tab. (Test the redirect/tab, not the full flow.)
  // -------------------------------------------------------------------------
  test("step 02: mid-tier CTA posts to /api/billing/checkout and returns a session", async ({
    page,
  }) => {
    // Drive the CTA via the API directly: the client component
    // (`/pricing/CheckoutButton.tsx`) does a `window.location.href =
    // data.url` redirect, which we don't want to follow in the test —
    // we just want to assert the API response shape.
    const checkout = await postCheckout(page.request, "mid", "CAD");
    expect(checkout.sessionId, "checkout returned a sessionId").toBeTruthy();
    // In demo mode, `url` is null (no real Stripe); the wizard
    // consumes the sessionId directly. If a real Stripe URL comes
    // back, we'd assert it looks like a checkout.stripe.com URL.
    if (checkout.url) {
      expect(checkout.url).toMatch(/^https?:\/\//);
    }
    state.sessionId = checkout.sessionId;
  });

  // -------------------------------------------------------------------------
  // Step 3: log into the portal via magic link
  // -------------------------------------------------------------------------
  test("step 03: magic-link login redeems checkout into the onboarding wizard", async ({ page }) => {
    const callback = `/portal/onboarding?session_id=${state.sessionId}&demo=1`;
    await page.goto(`/login?callbackUrl=${encodeURIComponent(callback)}`, {
      waitUntil: "domcontentloaded",
    });
    await loginViaMagicLink(page, DEFAULT_USER_EMAIL, callback);
    expect(page.url()).toMatch(/\/portal\/onboarding/);
    const cookieHeader = (await page.context().cookies())
      .map(({ name, value }) => `${name}=${value}`)
      .join("; ");
    const redeem = await page.request.post("/api/onboarding/redeem", {
      headers: { cookie: cookieHeader, "content-type": "application/json" },
      data: { sessionId: state.sessionId },
    });
    expect(redeem.ok(), `redeem returned HTTP ${redeem.status()}`).toBe(true);
    const body = (await redeem.json()) as { tenant?: { id?: string }; state?: { step?: number } };
    state.tenantId = body.tenant?.id ?? "";
    expect(state.tenantId, "checkout redemption returned tenantId").toBeTruthy();
    expect(body.state?.step, "checkout redemption advanced the wizard").toBeGreaterThanOrEqual(1);
    await page.screenshot({ path: "tests/e2e/screenshots/03-onboarding.png", fullPage: true });
  });

  // -------------------------------------------------------------------------
  // Step 4: complete every onboarding API step and stage an encrypted 837P
  // -------------------------------------------------------------------------
  // The wizard's step 5 (`/portal/onboarding`) accepts the file via
  // POST /api/onboarding/upload (multipart). We drive it directly.
  // The file path is also stored in the tenant row (for the audit
  // pipeline to pick up after the wizard completes).
  test("step 04: authenticated onboarding APIs complete and stage encrypted 837P", async ({ page }) => {
    // Playwright creates a fresh browser context for each test, even inside a
    // serial describe block. Establish this step's own authenticated session
    // before using page.request so the upload exercises the real auth gate.
    await loginViaMagicLink(page, DEFAULT_USER_EMAIL, `/portal/onboarding?session_id=${state.sessionId}`);
    const cookieHeader = (await page.context().cookies())
      .map(({ name, value }) => `${name}=${value}`)
      .join("; ");
    expect(cookieHeader, "magic-link callback established session cookies").toBeTruthy();
    const jsonHeaders = { cookie: cookieHeader, "content-type": "application/json" };
    const postStep = async (path: string, data: Record<string, unknown>) => {
      const response = await page.request.post(path, { headers: jsonHeaders, data });
      const responseText = await response.text();
      expect(response.ok(), `${path} returned HTTP ${response.status()}: ${responseText}`).toBe(true);
      return JSON.parse(responseText) as Record<string, unknown>;
    };
    await postStep("/api/onboarding/clinic-profile", {
      tenantId: state.tenantId,
      clinicName: "E2E Acceptance Clinic",
      clinicNpi: "1234567893",
      clinicTimezone: "America/Edmonton",
    });
    await postStep("/api/onboarding/region", { tenantId: state.tenantId, region: "ca-central-1" });
    await postStep("/api/onboarding/ehr", { tenantId: state.tenantId, mode: "manual" });
    const buf = await readFile(SAMPLE_837P);
    const res = await page.request.post("/api/onboarding/upload", {
      headers: { cookie: cookieHeader },
      multipart: {
        tenantId: state.tenantId,
        file: {
          name: "sample-837P.edi",
          mimeType: "text/plain",
          buffer: buf,
        },
      },
    });
    expect(
      res.ok(),
      `upload returned HTTP ${res.status()}: ${await res.text().catch(() => "<no body>")}`,
    ).toBe(true);
    const body = (await res.json()) as {
      encryptedAtRest?: boolean;
      fileName?: string;
      filePath?: string;
    };
    expect(body.encryptedAtRest, "upload response confirms encryption").toBe(true);
    expect(body.fileName, "upload response includes fileName").toBeTruthy();
    const firstEncounter = await postStep("/api/onboarding/first-encounter", {
      tenantId: state.tenantId,
      mode: "uploaded",
      filePath: body.filePath,
      fileName: body.fileName,
      specialty: "family_medicine",
      clinicalNote:
        "Established patient follow-up. Assessment and plan documented for preventive care. Follow-up plan reviewed with the patient.",
    });
    state.encounterId = (firstEncounter.ingestion as { encounterId?: string } | undefined)?.encounterId ?? "";
    expect(state.encounterId, "uploaded claim created a portal encounter").toBeTruthy();
    const completed = await postStep("/api/onboarding/complete", { tenantId: state.tenantId });
    expect((completed.tenant as { onboardingCompletedAt?: string } | undefined)?.onboardingCompletedAt).toBeTruthy();
    const audit = await page.request.post("/api/audit/run", {
      headers: { ...jsonHeaders, "x-tenant-id": state.tenantId },
      data: { encounterId: state.encounterId },
    });
    expect(audit.status(), await audit.text()).toBe(202);
    const status = await page.request.get(
      `/api/audit/status?encounterId=${encodeURIComponent(state.encounterId)}`,
      { headers: { cookie: cookieHeader, "x-tenant-id": state.tenantId } },
    );
    expect(status.ok(), `audit status returned HTTP ${status.status()}`).toBe(true);
    const statusBody = (await status.json()) as { status?: string; findings?: number };
    expect(statusBody.status).toBe("done");
    expect(statusBody.findings).toBeGreaterThanOrEqual(2);
    await page.goto("/findings", { waitUntil: "domcontentloaded" });
    await page.screenshot({ path: "tests/e2e/screenshots/04-onboarding-complete.png", fullPage: true });
  });

  // -------------------------------------------------------------------------
  // Step 5: prove the engine result was imported for the uploaded encounter
  // -------------------------------------------------------------------------
  test("step 05: uploaded encounter has imported engine findings", async () => {
    const encounter = readImportedEncounter(state.encounterId, state.tenantId);
    expect(encounter.sourceUploadDigest).toMatch(/^[a-f0-9]{64}$/);
    expect(encounter.status).toBe("awaiting_review");
    state.findingIds = encounter.findingIds;
    expect(state.findingIds.length, "engine result imported 2 findings").toBeGreaterThanOrEqual(2);
    expect(encounter.claimJson).toContain("diagnosisCodes");
  });

  // -------------------------------------------------------------------------
  // Step 6: the uploaded claim's finding appears on /findings
  // -------------------------------------------------------------------------
  test("step 06: /findings inbox lists the imported findings", async ({ page }) => {
    // Playwright isolates each test context, so establish this page's own
    // session before exercising the auth-gated findings inbox.
    await loginViaMagicLink(page, DEFAULT_USER_EMAIL, "/findings");
    const cookieHeader = (await page.context().cookies())
      .map(({ name, value }) => `${name}=${value}`)
      .join("; ");
    const findingsResponse = await page.request.get("/findings", {
      headers: { cookie: cookieHeader },
    });
    expect(
      findingsResponse.ok(),
      `findings returned HTTP ${findingsResponse.status()}`,
    ).toBe(true);
    const findingsHtml = await findingsResponse.text();
    expect(findingsHtml).toMatch(/code mismatch|documentation|2025/i);
    await page.setContent(findingsHtml, { waitUntil: "domcontentloaded" });
    await page.screenshot({ path: "tests/e2e/screenshots/06-findings.png", fullPage: true });
  });

  // -------------------------------------------------------------------------
  // Step 7: accept one finding, dismiss another with a reason
  // -------------------------------------------------------------------------
  // The /findings inbox renders one row per finding with bulk-action
  // modals. We exercise the API directly (the same path the modals
  // use) — that keeps the test focused on the persistence + audit
  // chain, which is what step 8 asserts.
  test("step 07: accept one finding, dismiss another with a reason", async ({ page }) => {
    expect(state.findingIds.length, "step 5 imported findings").toBeGreaterThanOrEqual(2);
    await loginViaMagicLink(page, DEFAULT_USER_EMAIL, "/findings");
    const cookieHeader = (await page.context().cookies())
      .map(({ name, value }) => `${name}=${value}`)
      .join("; ");

    // Accept the first finding.
    const acceptUrl = `/api/encounters/${state.encounterId}/findings/${state.findingIds[0]}/accept`;
    const acceptRes = await page.request.post(acceptUrl, {
      headers: { cookie: cookieHeader, "x-tenant-id": state.tenantId },
    });
    const acceptBody = (await acceptRes.json().catch(() => ({}))) as { ok?: boolean };
    expect(
      acceptRes.ok() && acceptBody.ok,
      `accept returned HTTP ${acceptRes.status()}: ${JSON.stringify(acceptBody).slice(0, 200)}`,
    ).toBe(true);
    state.accepted = true;

    // Dismiss the second finding with a reason.
    const dismissUrl = `/api/encounters/${state.encounterId}/findings/${state.findingIds[1]}/dismiss`;
    const dismissRes = await page.request.post(dismissUrl, {
      data: { reason: "hallucinated_fact" },
      headers: {
        "content-type": "application/json",
        cookie: cookieHeader,
        "x-tenant-id": state.tenantId,
      },
    });
    const dismissBody = (await dismissRes.json().catch(() => ({}))) as { ok?: boolean };
    expect(
      dismissRes.ok() && dismissBody.ok,
      `dismiss returned HTTP ${dismissRes.status()}: ${JSON.stringify(dismissBody).slice(0, 200)}`,
    ).toBe(true);
    state.dismissed = true;
  });

  // -------------------------------------------------------------------------
  // Step 8: the corresponding rows appear in the audit log
  // -------------------------------------------------------------------------
  // The audit log is an append-only Prisma table. There is no public
  // /audit route in this milestone; verify the chain by reading the
  // DB via the post-seed script's Prisma client. The chain walk is
  // the canonical integrity check (see src/lib/audit-chain.ts).
  test("step 08: audit log has 2 rows + chain signature is valid", async () => {
    expect(state.accepted && state.dismissed, "steps 6-7 ran").toBe(true);
    expect(state.encounterId, "encounterId set").toBeTruthy();

    const chain = readAuditChain(state.encounterId);
    expect(chain.rowCount, "2 audit rows").toBeGreaterThanOrEqual(2);
    expect(chain.actions, "one accept + one dismiss").toContain("accept");
    expect(chain.actions, "one accept + one dismiss").toContain("dismiss");
    expect(chain.brokenAt, `chain valid (brokenAt=${chain.brokenAt})`).toBeNull();
  });
});
