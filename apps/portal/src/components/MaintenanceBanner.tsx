// MaintenanceBanner.tsx — site-wide banner shown when we deploy or have
// a known incident.
//
// Kanban: t_46085e07 on board 'product-ux'.
//
// Reads the maintenance status from a public config endpoint
// (/api/maintenance) so the banner can be toggled without a redeploy.
// The endpoint returns { active: bool, message?: string, severity?: "info"|"warn"|"critical" }.
//
// Banner colors:
//   - info: blue background, normal copy
//   - warn: yellow background, "we're investigating"
//   - critical: red background, "service degraded — accept/dismiss may be slow"
//
// Dismissable per session via localStorage. If `force` is true on the
// server response, the banner cannot be dismissed.

"use client";

import { useEffect, useState } from "react";
import styles from "./MaintenanceBanner.module.css";

interface MaintenanceState {
  active: boolean;
  message?: string;
  severity?: "info" | "warn" | "critical";
  force?: boolean;
}

const DISMISS_KEY = "zorva.maintenance.dismissedAt";
const DISMISS_TTL_MS = 60 * 60 * 1000; // re-show after 1 hour

export function MaintenanceBanner() {
  const [state, setState] = useState<MaintenanceState | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      try {
        const r = await fetch("/api/maintenance", { cache: "no-store" });
        if (!r.ok) return;
        const j = (await r.json()) as MaintenanceState;
        if (cancelled) return;
        setState(j);
        const dismissedAt = Number(localStorage.getItem(DISMISS_KEY) ?? "0");
        const stillDismissed = Date.now() - dismissedAt < DISMISS_TTL_MS;
        if (!j.force && stillDismissed) setDismissed(true);
      } catch {
        // Banner silently absent on network errors.
      }
    }
    tick();
    // Re-poll every 60s so a deploy during a session surfaces.
    const iv = window.setInterval(tick, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(iv);
    };
  }, []);

  if (!state?.active || dismissed) return null;
  const severity = state.severity ?? "info";

  return (
    <div
      role={severity === "critical" ? "alert" : "status"}
      aria-live={severity === "critical" ? "assertive" : "polite"}
      className={`${styles.banner} ${styles[severity]}`}
    >
      <div className={styles.message}>
        {state.message ?? "Heads up: Zorva is undergoing scheduled maintenance."}
      </div>
      {!state.force && (
        <button
          type="button"
          className={styles.dismiss}
          onClick={() => {
            localStorage.setItem(DISMISS_KEY, String(Date.now()));
            setDismissed(true);
          }}
          aria-label="Dismiss maintenance notice"
        >
          ×
        </button>
      )}
    </div>
  );
}
