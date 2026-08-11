// Singleton Prisma client with an explicit driver adapter for each runtime.
// Local development and tests use SQLite. Production fails closed unless a
// PostgreSQL URL is supplied, then uses the separately generated PG client.

import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3";
import { PrismaPg } from "@prisma/adapter-pg";
import { PrismaClient } from "@/generated/prisma/client";
import { PrismaClient as PostgresPrismaClient } from "@/generated/prisma-postgresql/client";
import { resolveDatabaseRuntime } from "@/lib/database-runtime";

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined;
};

export function buildClient(
  databaseUrl = process.env.DATABASE_URL,
  nodeEnv = process.env.NODE_ENV,
): PrismaClient {
  const runtime = resolveDatabaseRuntime(databaseUrl, nodeEnv);
  const log =
    process.env.NODE_ENV === "development"
      ? (["query", "error", "warn"] as const)
      : (["error"] as const);

  if (runtime.provider === "postgresql") {
    return new PostgresPrismaClient({
      adapter: new PrismaPg({ connectionString: runtime.url }),
      log: [...log],
    }) as unknown as PrismaClient;
  }

  return new PrismaClient({
    adapter: new PrismaBetterSqlite3({ url: runtime.url }),
    log: [...log],
  });
}

function buildTimeClientProxy(): PrismaClient {
  let client: PrismaClient | undefined;

  // Next imports dynamic route modules while collecting build metadata. Those
  // modules import `prisma`, but should not open a database connection until a
  // request executes a query. Keep this mode strictly build-only; the runtime
  // continues to construct its client normally and fails closed on bad config.
  return new Proxy({} as PrismaClient, {
    get(_target, property, receiver) {
      client ??= buildClient();
      const value = Reflect.get(client, property, receiver);
      return typeof value === "function" ? value.bind(client) : value;
    },
  });
}

const isBuildWithoutDatabase = process.env.ZORVA_BUILD_SKIP_DATABASE === "1";

export const prisma = isBuildWithoutDatabase
  ? buildTimeClientProxy()
  : globalForPrisma.prisma ?? buildClient();

if (!isBuildWithoutDatabase && process.env.NODE_ENV !== "production") {
  globalForPrisma.prisma = prisma;
}
