import { randomUUID } from "node:crypto";
import { readdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  encryptPortalBuffer,
  encryptPortalString,
  decryptPortalString,
  decryptPortalBuffer,
  isPortalEncryptedBuffer,
  isPortalEncryptedString,
} from "./data-encryption";

export interface PortalUploadMigrationResult {
  migrated: number;
  skipped: number;
}

async function replaceFile(target: string, encrypted: Buffer): Promise<void> {
  const staged = `${target}.${randomUUID()}.enc.tmp`;
  await writeFile(staged, encrypted, { flag: "wx", mode: 0o600 });
  try {
    await rename(staged, target);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (process.platform !== "win32" || (code !== "EEXIST" && code !== "EPERM")) {
      await rm(staged, { force: true });
      throw error;
    }
    // Windows does not consistently replace an existing file with rename().
    // Production runs on Linux and uses the atomic branch above.
    await rm(target);
    await rename(staged, target);
  }
}

export async function migratePortalUploadDirectory(
  uploadDir: string,
): Promise<PortalUploadMigrationResult> {
  let entries;
  try {
    entries = await readdir(uploadDir, { withFileTypes: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return { migrated: 0, skipped: 0 };
    }
    throw error;
  }
  let migrated = 0;
  let skipped = 0;

  for (const entry of entries) {
    if (!entry.isFile() || entry.name.endsWith(".plaintext.bak.enc") || entry.name.endsWith(".enc.tmp")) {
      continue;
    }
    const target = path.join(uploadDir, entry.name);
    const payload = await readFile(target);
    if (isPortalEncryptedBuffer(payload)) {
      decryptPortalBuffer(payload);
      skipped += 1;
      continue;
    }

    const backup = `${target}.plaintext.bak.enc`;
    const encrypted = encryptPortalBuffer(payload);
    try {
      await writeFile(backup, encrypted, { flag: "wx", mode: 0o600 });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "EEXIST") {
        throw new Error(`encrypted backup already exists: ${backup}`);
      }
      throw error;
    }
    await replaceFile(target, encrypted);
    migrated += 1;
  }

  return { migrated, skipped };
}

export function migratePortalCredential(value: string): {
  value: string;
  migrated: boolean;
} {
  if (isPortalEncryptedString(value)) {
    decryptPortalString(value);
    return { value, migrated: false };
  }
  return { value: encryptPortalString(value), migrated: true };
}

export function migrateAuditTextFields(
  reasonText: string | null,
  dataElements: string,
): { reasonText: string | null; dataElements: string; migrated: boolean } {
  let parsed: Record<string, unknown>;
  try {
    const value = JSON.parse(dataElements) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("not an object");
    }
    parsed = value as Record<string, unknown>;
  } catch (error) {
    throw new Error(
      `audit dataElements is not valid JSON object: ${error instanceof Error ? error.message : String(error)}`,
    );
  }

  const embedded = parsed.reasonText;
  if (embedded !== null && embedded !== undefined && typeof embedded !== "string") {
    throw new Error("audit dataElements.reasonText must be a string or null");
  }
  const columnPlain =
    reasonText === null
      ? null
      : isPortalEncryptedString(reasonText)
        ? decryptPortalString(reasonText)
        : reasonText;
  const embeddedValue = typeof embedded === "string" ? embedded : null;
  const embeddedPlain =
    embeddedValue === null
      ? null
      : isPortalEncryptedString(embeddedValue)
        ? decryptPortalString(embeddedValue)
        : embeddedValue;
  if (columnPlain !== embeddedPlain) {
    throw new Error("audit reasonText copies disagree");
  }

  let migrated = false;
  let protectedColumn = reasonText;
  if (reasonText !== null && !isPortalEncryptedString(reasonText)) {
    protectedColumn = encryptPortalString(reasonText);
    migrated = true;
  }
  if (embeddedValue !== null && !isPortalEncryptedString(embeddedValue)) {
    parsed.reasonText = encryptPortalString(embeddedValue);
    migrated = true;
  }
  return {
    reasonText: protectedColumn,
    dataElements: JSON.stringify(parsed, Object.keys(parsed).sort()),
    migrated,
  };
}
