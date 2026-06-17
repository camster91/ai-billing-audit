// End-to-end smoke test for the /encounters list page and the
// /api/encounters/export CSV route (t_2407d2c1).
//
// Walks the magic-link dev flow:
//   1. POST to /api/auth/signin/resend with the demo user's email
//      and a callbackUrl — the dev-mode sendVerificationRequest
//      prints the magic link to the dev server's stdout instead of
//      emailing it. We capture the link from the dev.log file
//      between requests.
//   2. GET the magic link → the callback sets a session cookie.
//   3. GET /encounters with the cookie and verify the rendered HTML
//      contains the seeded rows.
//   4. GET /api/encounters/export with the same cookie and a
//      `status=pending` filter, verify the CSV has the header row
//      and only pending rows.
//
// Run from apps/portal:
//   pnpm exec tsx scripts/smoke-encounter-list.ts
//
// Pre-req: a dev server must be running on port 3000 (or 3001 —
// the script probes both) and the seed-encounter-list script must
// have been run.

import { randomBytes } from "node:crypto";
import { readFileSync, existsSync } from "node:fs";

const PORTS = [3000, 3001];
const COOKIE_JAR: string[] = [];

async function findBase(): Promise<string> {
  for (const p of PORTS) {
    try {
      const r = await fetch(`http://localhost:${p}/login`, { redirect: "manual" });
      if (r.status < 500) return `http://localhost:${p}`;
    } catch {
      // ignore
    }
  }
  throw new Error("no dev server found on ports 3000 or 3001");
}

function appendCookie(setCookie: string | null) {
  if (!setCookie) return;
  const [pair] = setCookie.split(";");
  if (!pair) return;
  const idx = COOKIE_JAR.findIndex((c) => c.split("=")[0] === pair.split("=")[0]);
  if (idx >= 0) COOKIE_JAR[idx] = pair;
  else COOKIE_JAR.push(pair);
}

function cookieHeader(): string {
  return COOKIE_JAR.join("; ");
}

