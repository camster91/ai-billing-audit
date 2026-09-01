import {
  createCipheriv,
  createDecipheriv,
  createHash,
  randomBytes,
} from "node:crypto";
import { safeReturnUrl } from "./email-mask";

export const PENDING_MAGIC_LINK_COOKIE = "zorva_pending_magic_link";
export const PENDING_MAGIC_LINK_MAX_AGE_SECONDS = 10 * 60;
export const MAGIC_LINK_RESEND_COOLDOWN_SECONDS = 60;

export interface PendingMagicLink {
  email: string;
  from: string;
  sentAt: number;
}

function encryptionKey(): Buffer {
  const secret = process.env.AUTH_SECRET ?? process.env.NEXTAUTH_SECRET;
  if (secret) return createHash("sha256").update(secret).digest();
  if (process.env.NODE_ENV === "production") {
    throw new Error("AUTH_SECRET is required for pending magic-link state.");
  }
  return createHash("sha256")
    .update("zorva-development-pending-magic-link-only")
    .digest();
}

function decodeCanonicalBase64Url(value: string): Buffer | null {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) return null;
  const decoded = Buffer.from(value, "base64url");
  return decoded.toString("base64url") === value ? decoded : null;
}

export function sealPendingMagicLink(state: PendingMagicLink): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey(), iv);
  const plaintext = Buffer.from(JSON.stringify(state), "utf8");
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const tag = cipher.getAuthTag();
  return ["v1", iv.toString("base64url"), tag.toString("base64url"), ciphertext.toString("base64url")].join(".");
}

export function openPendingMagicLink(value: string | undefined): PendingMagicLink | null {
  if (!value) return null;
  try {
    const [version, ivPart, tagPart, ciphertextPart, extra] = value.split(".");
    if (version !== "v1" || !ivPart || !tagPart || !ciphertextPart || extra) {
      return null;
    }
    const iv = decodeCanonicalBase64Url(ivPart);
    const tag = decodeCanonicalBase64Url(tagPart);
    const ciphertext = decodeCanonicalBase64Url(ciphertextPart);
    if (!iv || iv.length !== 12 || !tag || tag.length !== 16 || !ciphertext) return null;
    const decipher = createDecipheriv(
      "aes-256-gcm",
      encryptionKey(),
      iv,
    );
    decipher.setAuthTag(tag);
    const plaintext = Buffer.concat([
      decipher.update(ciphertext),
      decipher.final(),
    ]);
    const parsed = JSON.parse(plaintext.toString("utf8")) as Partial<PendingMagicLink>;
    if (
      typeof parsed.email !== "string" ||
      !parsed.email ||
      parsed.email.length > 320 ||
      typeof parsed.from !== "string" ||
      safeReturnUrl(parsed.from) !== parsed.from ||
      typeof parsed.sentAt !== "number" ||
      !Number.isFinite(parsed.sentAt)
    ) {
      return null;
    }
    return { email: parsed.email, from: parsed.from, sentAt: parsed.sentAt };
  } catch {
    return null;
  }
}

export function secondsUntilMagicLinkResend(
  state: Pick<PendingMagicLink, "sentAt">,
  now = Date.now(),
): number {
  const elapsedSeconds = Math.floor(Math.max(0, now - state.sentAt) / 1000);
  return Math.max(0, MAGIC_LINK_RESEND_COOLDOWN_SECONDS - elapsedSeconds);
}
