"use client";

// CheckoutButton — client component that POSTs to /api/billing/checkout
// and redirects to the returned Stripe-hosted URL (or the demo-mode
// local stub). The /pricing page renders two of these per tier (CAD +
// USD) so the customer picks their billing currency at the CTA, not
// at a top-of-page toggle.
//
// The button is intentionally minimal — no form wrapper, no hidden
// inputs, no client-side validation. The server validates tierId and
// currency. Visual feedback is "Submitting…" while the request is
// in flight; on error, the message appears below the button so the
// customer can retry without losing context.

import { useState } from "react";
import type { TierId, CurrencyCode } from "@/lib/pricing";
import styles from "./pricing.module.css";

interface CheckoutButtonProps {
  tierId: TierId;
  currency: CurrencyCode;
  label: string;
  variant: "primary" | "secondary" | "ghost";
}

export function CheckoutButton({ tierId, currency, label, variant }: CheckoutButtonProps) {
  const [state, setState] = useState<"idle" | "submitting" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function onClick() {
    if (state === "submitting") return;
    setState("submitting");
    setErrorMsg(null);
    try {
      const res = await fetch("/api/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tierId, currency }),
      });
      const data = (await res.json()) as { url?: string; error?: string };
      if (!res.ok || !data.url) {
        setState("error");
        setErrorMsg(data.error ?? `Checkout failed (HTTP ${res.status})`);
        return;
      }
      // Success: redirect to Stripe (or the local demo stub).
      window.location.href = data.url;
    } catch (e) {
      setState("error");
      setErrorMsg(e instanceof Error ? e.message : "Network error");
    }
  }

  const className = [
    styles.cta,
    variant === "primary" ? styles.ctaPrimary : "",
    variant === "secondary" ? styles.ctaSecondary : "",
    variant === "ghost" ? styles.ctaGhost : "",
  ].filter(Boolean).join(" ");

  return (
    <div className={styles.ctaWrap}>
      <button
        type="button"
        className={className}
        onClick={onClick}
        disabled={state === "submitting"}
        aria-busy={state === "submitting"}
      >
        {state === "submitting" ? "Submitting…" : label}
      </button>
      {state === "error" && errorMsg && (
        <div className={styles.ctaError} role="alert">
          {errorMsg}
        </div>
      )}
    </div>
  );
}
