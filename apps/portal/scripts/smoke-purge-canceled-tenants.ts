// Smoke test for scripts/purge-canceled-tenants.ts (t_c12cf722).
//
// Inserts a synthetic tenant with canceledAt = 31 days ago, runs
// the purge script via child_process, and asserts the tenant is
// gone. Also tests the --dry-run path: the tenant must NOT be
// deleted.
//
// We don't import the purge script directly because it uses
// top-level process.exit() calls. Spawning it as a child keeps
// the test honest — we're verifying the actual command the cron
// will run, not a re-implementation.

import { strict as assert } from "node:assert";
import { spawnSync } from "node:child_process";
import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3";
import { PrismaClient } from "../src/generated/prisma/client";

function buildPrisma(): PrismaClient {
  const url = process.env.DATABASE_URL ?? "file:./prisma/dev.db";
  const sqlitePath = url.replace(/^file:/, "");
  return new PrismaClient({
    adapter: new PrismaBetterSqlite3({ url: sqlitePath }),
    log: ["error"],
  });
}

function uniqueSlug(base: string): string {
  return (
    base
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "")
      .slice(0, 48) || "clinic"
  );
}

function runPurge(args: string[]): { status: number; stdout: string; stderr: string } {
  const r = spawnSync("pnpm", ["tsx", "scripts/purge-canceled-tenants.ts", ...args], {
    encoding: "utf8",
    stdio: "pipe",
    cwd: process.cwd(),
    env: process.env,
  });
  return {
    status: r.status ?? -1,
    stdout: r.stdout ?? "",
    stderr: r.stderr ?? "",
  };
}

async function main() {
  const prisma = buildPrisma();
  const tag = `smoke-purge-${Date.now()}`;
  const customerId = `cus_purge_${tag}`;
  const tenantName = `Purge Test ${tag}`;

  let passed = 0;
  let failed = 0;
  function check(label: string, cond: boolean, detail?: string) {
    if (cond) {
      console.log(`  ✓ ${label}`);
      passed += 1;
    } else {
      console.error(`  ✗ ${label}${detail ? ` — ${detail}` : ""}`);
      failed += 1;
    }
  }

  try {
    // ----- Setup: insert a tenant with canceledAt = 31 days ago -----
    console.log("\n[setup] creating synthetic tenant with canceledAt = 31d ago");
    const oldCancel = new Date(Date.now() - 31 * 24 * 60 * 60 * 1000);
    const tenant = await prisma.tenant.create({
      data: {
        name: tenantName,
        slug: uniqueSlug(tenantName),
        tier: "small",
        subscriptionStatus: "canceled",
        stripeCustomerId: customerId,
        canceledAt: oldCancel,
        auditQuotaLimit: 500,
      },
    });
    const before = await prisma.tenant.findUnique({ where: { id: tenant.id } });
    check("synthetic tenant exists", before !== null);
    check(
      "synthetic tenant canceledAt is 31d ago",
      before?.canceledAt !== null &&
        Math.abs(before.canceledAt.getTime() - oldCancel.getTime()) < 1000,
    );

    // ----- 1. --dry-run must NOT delete -----
    console.log("\n[1] purge --dry-run: tenant should still exist");
    {
      const r = runPurge(["--dry-run"]);
      assert.equal(r.status, 0, `dry-run exit code: ${r.status}\nstdout=${r.stdout}\nstderr=${r.stderr}`);
      const after = await prisma.tenant.findUnique({ where: { id: tenant.id } });
      check("--dry-run did not delete the tenant", after !== null);
      assert.ok(
        r.stdout.includes("smoke-purge-") || r.stdout.includes(tenantName),
        `--dry-run should mention the synthetic tenant in output\nstdout=${r.stdout}`,
      );
    }

    // ----- 2. real purge: tenant older than 30d is deleted -----
    console.log("\n[2] purge (no flags): tenant should be deleted");
    {
      const r = runPurge([]);
      assert.equal(r.status, 0, `purge exit code: ${r.status}\nstdout=${r.stdout}\nstderr=${r.stderr}`);
      const after = await prisma.tenant.findUnique({ where: { id: tenant.id } });
      check("tenant deleted", after === null);
    }

    // ----- 3. recent cancel is preserved -----
    console.log("\n[3] recent cancellation (5d ago) is preserved");
    {
      const recentCustomerId = `cus_recent_${tag}`;
      const recent = await prisma.tenant.create({
        data: {
          name: `Recent Cancel ${tag}`,
          slug: uniqueSlug(`recent-cancel-${tag}`),
          tier: "small",
          subscriptionStatus: "canceled",
          stripeCustomerId: recentCustomerId,
          canceledAt: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000),
          auditQuotaLimit: 500,
        },
      });
      const r = runPurge([]);
      assert.equal(r.status, 0, `purge exit code: ${r.status}`);
      const after = await prisma.tenant.findUnique({ where: { id: recent.id } });
      check("recently canceled tenant preserved", after !== null);
      // Cleanup
      await prisma.tenant.delete({ where: { id: recent.id } });
    }

    // ----- 4. no candidates → exit 0 -----
    console.log("\n[4] no candidates → exit 0");
    {
      const r = runPurge([]);
      assert.equal(r.status, 0, `purge exit code: ${r.status}`);
      assert.ok(
        r.stdout.includes("no candidates") || r.stdout.includes("nothing to do"),
        `expected no-candidates message, got:\n${r.stdout}`,
      );
    }

    // ----- Summary -----
    console.log(`\n[smoke-purge-canceled-tenants] passed=${passed} failed=${failed}`);
    if (failed > 0) {
      console.error("SMOKE FAILED");
      process.exit(1);
    }
    console.log("ALL CHECKS PASSED");
  } finally {
    await prisma.$disconnect();
  }
}

main().catch((e) => {
  console.error("[smoke-purge-canceled-tenants] unhandled error:", e);
  process.exit(1);
});
