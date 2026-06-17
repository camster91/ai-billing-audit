"use client";

// Lightweight analytics beacon. Fires on click for any element carrying
// data-analytics="<event_name>". The sendBeacon path is the canonical
// "fire-and-forget" channel: it survives page-unload (which happens
// immediately when the user clicks a real /security.pdf download link),
// unlike fetch() with keepalive. If sendBeacon isn't available we fall back
// to fetch with keepalive. We also push to window.dataLayer so a GTM /
// GA4 / Plausible tag installed later on can pick the event up without
// re-wiring the markup.
//
// /security.pdf is a static asset, not a real endpoint. The fetch below
// is best-effort; a 404 just means no listener is configured yet, which
// is fine for v1. The console log is the developer-facing breadcrumb.

type Beacon = (
  url: string,
  data?: BodyInit | null,
  opts?: { type?: string }
) => boolean;

function isFn(x: unknown): x is Beacon {
  return typeof x === "function";
}

function send(event: string, payload: Record<string, unknown>) {
  if (typeof window === "undefined") return;
  const body = JSON.stringify({ event, ts: Date.now(), ...payload });

  // 1. dataLayer push (GTM convention) — harmless if no GTM is installed.
  const w = window as unknown as { dataLayer?: unknown[] };
  if (Array.isArray(w.dataLayer)) {
    w.dataLayer.push({ event, ...payload });
  } else {
    w.dataLayer = [{ event, ...payload }];
  }

  // 2. sendBeacon (survives page-unload during a download click)
  const endpoint = "/api/analytics/event";
  const beacon = (navigator as Navigator & { sendBeacon?: Beacon })
    .sendBeacon;
  if (isFn(beacon)) {
    const ok = beacon.call(navigator, endpoint, new Blob([body], { type: "application/json" }));
    if (ok) return;
  }

  // 3. fetch keepalive fallback
  if (typeof fetch === "function") {
    fetch(endpoint, {
      method: "POST",
      body,
      keepalive: true,
      headers: { "content-type": "application/json" },
    }).catch(() => {
      /* best-effort */
    });
  }

  // 4. dev breadcrumb
  // eslint-disable-next-line no-console
  console.log("[analytics]", event, payload);
}

export default function AnalyticsClick() {
  if (typeof window !== "undefined") {
    // Delegated click handler attached once per page load.
    const existing = (window as unknown as { __analyticsWired?: boolean })
      .__analyticsWired;
    if (!existing) {
      (window as unknown as { __analyticsWired?: boolean }).__analyticsWired = true;
      document.addEventListener(
        "click",
        (ev) => {
          const target = ev.target;
          if (!(target instanceof Element)) return;
          const el = target.closest<HTMLElement>("[data-analytics]");
          if (!el) return;
          const name = el.dataset.analytics;
          if (!name) return;
          send(name, {
            href: el.getAttribute("href"),
            text: (el.textContent || "").trim().slice(0, 80),
            path: window.location.pathname,
          });
        },
        { capture: true }
      );
    }
  }
  return null;
}
