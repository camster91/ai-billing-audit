// Hard-delete tenants whose subscription was canceled more than
// CANCELED_TENANT_RETENTION_DAYS ago (default 30). Run daily from
// cron — the webhook handler records canceledAt when Stripe
// delivers customer.subscription.deleted; this script does the
// actual deletion so a canceled tenant's data isn't kept forever.
//
// Usage:
//   pnpm tsx scripts/purge-canceled-tenants.ts
//   pnpm tsx scripts/purge-canceled-tenants.ts --dry-run
//   PURGE_RETENTION_DAYS=15 pnpm tsx scripts/purge-canceled-tenants.ts
//
// The Prisma schema cascades deletes from Tenant to its child
// rows (Encounter, Finding, AuditTrailEntry, Membership,
// Invoice, ProcessedStripeEvent, RedeemedCheckoutSession), so
// deleting the Tenant row removes everything in one transaction.
//
// Exit code 0 on success (including 0 purges), non-zero if a
// transaction failed. Cron should treat non-zero as a maintenance
// alert — the next day's run will pick up the same rows.
//
// The retention window reads from PURGE_RETENTION_DAYS env var
// when set, falling back to CANCELED_TENANT_RETENTION_DAYS from
// src/lib/billing-webhook.ts. Override is for the "we're migrating
// to a longer window" one-off case where we want to delete the
// backlog of old canceled tenants in one shot.

import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3";
import { PrismaClient } from "../src/generated/prisma/client";
import { CANCELED_TENANT_RETENTION_DAYS } from "../src/lib/billing-webhook";

interface CliOptions {
  dryRun: boolean;
  retentionDays: number;
}

function parseArgs(argv: readonly string[]): CliOptions {
  const opts: CliOptions = {
    dryRun: false,
    retentionDays: CANCELED_TENANT_RETENTION_DAYS,
  };
  for (const arg of argv) {
    if (arg === "--dry-run") {
      opts.dryRun = true;
    } else if (arg === "--help" || arg === "-h") {
      console.log(
        [
          "Usage: tsx scripts/purge-canceled-tenants.ts [--dry-run]",
          "",
          "Environment:",
          "  PURGE_RETENTION_DAYS  override the retention window (default 30)",
          "",
          "Hard-deletes tenants with canceledAt < now - retentionDays.",
          "The Prisma schema cascades to child rows (Encounter, Finding,",
          "AuditTrailEntry, Membership, Invoice, ProcessedStripeEvent,",
          "RedeemedCheckoutSession) in a single transaction per tenant.",
        ].join("\n"),
      );
      process.exit(0);
    }
  }
  if (process.env.PURGE_RETENTION_DAYS) {
    const parsed = Number.parseInt(process.env.PURGE_RETENTION_DAYS, 10);
    if (Number.isFinite(parsed) && parsed > 0) {
      opts.retentionDays = parsed;
    }
  }
  return opts;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const cutoff = new Date(
    Date.now() - opts.retentionDays * 24 * 60 * 60 * 1000,
  );

  const databaseUrl = process.env.DATABASE_URL ?? "file:./prisma/dev.db";
  const sqlitePath = databaseUrl.replace(/^file:/, "");
  const adapter = new PrismaBetterSqlite3({ url: sqlitePath });
  const prisma = new PrismaClient({ adapter, log: ["error"] });

  console.log(
    `[purge-canceled-tenants] retention=${opts.retentionDays}d cutoff=${cutoff.toISOString()} dryRun=${opts.dryRun}`,
  );

  // Find the candidates first so the dry-run output lists the would-be
  // deletes (and so we can exit early when the table is empty).
  const candidates = await prisma.tenant.findMany({
    where: {
      canceledAt: { lt: cutoff, not: null },
    },
    select: {
      id: true,
      name: true,
      slug: true,
      stripeCustomerId: true,
      canceledAt: true,
    },
    orderBy: { canceledAt: "asc" },
  });

  if (candidates.length === 0) {
    console.log("[purge-canceled-tenants] no candidates; nothing to do");
    await prisma.$disconnect();
    return;
  }

  console.log(
    `[purge-canceled-tenants] ${candidates.length} tenant(s) older than ${opts.retentionDays}d:`,
  );
  for (const t of candidates) {
    console.log(
      `  - ${t.id} ${t.name} (slug=${t.slug}, stripeCustomer=${t.stripeCustomerId ?? "(none)"}, canceledAt=${t.canceledAt?.toISOString()})`,
    );
  }

  if (opts.dryRun) {
    console.log(
      "[purge-canceled-tenants] --dry-run set; skipping deletion. Re-run without --dry-run to apply.",
    );
    await prisma.$disconnect();
    return;
  }

  let succeeded = 0;
  let failed = 0;
  for (const t of candidates) {
    try {
      // The schema's onDelete: Cascade on every Tenant-owned child
      // table means a single delete call removes the whole tree in
      // one transaction. We wrap the call in $transaction so a
      // partial failure (e.g. a DB constraint we didn't anticipate)
      // rolls the whole tenant back rather than leaving a half-purged
      // tree.
      await prisma.$transaction(async (tx) => {
        await tx.tenant.delete({ where: { id: t.id } });
      });
      console.log(`[purge-canceled-tenants] purged ${t.id} ${t.name}`);
      succeeded += 1;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      console.error(
        `[purge-canceled-tenants] FAILED to purge ${t.id} ${t.name}: ${message}`,
      );
      failed += 1;
    }
  }

  console.log(
    `[purge-canceled-tenants] done. purged=${succeeded} failed=${failed}`,
  );
  await prisma.$disconnect();
  if (failed > 0) process.exit(1);
}

main().catch(async (e) => {
  console.error("[purge-canceled-tenants] unhandled error:", e);
  process.exit(1);
});
