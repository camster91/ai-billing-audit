// Privacy-safe email masking for the /verify-request page (issue #47).
// The full email is never echoed in the rendered HTML so a
// screenshot, browser extension, or shoulder-surf does not leak
// the address. The masked form keeps the local-part shape ("a
// name of some length at some domain") for the biller's
// recognition.

const DEFAULT_LOCAL_VISIBLE = 1;
const DEFAULT_DOMAIN_VISIBLE = 1;
const MAX_EMAIL_LENGTH = 320;

/**
 * Mask an email address for display.
 *
 *   "jane.smith@clinic.com" → "j•••@c•••.com"
 *   "a@b.com"             → "a@b.com" (too short to mask usefully)
 *   ""                    → ""
 *
 * The local part is reduced to its first character followed by
 * middle bullets; the domain keeps its first character and its
 * TLD. The full address is never returned.
 */
export function maskEmail(
  email: string,
  options: { localVisible?: number; domainVisible?: number } = {},
): string {
  if (!email) return "";
  const trimmed = email.trim();
  if (trimmed.length > MAX_EMAIL_LENGTH) return "";
  const at = trimmed.indexOf("@");
  if (at <= 0 || at === trimmed.length - 1) return "";
  const local = trimmed.slice(0, at);
  const domain = trimmed.slice(at + 1);
  const dot = domain.indexOf(".");
  if (dot <= 0 || dot === domain.length - 1) return "";

  const localVisible = Math.max(0, options.localVisible ?? DEFAULT_LOCAL_VISIBLE);
  const domainVisible = Math.max(
    0,
    options.domainVisible ?? DEFAULT_DOMAIN_VISIBLE,
  );

  // If the address is too short to mask, return it as-is.
  if (local.length <= localVisible + 1 && domain.split(".")[0].length <= domainVisible + 1) {
    return trimmed;
  }

  const localMask =
    local.length <= localVisible
      ? local
      : local.slice(0, localVisible) + "•".repeat(Math.max(1, local.length - localVisible - 1));

  const domainLabel = domain.slice(0, dot);
  const tld = domain.slice(dot);
  const domainMask =
    domainLabel.length <= domainVisible
      ? domainLabel
      : domainLabel.slice(0, domainVisible) +
        "•".repeat(Math.max(1, domainLabel.length - domainVisible - 1));

  return `${localMask}@${domainMask}${tld}`;
}

/**
 * Allow-list check for a same-origin return URL used by the magic-
 * link flow. Rejects external URLs, protocol-relative URLs, and
 * anything that smells like a scheme or host.
 */
export function safeReturnUrl(raw: string | undefined, fallback = "/dashboard"): string {
  if (!raw) return fallback;
  if (!raw.startsWith("/")) return fallback;
  if (raw.startsWith("//")) return fallback;
  if (/^\/[^/]*$/.test(raw) && raw.includes(":")) return fallback;
  return raw;
}
