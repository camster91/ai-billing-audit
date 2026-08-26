// Privacy-conscious analytics event schema and helpers (issue #75).
//
// Rules:
//   - NO names, emails, clinic names, message text, IP, User-Agent, or
//     stable personal identifiers in any event payload.
//   - The only personal-data-adjacent property is `claim_volume_bucket`
//     (a coarse bucket string) and `billing_setup` (a 3-valued enum)
//     on the contact_submit_success event. These are aggregated counts,
//     not identifiers.
//   - The schema is closed: events are validated against this list
//     server-side and dropped on mismatch. Adding a new event requires
//     editing this file and a code review.
//
// Backend:
//   - Plausible (NEXT_PUBLIC_PLAUSIBLE_DOMAIN env var) for page views
//     and custom-event counts. Plausible is privacy-focused: no
//     cross-site tracking, no cookies, no personal data.
//   - /api/analytics/event as a self-hosted beacon for events that
//     need a guaranteed server log (e.g. submission-failure error
//     codes). The endpoint logs to stdout today; a future forwarder
//     can attach a real analytics backend without a code change.
//
// Retention:
//   - Plausible: 30 days of aggregate, no per-user, no export.
//   - /api/analytics/event stdout: rolled by the deploy log policy
//     (deployed operators manage this; documented in OPERATIONS_RUNBOOK).

export type AnalyticsEventName =
  | "cta_click"
  | "contact_start"
  | "contact_submit_success"
  | "contact_submit_failure";

export const ALLOWED_EVENTS: ReadonlySet<AnalyticsEventName> = new Set([
  "cta_click",
  "contact_start",
  "contact_submit_success",
  "contact_submit_failure",
]);

/**
 * Properties allowed for each event. Enforced by `assertSafePayload`
 * before any send. New properties require a code change here and a
 * review against the privacy rules at the top of this file.
 */
export const ALLOWED_PROPS: Readonly<Record<AnalyticsEventName, ReadonlySet<string>>> = {
  cta_click: new Set([
    "cta_id",
    "page_path",
    "href",
    "text", // up to 80 chars (caller truncates); never free-form message text
    "utm_source",
    "utm_medium",
    "utm_campaign",
  ]),
  contact_start: new Set([
    "page_path",
    "utm_source",
    "utm_medium",
    "utm_campaign",
  ]),
  contact_submit_success: new Set([
    "claim_volume_bucket", // e.g. "0-100", "100-500", "500-2000", "2000-10000", "10000-100000"
    "billing_setup", // "in_house" | "outsourced" | "hybrid"
    "page_path",
    "utm_source",
    "utm_medium",
    "utm_campaign",
  ]),
  contact_submit_failure: new Set([
    "error_code", // server-side error string, e.g. "invalid_input", "disposable_email", "rate_limited", "internal_error"
    "page_path",
    "utm_source",
    "utm_medium",
    "utm_campaign",
  ]),
};

/** Property values that must never appear in a payload, regardless of event. */
export const FORBIDDEN_KEYS: ReadonlySet<string> = new Set([
  "name",
  "clinicName",
  "email",
  "message",
  "patient",
  "patientHash",
  "phone",
  "address",
  "claimVolume", // raw number — use claim_volume_bucket instead
  "ip",
  "userAgent",
  "referer",
]);

/**
 * Throws if the payload contains a forbidden key or a key not in
 * the allow-list for the event. Returns the trimmed payload on
 * success. Callers should send the returned payload verbatim.
 */
