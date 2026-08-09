export type DatabaseRuntime =
  | { provider: "sqlite"; url: string }
  | { provider: "postgresql"; url: string };

export function resolveDatabaseRuntime(
  databaseUrl: string | undefined,
  nodeEnv: string | undefined,
): DatabaseRuntime {
  if (!databaseUrl) {
    if (nodeEnv === "production") {
      throw new Error("DATABASE_URL is required in production");
    }
    return { provider: "sqlite", url: "./prisma/dev.db" };
  }

  if (databaseUrl.startsWith("file:")) {
    if (nodeEnv === "production") {
      throw new Error("PostgreSQL DATABASE_URL is required in production");
    }
    return { provider: "sqlite", url: databaseUrl.replace(/^file:/, "") };
  }

  if (
    databaseUrl.startsWith("postgresql://") ||
    databaseUrl.startsWith("postgres://")
  ) {
    return { provider: "postgresql", url: databaseUrl };
  }

  throw new Error("Unsupported DATABASE_URL scheme; use file: or postgresql:");
}
