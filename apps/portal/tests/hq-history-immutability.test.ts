import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import Database from "better-sqlite3";

const sqliteMigration = readFileSync(
  new URL("../prisma/migrations/20260831200000_protect_hq_history/migration.sql", import.meta.url),
  "utf8",
);
const postgresqlMigration = readFileSync(
  new URL("../prisma/postgresql/migrations/20260831200000_protect_hq_history/migration.sql", import.meta.url),
  "utf8",
);

function createHistoryDatabase() {
  const database = new Database(":memory:");
  database.exec(`
    CREATE TABLE "PlatformAuditEvent" (
      "id" TEXT PRIMARY KEY,
      "requestId" TEXT NOT NULL UNIQUE,
      "action" TEXT NOT NULL
    );
    CREATE TABLE "LeadActivity" (
      "id" TEXT PRIMARY KEY,
      "mutationId" TEXT NOT NULL,
      "kind" TEXT NOT NULL
    );
  `);
  database.exec(sqliteMigration);
  return database;
}

test("SQLite HQ history guards allow inserts and reject updates and deletes", () => {
  const database = createHistoryDatabase();
  try {
    database.prepare(`INSERT INTO "PlatformAuditEvent" ("id", "requestId", "action") VALUES (?, ?, ?)`)
      .run("audit-1", "request-1", "read");
    database.prepare(`INSERT INTO "LeadActivity" ("id", "mutationId", "kind") VALUES (?, ?, ?)`)
      .run("activity-1", "mutation-1", "stage_changed");

    assert.throws(
      () => database.prepare(`UPDATE "PlatformAuditEvent" SET "action" = ? WHERE "id" = ?`).run("rewritten", "audit-1"),
      /PlatformAuditEvent is append-only/,
    );
    assert.throws(
      () => database.prepare(`DELETE FROM "PlatformAuditEvent" WHERE "id" = ?`).run("audit-1"),
      /PlatformAuditEvent is append-only/,
    );
    assert.throws(
      () => database.prepare(`UPDATE "LeadActivity" SET "kind" = ? WHERE "id" = ?`).run("rewritten", "activity-1"),
      /LeadActivity is append-only/,
    );
    assert.throws(
      () => database.prepare(`DELETE FROM "LeadActivity" WHERE "id" = ?`).run("activity-1"),
      /LeadActivity is append-only/,
    );
    assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM "PlatformAuditEvent"`).get().count, 1);
    assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM "LeadActivity"`).get().count, 1);
  } finally {
    database.close();
  }
});

test("PostgreSQL migration protects both history tables from update and delete", () => {
  assert.match(postgresqlMigration, /BEFORE UPDATE OR DELETE ON "PlatformAuditEvent"/);
  assert.match(postgresqlMigration, /BEFORE UPDATE OR DELETE ON "LeadActivity"/);
  assert.match(postgresqlMigration, /RAISE EXCEPTION/);
  assert.doesNotMatch(postgresqlMigration, /current_setting|session_user|bypass/i);
});
