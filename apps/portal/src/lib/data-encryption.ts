import {
  createCipheriv,
  createDecipheriv,
  randomBytes,
} from "node:crypto";

const MAGIC = Buffer.from("zorva-aesgcm-v1\0", "ascii");
const IV_BYTES = 12;
const TAG_BYTES = 16;
const STRING_PREFIX = "zorva:v1:";

export function isPortalEncryptedBuffer(payload: Buffer): boolean {
  return payload.length >= MAGIC.length && payload.subarray(0, MAGIC.length).equals(MAGIC);
}

export function isPortalEncryptedString(payload: string): boolean {
  return payload.startsWith(STRING_PREFIX);
}

function encryptionKey(): Buffer {
  const configured = process.env.ZORVA_PHI_ENCRYPTION_KEY?.trim();
  if (!configured) {
    throw new Error("ZORVA_PHI_ENCRYPTION_KEY is required for portal storage");
  }
  let key: Buffer;
  try {
    key = Buffer.from(configured, "base64url");
  } catch {
    throw new Error("ZORVA_PHI_ENCRYPTION_KEY must be valid base64url");
  }
  if (key.length !== 32) {
    throw new Error("ZORVA_PHI_ENCRYPTION_KEY must decode to exactly 32 bytes");
  }
  return key;
}

export function encryptPortalBuffer(plaintext: Buffer): Buffer {
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey(), iv);
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  return Buffer.concat([MAGIC, iv, cipher.getAuthTag(), ciphertext]);
}

export function decryptPortalBuffer(payload: Buffer): Buffer {
  if (!isPortalEncryptedBuffer(payload)) {
    throw new Error("portal data is plaintext, corrupt, or uses an unknown format");
  }
  const ivStart = MAGIC.length;
  const tagStart = ivStart + IV_BYTES;
  const ciphertextStart = tagStart + TAG_BYTES;
  if (payload.length < ciphertextStart) {
    throw new Error("portal encrypted payload is truncated");
  }
  const decipher = createDecipheriv(
    "aes-256-gcm",
    encryptionKey(),
    payload.subarray(ivStart, tagStart),
  );
  decipher.setAuthTag(payload.subarray(tagStart, ciphertextStart));
  return Buffer.concat([
    decipher.update(payload.subarray(ciphertextStart)),
    decipher.final(),
  ]);
}

export function encryptPortalString(plaintext: string): string {
  return STRING_PREFIX + encryptPortalBuffer(Buffer.from(plaintext, "utf8")).toString("base64url");
}

export function decryptPortalString(payload: string): string {
  if (!isPortalEncryptedString(payload)) {
    throw new Error("portal credential is plaintext, corrupt, or uses an unknown format");
  }
  return decryptPortalBuffer(
    Buffer.from(payload.slice(STRING_PREFIX.length), "base64url"),
  ).toString("utf8");
}

export function encryptPortalNullableString(value: string | null): string | null {
  return value === null ? null : encryptPortalString(value);
}

export function decryptPortalNullableString(value: string | null): string | null {
  return value === null ? null : decryptPortalString(value);
}
