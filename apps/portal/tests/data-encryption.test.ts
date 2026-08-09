import { test } from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";

import {
  decryptPortalBuffer,
  decryptPortalString,
  encryptPortalBuffer,
  encryptPortalString,
  isPortalEncryptedBuffer,
  isPortalEncryptedString,
  decryptPortalNullableString,
  encryptPortalNullableString,
} from "../src/lib/data-encryption";

const TEST_KEY = randomBytes(32).toString("base64url");

test("portal encryption hides and round-trips PHI bytes", () => {
  process.env.ZORVA_PHI_ENCRYPTION_KEY = TEST_KEY;
  const plaintext = Buffer.from("CLM*PATIENT-SECRET*100~", "utf8");
  const encrypted = encryptPortalBuffer(plaintext);

  assert.equal(encrypted.includes(plaintext), false);
  assert.deepEqual(decryptPortalBuffer(encrypted), plaintext);
});

test("portal encryption hides and round-trips credentials", () => {
  process.env.ZORVA_PHI_ENCRYPTION_KEY = TEST_KEY;
  const encrypted = encryptPortalString("SFTP-PASSWORD-SECRET");

  assert.equal(encrypted.includes("SFTP-PASSWORD-SECRET"), false);
  assert.equal(decryptPortalString(encrypted), "SFTP-PASSWORD-SECRET");
});

test("portal encryption fails closed without a valid 32-byte key", () => {
  delete process.env.ZORVA_PHI_ENCRYPTION_KEY;
  assert.throws(() => encryptPortalBuffer(Buffer.from("PHI")), /required/);
  process.env.ZORVA_PHI_ENCRYPTION_KEY = "too-short";
  assert.throws(() => encryptPortalString("secret"), /32 bytes/);
});

test("portal encrypted format detection never mistakes plaintext for ciphertext", () => {
  process.env.ZORVA_PHI_ENCRYPTION_KEY = TEST_KEY;
  const encrypted = encryptPortalBuffer(Buffer.from("claim data"));
  assert.equal(isPortalEncryptedBuffer(encrypted), true);
  assert.equal(isPortalEncryptedBuffer(Buffer.from("claim data")), false);

  const credential = encryptPortalString("secret");
  assert.equal(isPortalEncryptedString(credential), true);
  assert.equal(isPortalEncryptedString("secret"), false);
});

test("nullable portal fields encrypt values and preserve null", () => {
  process.env.ZORVA_PHI_ENCRYPTION_KEY = TEST_KEY;
  assert.equal(encryptPortalNullableString(null), null);
  assert.equal(decryptPortalNullableString(null), null);
  const encrypted = encryptPortalNullableString("patient-related free text");
  assert.ok(encrypted);
  assert.equal(encrypted.includes("patient-related"), false);
  assert.equal(decryptPortalNullableString(encrypted), "patient-related free text");
  assert.throws(() => decryptPortalNullableString("legacy plaintext"), /plaintext/);
});
