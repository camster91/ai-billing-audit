-- Team management: extend Membership with status / email / inviteToken.
--
-- Backwards-compatible table rewrite:
--   - userId becomes nullable (a "pending" membership may not yet be
--     bound to a User row).
--   - email is required for every membership. For existing rows
--     we copy the value from the linked User.
--   - status defaults to "active" for existing rows; new rows default
--     to "active" too but the /api/team/invite handler will pass
--     "pending" explicitly.
--   - inviteToken is nullable and unique. The accept route generates
--     a one-time token; we leave it null for existing rows.
--
-- SQLite doesn't support DROP COLUMN / ADD CONSTRAINT on all
-- versions, so we use the project-standard "create new table, copy
-- data, swap" pattern that the 20260617090319_add_settings_page_columns
-- migration also uses.

PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;

CREATE TABLE "new_Membership" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT,
    "tenantId" TEXT NOT NULL,
    "role" TEXT NOT NULL DEFAULT 'viewer',
    "status" TEXT NOT NULL DEFAULT 'active',
    "email" TEXT NOT NULL,
    "inviteToken" TEXT,
    "invitedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "activatedAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "new_Membership_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User" ("id") ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT "new_Membership_tenantId_fkey" FOREIGN KEY ("tenantId") REFERENCES "Tenant" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

INSERT INTO "new_Membership" ("id", "userId", "tenantId", "role", "status", "email", "inviteToken", "invitedAt", "activatedAt", "createdAt", "updatedAt")
SELECT
    m."id",
    m."userId",
    m."tenantId",
    m."role",
    'active',
    COALESCE(u."email", 'unknown@example.com'),
    NULL,
    m."createdAt",
    m."createdAt",
    m."createdAt",
    m."createdAt"
FROM "Membership" m
LEFT JOIN "User" u ON u."id" = m."userId";

DROP TABLE "Membership";
ALTER TABLE "new_Membership" RENAME TO "Membership";

-- Recreate the original indexes plus the new email / inviteToken indexes.
CREATE UNIQUE INDEX "Membership_userId_tenantId_key" ON "Membership"("userId", "tenantId");
CREATE UNIQUE INDEX "Membership_inviteToken_key" ON "Membership"("inviteToken");
CREATE INDEX "Membership_tenantId_idx" ON "Membership"("tenantId");
CREATE INDEX "Membership_email_idx" ON "Membership"("email");

PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;
