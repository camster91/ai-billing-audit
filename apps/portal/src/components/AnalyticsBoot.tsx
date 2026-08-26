"use client";

// Analytics client boot — runs once per page load. Captures UTM
// parameters from the URL (or sessionStorage for return visits),
// exposes a small typed `analytics` function that the rest of the
// app can call, and forwards events to both Plausible (when
// NEXT_PUBLIC_PLAUSIBLE_DOMAIN is set) and the self-hosted
// /api/analytics/event beacon.
//
// This module is intentionally framework-agnostic so it can be
// unit-tested with a fake window / document. The companion test
// file exercises the schema in node:test without mounting React.
//
// Privacy contract (see apps/portal/src/lib/analytics-events.ts):
//   - Schema-validated events only.
//   - No PII in any payload.
//   - UTM is captured from the URL and persisted in sessionStorage.

import {
  ALLOWED_EVENTS,
  UTM_KEYS,
  assertSafePayload,
  ensurePlausibleQueue,
  readSessionUTM,
  readStoredUTM,
  readUTMFromURL,
  truncateText,
  type AnalyticsEventName,
  type PlausibleFunction,
  type UTM,
} from "@/lib/analytics-events";

declare global {
  interface Window {
    plausible?: PlausibleFunction;
    __zorvaAnalyticsBooted?: boolean;
  }
}

function getWindow(): Window | null {
  if (typeof window === "undefined") return null;
  return window;
}

function getStoredUTM(): UTM {
  return readSessionUTM();
}

/** Build a payload that always carries the session's UTM source. */
function withUTM(payload: Record<string, unknown>, utm: UTM): Record<string, unknown> {
  const out: Record<string, unknown> = { ...payload };
  for (const k of UTM_KEYS) {
    const v = utm[k];
    if (v) out[k] = v;
  }
  return out;
}

function sendBeacon(event: string, payload: Record<string, unknown>) {
  const w = getWindow();
  if (!w) return;
  const body = JSON.stringify({ event, ts: Date.now(), ...payload });
  const beacon = (w.navigator as Navigator & {
    sendBeacon?: (url: string, data?: BodyInit | null) => boolean;
  }).sendBeacon;
  if (typeof beacon === "function") {
    const ok = beacon.call(
      w.navigator,
      "/api/analytics/event",
      new Blob([body], { type: "application/json" }),
    );
    if (ok) return;
  }
  if (typeof w.fetch === "function") {
    w.fetch("/api/analytics/event", {
      method: "POST",
      body,
      keepalive: true,
      headers: { "content-type": "application/json" },
    }).catch(() => {
      /* best-effort */
    });
  }
}

/**
 * Send a typed analytics event. Returns true if the event was
 * accepted, false if the payload was rejected by the schema guard
 * (caller should log the rejection in development).
 */
export function track(
  event: AnalyticsEventName,
  payload: Record<string, unknown>,
  utm?: UTM,
): boolean {
  if (!ALLOWED_EVENTS.has(event)) return false;
  const enriched = withUTM(payload, utm ?? getStoredUTM());
  let safe: Record<string, unknown>;
  try {
    safe = assertSafePayload(event, enriched);
  } catch {
    return false;
  }
  const w = getWindow();
  if (w?.plausible) {
    try {
      w.plausible(event, { props: safe });
    } catch {
      /* fall through to beacon */
    }
  }
  sendBeacon(event, safe);
  return true;
}

/** Re-export for tests / one-off callers. */
export { truncateText, assertSafePayload, readUTMFromURL, readStoredUTM };

/**
 * Boot the analytics client once per page load. Captures UTM,
 * wires the delegated click handler (extends the existing
 * AnalyticsClick component), and returns a cleanup function.
 *
 * Mount via <AnalyticsBoot /> near the root of the public pages.
 */
export function bootAnalytics(): () => void {
  const w = getWindow();
  if (!w) return () => {};
  if (w.__zorvaAnalyticsBooted) return () => {};
  w.__zorvaAnalyticsBooted = true;

  // Plausible loads asynchronously. Install its canonical queue first so
  // interactions during script startup are replayed instead of discarded.
  ensurePlausibleQueue(w);
  readUTMFromURL();

  // Wire a delegated click handler for elements with data-analytics="<cta_id>".
  // The dataLayer push and existing AnalyticsClick component still fire too;
  // this adds a typed `cta_click` event with UTM attribution.
  const onClick = (ev: Event) => {
    const target = ev.target;
    if (!(target instanceof Element)) return;
    const el = target.closest<HTMLElement>("[data-analytics]");
    if (!el) return;
    const name = el.dataset.analytics;
    if (!name) return;
    track("cta_click", {
      cta_id: name,
      page_path: w.location.pathname,
      href: el.getAttribute("href") ?? "",
      text: truncateText(el.textContent ?? "", 80),
    });
  };
  document.addEventListener("click", onClick, { capture: true });

  return () => {
    document.removeEventListener("click", onClick, { capture: true } as EventListenerOptions);
    if (w) w.__zorvaAnalyticsBooted = false;
  };
}

export default function AnalyticsBoot() {
  if (typeof window !== "undefined") {
    // Schedule on the next microtask so the component can render
    // synchronously without blocking paint.
    queueMicrotask(() => bootAnalytics());
  }
  return null;
}
