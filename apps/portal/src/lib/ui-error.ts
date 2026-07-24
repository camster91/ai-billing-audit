/**
 * Map thrown/network errors to safe, user-facing copy.
 *
 * Never echo raw `Error.message` from fetch failures — browsers
 * surface "Failed to fetch" / TypeError text, and API routes that
 * accidentally leak details would otherwise reach the UI.
 */

const OFFLINE_MSG =
  "You appear to be offline. Check your connection and try again.";
const NETWORK_MSG = "Network error. Please try again.";
const DEFAULT_MSG = "Something went wrong. Please try again.";

const NETWORK_RE =
  /failed to fetch|networkerror|load failed|network request failed|fetch failed/i;

export function toUserFacingError(
  err: unknown,
  fallback: string = DEFAULT_MSG,
): string {
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    return OFFLINE_MSG;
  }
  if (err instanceof TypeError) {
    return NETWORK_MSG;
  }
  if (err instanceof Error && NETWORK_RE.test(err.message)) {
    return NETWORK_MSG;
  }
  // Known stable API error codes we intentionally surface.
  if (err instanceof Error) {
    const code = err.message.trim();
    if (
      /^(unauthenticated|forbidden|invalid_|finding_|audit_|stripe_|platform_)/i.test(
        code,
      ) ||
      code === "audit_write_failed" ||
      code === "finding_terminal" ||
      code === "finding_not_found" ||
      code === "stripe_unavailable"
    ) {
      return humanizeApiCode(code);
    }
    // HTTP status fallbacks from our own throw sites.
    if (/^HTTP \d{3}$/.test(code) || /^Accept failed|^Dismiss failed|^Request failed|^Save failed/i.test(code)) {
      return fallback;
    }
  }
  return fallback;
}

function humanizeApiCode(code: string): string {
  switch (code) {
    case "unauthenticated":
      return "Please sign in and try again.";
    case "forbidden":
      return "You don't have permission to do that.";
    case "finding_terminal":
      return "This finding was already accepted or dismissed.";
    case "finding_not_found":
      return "That finding could not be found.";
    case "audit_write_failed":
      return "Could not save the audit entry. Please try again.";
    case "stripe_unavailable":
      return "Billing is temporarily unavailable. Please try again shortly.";
    default:
      return DEFAULT_MSG;
  }
}