async function postForm(base: string, path: string, body: Record<string, string>): Promise<Response> {
  const params = new URLSearchParams(body);
  const r = await fetch(`${base}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/x-www-form-urlencoded",
      cookie: cookieHeader(),
    },
    body: params.toString(),
    redirect: "manual",
  });
  const sc = r.headers.get("set-cookie");
  appendCookie(sc);
  return r;
}

async function get(base: string, path: string): Promise<Response> {
  const r = await fetch(`${base}${path}`, {
    headers: { cookie: cookieHeader() },
    redirect: "manual",
  });
  const sc = r.headers.get("set-cookie");
  appendCookie(sc);
  return r;
}

function readMagicLink(): string {
  // The dev auth flow prints the magic link to the dev server's
  // stdout. We tail the dev log file. If the link isn't there yet,
  // wait a moment and retry.
  const candidates = [
    ".next/dev/logs/next-development.log",
    "/tmp/dev.log",
  ];
  let lastLink: string | null = null;
  for (const path of candidates) {
    if (!existsSync(path)) continue;
    const text = readFileSync(path, "utf8");
    const matches = text.match(/https?:\/\/[^\s\\]*api\/auth\/callback[^\s\\]*/g);
    if (matches && matches.length > 0) {
      lastLink = matches[matches.length - 1] as string;
      // Strip ANSI escape sequences that next prints in color mode.
      lastLink = lastLink.replace(/\u001b\[[0-9;]*m/g, "");
    }
  }
  return lastLink ?? "";
}

async function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

async function waitForMagicLink(): Promise<string> {
  for (let i = 0; i < 20; i += 1) {
    const link = readMagicLink();
    if (link.length > 0) return link;
    await sleep(500);
  }
  throw new Error("magic link not found in dev log after 10s");
}

async function main() {
  const base = await findBase();
  console.log(`[smoke] using dev server at ${base}`);

  // 1. Trigger magic-link signin for the demo user. The CSRF
  //    cookie is set by the /api/auth/csrf endpoint; we fetch it
  //    first and pull the token out of the response JSON.
  const csrf = await get(base, "/api/auth/csrf");
  const csrfJson = (await csrf.json()) as { csrfToken: string };
  await postForm(base, "/api/auth/signin/resend", {
    email: "demo.reviewer@ashbi.test",
    callbackUrl: "/encounters",
    csrfToken: csrfJson.csrfToken,
    json: "true",
  });
  console.log("[smoke] signin request sent, waiting for magic link in dev log…");
  const link = await waitForMagicLink();
  console.log(`[smoke] magic link: ${link.slice(0, 80)}…`);

  // 2. Hit the magic link — the callback sets the session cookie
  //    and 302's to /encounters.
  const callback = await get(base, link.replace(/^https?:\/\/[^/]+/, ""));
  console.log(`[smoke] callback status=${callback.status}`);

  // 3. Fetch the /encounters page and assert the table renders the
  //    expected columns and the seeded rows.
  const pageRes = await get(base, "/encounters");
  const html = await pageRes.text();
  if (pageRes.status !== 200) {
    throw new Error(`/encounters returned ${pageRes.status}, body starts: ${html.slice(0, 200)}`);
  }
  const checks: Array<[string, boolean]> = [
    ["<h1>Encounters</h1>", html.includes("<h1") && html.includes("Encounters")],
    ["table header has Date of service", html.includes("Date of service")],
    ["table header has Provider", html.includes("Provider")],
    ["table header has Payer", html.includes("Payer")],
    ["table header has Status", html.includes("Status")],
    ["table header has Findings", html.includes("Findings")],
    ["table header has Est. impact", html.includes("Est. impact")],
    // Page 1 (default sort = dateOfService DESC) shows the 50 most-recent
    // encounters; with 60 seeded the oldest 5 are on page 2. Assert that
    // the page contains *some* seeded id rather than a specific one.
    ["seeded encounter id present", /enc-list-\d{4}/.test(html)],
    ["filter toolbar present", html.includes("Status") && html.includes("Category") && html.includes("Provider")],
  ];
  let failed = 0;
  for (const [label, ok] of checks) {
    console.log(`${ok ? "  ok" : "FAIL"}  ${label}`);
    if (!ok) failed += 1;
  }
  if (failed > 0) {
    throw new Error(`${failed} check(s) failed on /encounters`);
  }

  // 4. Hit the export endpoint and check the CSV shape.
  const exportRes = await get(base, "/api/encounters/export?status=pending&page_size=10");
  if (exportRes.status !== 200) {
    throw new Error(`/api/encounters/export returned ${exportRes.status}`);
  }
  const csv = await exportRes.text();
  const lines = csv.trim().split("\n");
  if (lines[0] !== "encounter_id,date_of_service,provider,provider_npi,payer,status,finding_count,est_impact_cents,total_billed_cents,patient_hash_prefix") {
    throw new Error(`unexpected CSV header: ${lines[0]}`);
  }
  console.log(`[smoke] CSV: ${lines.length} lines (1 header + ${lines.length - 1} data rows for status=pending)`);
  if (lines.length < 2) {
    throw new Error("expected at least one data row for status=pending");
  }
  // Every data row should have status=pending.
  for (let i = 1; i < lines.length; i += 1) {
    const cols = lines[i].split(",");
    if (cols[5] !== "pending") {
      throw new Error(`row ${i} has status=${cols[5]}, expected pending`);
    }
  }

  // 5. Hit the export with selection ids.
  const idsParam = "enc-list-0001,enc-list-0002";
  const selRes = await get(base, `/api/encounters/export?ids=${idsParam}`);
  if (selRes.status !== 200) {
    throw new Error(`/api/encounters/export?ids=… returned ${selRes.status}`);
  }
  const selCsv = await selRes.text();
  const selLines = selCsv.trim().split("\n");
  if (selLines.length !== 3) {
    throw new Error(`expected 3 lines (header + 2 selected) for ids export, got ${selLines.length}`);
  }
  console.log(`[smoke] ids-scoped CSV: ${selLines.length} lines for ids=enc-list-0001,enc-list-0002`);

  // 6. Sort round-trip — sort=est_impact&dir=desc and assert the
  //    first data row has the largest impact.
  const sortRes = await get(base, "/api/encounters/export?sort=est_impact&dir=desc&page_size=5");
  if (sortRes.status !== 200) {
    throw new Error(`/api/encounters/export?sort=est_impact&dir=desc returned ${sortRes.status}`);
  }
  const sortCsv = await sortRes.text();
  const sortLines = sortCsv.trim().split("\n").slice(1);
  const impacts = sortLines.map((l) => Number.parseInt(l.split(",")[7], 10));
  for (let i = 1; i < impacts.length; i += 1) {
    if (impacts[i] > impacts[i - 1]) {
      throw new Error(`row ${i} impact ${impacts[i]} > row ${i - 1} impact ${impacts[i - 1]} — sort not respected`);
    }
  }
  console.log(`[smoke] est_impact desc sort verified, top impact: $${(impacts[0] / 100).toFixed(2)}`);

  console.log("[smoke] all checks passed");
}

main().catch((err) => {
  console.error("[smoke] failed", err);
  process.exit(1);
});
