import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { decryptPortalBuffer, decryptPortalString } from "../src/lib/data-encryption";
import {
  migratePortalCredential,
  migrateAuditTextFields,
  migratePortalUploadDirectory,
} from "../src/lib/portal-phi-migration";

process.env.ZORVA_PHI_ENCRYPTION_KEY ??= randomBytes(32).toString("base64url");

test("portal upload migration encrypts plaintext and is idempotent", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "zorva-portal-migrate-"));
  try {
    const target = path.join(dir, "claim.837");
    const plaintext = Buffer.from("ISA*00*claim payload~", "utf8");
    await writeFile(target, plaintext);

    const first = await migratePortalUploadDirectory(dir);
    assert.deepEqual(first, { migrated: 1, skipped: 0 });
    const encrypted = await readFile(target);
    assert.notDeepEqual(encrypted, plaintext);
    assert.deepEqual(decryptPortalBuffer(encrypted), plaintext);
    assert.deepEqual(
      decryptPortalBuffer(await readFile(`${target}.plaintext.bak.enc`)),
      plaintext,
    );

    const second = await migratePortalUploadDirectory(dir);
    assert.deepEqual(second, { migrated: 0, skipped: 1 });
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("portal upload migration fails closed when a backup already exists", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "zorva-portal-migrate-"));
  try {
    const target = path.join(dir, "claim.837");
    const plaintext = Buffer.from("plaintext claim", "utf8");
    await writeFile(target, plaintext);
    await writeFile(`${target}.plaintext.bak.enc`, Buffer.from("collision"));

    await assert.rejects(
      migratePortalUploadDirectory(dir),
      /backup already exists/,
    );
    assert.deepEqual(await readFile(target), plaintext);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("portal credential migration encrypts plaintext once", () => {
  const first = migratePortalCredential("legacy-sftp-password");
  assert.equal(first.migrated, true);
  assert.equal(first.value.includes("legacy-sftp-password"), false);
  assert.equal(decryptPortalString(first.value), "legacy-sftp-password");

  assert.deepEqual(migratePortalCredential(first.value), {
    value: first.value,
    migrated: false,
  });
});

test("portal migration validates existing ciphertext with the active key", () => {
  const originalKey = process.env.ZORVA_PHI_ENCRYPTION_KEY!;
  const encrypted = migratePortalCredential("credential").value;
  process.env.ZORVA_PHI_ENCRYPTION_KEY = randomBytes(32).toString("base64url");
  try {
    assert.throws(() => migratePortalCredential(encrypted), /authenticate|Unsupported state/i);
  } finally {
    process.env.ZORVA_PHI_ENCRYPTION_KEY = originalKey;
  }
});

test("audit text migration encrypts both copies and rejects disagreement", () => {
  const migrated = migrateAuditTextFields(
    "patient-specific explanation",
    JSON.stringify({ findingId: "f1", reason: "other_with_text", reasonText: "patient-specific explanation" }),
  );
  assert.equal(migrated.migrated, true);
  assert.equal(decryptPortalString(migrated.reasonText!), "patient-specific explanation");
  const parsed = JSON.parse(migrated.dataElements) as { reasonText: string };
  assert.equal(decryptPortalString(parsed.reasonText), "patient-specific explanation");
  assert.equal(migrateAuditTextFields(migrated.reasonText, migrated.dataElements).migrated, false);

  assert.throws(
    () => migrateAuditTextFields("one", JSON.stringify({ reasonText: "two" })),
    /disagree/,
  );
});
