"use client";

// /billing — interactive actions panel.
//
// Three actions:
//   1. Update payment method  →  GET /api/billing/portal-redirect
//   2. Change tier            →  POST /api/billing/change-tier
//   3. Cancel subscription    →  POST /api/billing/cancel-subscription
//
// Each action has its own loading + error state so the panel never
// gets stuck because of one failure. After a successful mutation we
// call router.refresh() to re-fetch the server-rendered sections
// (the page itself is force-dynamic, so a refresh triggers a fresh
// data load).
//
// In demo mode (no STRIPE_SECRET_KEY configured):
//   - Update payment is disabled and shows a hint
//   - Change tier is disabled
//   - Cancel is disabled
// This matches the design choice from the pricing page — demo
// mode is for UI testing, not for exercising real billing flows.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { toUserFacingError } from "@/lib/ui-error";
import styles from "./billing.module.css";

type TierId = "small" | "mid" | "large";
type CurrencyCode = "CAD" | "USD";

interface TierOption {
  id: TierId;
  name: string;
  auditCap: number;
  priceCAD: number;
  priceUSD: number;
  currencyPrimary: CurrencyCode;
}

interface BillingActionsProps {
  tenantId: string;
  currentTier: TierId | null;
  currentStatus: string;
  hasStripeCustomer: boolean;
  demo: boolean;
  tiers: TierOption[];
}

function formatPrice(n: number, code: CurrencyCode): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
      maximumFractionDigits: 0,
    }).format(n);
  } catch {
    const sign = code === "USD" ? "$" : "CA$";
    return `${sign}${n.toLocaleString("en-US")}`;
  }
}

