// Singleton Prisma client.
//
// In dev, Next.js hot-reload re-evaluates this module on every change which
// would normally create a new PrismaClient and exhaust the SQLite handle
// pool. The global-cache pattern below is the official Prisma recommendation:
// store the client on globalThis in non-production environments so HMR
// re-uses the same instance.
//
// In production (NODE_ENV=production) the global is unused and a fresh
// client is created per process, which is what we want for serverless
// cold starts.
//
// Prisma 7 note: the client now requires a Driver Adapter for direct DB
// access (no more "magic" DATABASE_URL from schema). For local dev we use
// @prisma/adapter-better-sqlite3 (synchronous, fast, single-file). In
// production swap this for @prisma/adapter-pg pointed at the ca-central-1
// or us-east-1 Postgres cluster.

import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3";
import { PrismaClient } from "@/generated/prisma/client";

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined;
};

function buildClient(): PrismaClient {
  const databaseUrl = process.env.DATABASE_URL ?? "file:./prisma/dev.db";
  // The adapter wants a bare path, not a `file:./` URL — strip the prefix.
  const sqlitePath = databaseUrl.replace(/^file:/, "");

  const adapter = new PrismaBetterSqlite3({ url: sqlitePath });

  return new PrismaClient({
    adapter,
    log:
      process.env.NODE_ENV === "development"
        ? ["query", "error", "warn"]
        : ["error"],
  });
}

export const prisma = globalForPrisma.prisma ?? buildClient();

if (process.env.NODE_ENV !== "production") {
  globalForPrisma.prisma = prisma;
}