export function assertSafePayload(
  event: AnalyticsEventName,
  payload: Record<string, unknown>,
): Record<string, unknown> {
  if (!ALLOWED_EVENTS.has(event)) {
    throw new Error(`unknown analytics event: ${String(event)}`);
  }
  const allowed = ALLOWED_PROPS[event];
  for (const key of Object.keys(payload)) {
    if (FORBIDDEN_KEYS.has(key)) {
      throw new Error(`forbidden analytics key: ${key}`);
    }
    if (!allowed.has(key)) {
      throw new Error(`property ${key} not allowed for event ${event}`);
    }
  }
  // Defensive: drop any property whose value is a non-finite number or
  // contains an object (object values risk leaking structured PII).
  const cleaned: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(payload)) {
    if (v === null || v === undefined) continue;
    if (typeof v === "object") {
      throw new Error(`object value not allowed for analytics key ${k}`);
    }
    if (typeof v === "number" && !Number.isFinite(v)) continue;
    cleaned[k] = v;
  }
  return cleaned;
}

/** Coarse claim-volume bucket. Matches the form's slider range 0-100000. */
export function claimVolumeBucket(n: number): string {
  if (n <= 100) return "0-100";
  if (n <= 500) return "100-500";
  if (n <= 2000) return "500-2000";
  if (n <= 10000) return "2000-10000";
  return "10000-100000";
}

/** Truncate `text` to a safe length for analytics purposes. */
export function truncateText(text: string, max = 80): string {
  const trimmed = text.trim();
  return trimmed.length > max ? trimmed.slice(0, max) : trimmed;
}

/** UTM parameters read from the URL on page load and persisted for the session. */
export interface UTM {
  utm_source: string;
  utm_medium: string;
  utm_campaign: string;
}

export const UTM_KEYS: ReadonlyArray<keyof UTM> = ["utm_source", "utm_medium", "utm_campaign"];

export const EMPTY_UTM: UTM = { utm_source: "", utm_medium: "", utm_campaign: "" };

const UTM_STORAGE_KEY = "zorva:utm:v1";

export interface PlausibleFunction {
  (event: string, options?: { props?: Record<string, unknown> }): void;
  q?: IArguments[];
}

/**
 * Install Plausible's standard pre-load queue without replacing an already
 * loaded client. Events emitted during async script loading are replayed by
 * Plausible when the client becomes available.
 */
export function ensurePlausibleQueue(target: {
  plausible?: PlausibleFunction;
}): PlausibleFunction {
  if (target.plausible) return target.plausible;
  const queued: PlausibleFunction = function () {
    (queued.q ??= []).push(arguments);
  };
  queued.q = [];
  target.plausible = queued;
  return queued;
}

export function readUTMFromURL(href: string = (typeof window !== "undefined" ? window.location.href : "")): UTM {
  if (typeof window === "undefined") return EMPTY_UTM;
  try {
    const u = new URL(href);
    const out: Partial<UTM> = {};
    for (const k of UTM_KEYS) {
      const v = u.searchParams.get(k);
      if (v) out[k] = v.slice(0, 100); // hard cap
    }
    if (Object.keys(out).length > 0) {
      // Persist for the session so events fired later still carry the source.
      try {
        window.sessionStorage.setItem(UTM_STORAGE_KEY, JSON.stringify(out));
      } catch {
        // sessionStorage may be disabled (private mode); proceed in-memory only.
      }
    }
    return { ...EMPTY_UTM, ...out };
  } catch {
    return EMPTY_UTM;
  }
}

/**
 * Prefer campaign values present on the current URL. This deliberately keeps
 * those values in memory even when privacy settings disable sessionStorage.
 */
export function readSessionUTM(href?: string): UTM {
  const fromURL = readUTMFromURL(href);
  if (UTM_KEYS.some((key) => Boolean(fromURL[key]))) return fromURL;
  return readStoredUTM();
}

export function readStoredUTM(): UTM {
  if (typeof window === "undefined") return EMPTY_UTM;
  try {
    const raw = window.sessionStorage.getItem(UTM_STORAGE_KEY);
    if (!raw) return EMPTY_UTM;
    const parsed = JSON.parse(raw) as Partial<UTM>;
    return { ...EMPTY_UTM, ...parsed };
  } catch {
    return EMPTY_UTM;
  }
}