export function BillingActions({
  tenantId,
  currentTier,
  currentStatus,
  hasStripeCustomer,
  demo,
  tiers,
}: BillingActionsProps) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  // Per-action state so they don't block each other.
  const [paymentBusy, setPaymentBusy] = useState(false);
  const [paymentError, setPaymentError] = useState<string | null>(null);

  const [tierBusy, setTierBusy] = useState(false);
  const [tierError, setTierError] = useState<string | null>(null);
  const [selectedTier, setSelectedTier] = useState<TierId | "">(
    currentTier ?? "",
  );
  const [tierCurrency, setTierCurrency] = useState<CurrencyCode>(
    tiers[0]?.currencyPrimary ?? "CAD",
  );

  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelConfirm, setCancelConfirm] = useState(false);
  const [canceled, setCanceled] = useState(
    currentStatus === "canceled",
  );

  function handleUpdatePayment() {
    setPaymentError(null);
    setPaymentBusy(true);
    // The portal-redirect route 302s to Stripe; we just navigate.
    window.location.href = `/api/billing/portal-redirect?tenantId=${encodeURIComponent(tenantId)}`;
  }

  async function handleChangeTier() {
    if (!selectedTier) {
      setTierError("Pick a tier to switch to.");
      return;
    }
    setTierError(null);
    setTierBusy(true);
    try {
      const res = await fetch("/api/billing/change-tier", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenantId,
          newTierId: selectedTier,
          currency: tierCurrency,
        }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        error?: string;
        message?: string;
        tier?: string;
        status?: string;
      };
      if (!res.ok) {
        setTierError(
          data.message ?? data.error ?? `Request failed (${res.status})`,
        );
        return;
      }
      // Success — refresh server-rendered sections.
      startTransition(() => router.refresh());
    } catch (e) {
      setTierError(
        toUserFacingError(e, "Network error during tier change."),
      );
    } finally {
      setTierBusy(false);
    }
  }

  async function handleCancel() {
    if (!cancelConfirm) {
      // Show the confirm UI; the actual call only fires after the
      // user ticks the box and clicks again. This is the "30-day
      // grace-period warning" — the subscription continues until
      // the period end (handled by Stripe's cancel_at_period_end),
      // and the data retention window is the existing 30-day
      // purge from the webhook handler.
      setCancelConfirm(true);
      return;
    }
    setCancelError(null);
    setCancelBusy(true);
    try {
      const res = await fetch("/api/billing/cancel-subscription", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenantId, confirm: true }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        error?: string;
        message?: string;
        cancelAt?: string;
      };
      if (!res.ok) {
        setCancelError(
          data.message ?? data.error ?? `Request failed (${res.status})`,
        );
        return;
      }
      setCanceled(true);
      setCancelConfirm(false);
      startTransition(() => router.refresh());
    } catch (e) {
      setCancelError(
        toUserFacingError(e, "Network error during cancel."),
      );
    } finally {
      setCancelBusy(false);
    }
  }

  const disabledAll = demo || canceled;
  const paymentDisabled = disabledAll || !hasStripeCustomer || paymentBusy;
  const tierDisabled = disabledAll || tierBusy || !hasStripeCustomer;
  const cancelDisabled =
    disabledAll || cancelBusy || currentStatus === "canceled";

  return (
    <div className={styles.actions}>
      {demo ? (
        <p className={styles.demoHint} role="note">
          Demo mode — billing mutations are disabled. Configure
          STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET to test real
          flows.
        </p>
      ) : null}
      {canceled ? (
        <p className={styles.canceledHint} role="note">
          Subscription canceled. Re-subscribe from the{" "}
          <a href="/pricing" className={styles.link}>pricing page</a>.
        </p>
      ) : null}

      <section className={styles.actionBlock}>
        <h3>Payment method</h3>
        <p className={styles.muted}>
          Open the Stripe Customer Portal to update your card, billing
          address, or tax details.
        </p>
        <button
          type="button"
          className={styles.button}
          onClick={handleUpdatePayment}
          disabled={paymentDisabled}
          data-testid="update-payment"
        >
          {paymentBusy ? "Opening…" : "Update payment method"}
        </button>
        {paymentError ? (
          <p className={styles.error} role="alert">
            {paymentError}
          </p>
        ) : null}
        {!hasStripeCustomer ? (
          <p className={styles.muted}>
            You haven&rsquo;t subscribed to a plan yet — start at{" "}
            <a href="/pricing" className={styles.link}>pricing</a>.
          </p>
        ) : null}
      </section>

      <section className={styles.actionBlock}>
        <h3>Change tier</h3>
        <p className={styles.muted}>
          Switch to a different plan. Stripe will prorate the change.
        </p>
        <label className={styles.field}>
          <span>New tier</span>
          <select
            value={selectedTier}
            onChange={(e) => setSelectedTier(e.target.value as TierId)}
            disabled={tierDisabled}
            data-testid="tier-select"
          >
            <option value="">— select —</option>
            {tiers.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} (up to {t.auditCap.toLocaleString("en-US")} audits)
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>Currency</span>
          <select
            value={tierCurrency}
            onChange={(e) => setTierCurrency(e.target.value as CurrencyCode)}
            disabled={tierDisabled}
            data-testid="tier-currency"
          >
            <option value="CAD">
              CAD · {selectedTier ? formatPrice(tiers.find((t) => t.id === selectedTier)?.priceCAD ?? 0, "CAD") : "—"}
            </option>
            <option value="USD">
              USD · {selectedTier ? formatPrice(tiers.find((t) => t.id === selectedTier)?.priceUSD ?? 0, "USD") : "—"}
            </option>
          </select>
        </label>
        <button
          type="button"
          className={styles.button}
          onClick={handleChangeTier}
          disabled={tierDisabled || !selectedTier}
          data-testid="change-tier"
        >
          {tierBusy ? "Updating…" : isPending ? "Refreshing…" : "Change tier"}
        </button>
        {tierError ? (
          <p className={styles.error} role="alert">
            {tierError}
          </p>
        ) : null}
      </section>

      <section className={styles.actionBlock}>
        <h3>Cancel subscription</h3>
        <p className={styles.muted}>
          Service continues until the end of your current billing
          period. Data is retained for 30 days after the period
          closes.
        </p>
        {!cancelConfirm ? (
          <button
            type="button"
            className={`${styles.button} ${styles.buttonDanger}`}
            onClick={handleCancel}
            disabled={cancelDisabled}
            data-testid="cancel-init"
          >
            Cancel subscription…
          </button>
        ) : (
          <>
            <p className={styles.warning} role="alert">
              <strong>Confirm cancellation?</strong> Your subscription
              stays active until the end of the current billing period
              (no further invoices will be issued after that). Data is
              retained for 30 days.
            </p>
            <div className={styles.confirmRow}>
              <button
                type="button"
                className={`${styles.button} ${styles.buttonDanger}`}
                onClick={handleCancel}
                disabled={cancelBusy}
                data-testid="cancel-confirm"
              >
                {cancelBusy ? "Canceling…" : "Yes, cancel"}
              </button>
              <button
                type="button"
                className={styles.buttonSecondary}
                onClick={() => setCancelConfirm(false)}
                disabled={cancelBusy}
                data-testid="cancel-abort"
              >
                Never mind
              </button>
            </div>
          </>
        )}
        {cancelError ? (
          <p className={styles.error} role="alert">
            {cancelError}
          </p>
        ) : null}
      </section>
    </div>
  );
}
