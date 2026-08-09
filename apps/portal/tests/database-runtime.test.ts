import { test } from "node:test";
import assert from "node:assert/strict";

import { resolveDatabaseRuntime } from "../src/lib/database-runtime";
import { buildClient } from "../src/lib/prisma";

test("selects SQLite only for file URLs", () => {
  assert.deepEqual(resolveDatabaseRuntime("file:./prisma/dev.db", "development"), {
    provider: "sqlite",
    url: "./prisma/dev.db",
  });
});

test("selects PostgreSQL for postgres URLs", () => {
  const url = "postgresql://zorva:secret@db:5432/zorva";
  assert.deepEqual(resolveDatabaseRuntime(url, "production"), {
    provider: "postgresql",
    url,
  });
});

test("production fails closed when DATABASE_URL is missing", () => {
  assert.throws(
    () => resolveDatabaseRuntime(undefined, "production"),
    /DATABASE_URL is required in production/,
  );
});

test("production refuses the development SQLite database", () => {
  assert.throws(
    () => resolveDatabaseRuntime("file:./prisma/dev.db", "production"),
    /PostgreSQL DATABASE_URL is required in production/,
  );
});

test("unsupported database schemes fail clearly", () => {
  assert.throws(
    () => resolveDatabaseRuntime("mysql://db/zorva", "production"),
    /Unsupported DATABASE_URL scheme/,
  );
});

test("PostgreSQL runtime constructs with the matching Prisma driver", async () => {
  const client = buildClient(
    "postgresql://zorva:secret@127.0.0.1:9/zorva",
    "production",
  );
  await client.$disconnect();
});
