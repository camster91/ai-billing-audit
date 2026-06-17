// /billing — client-facing billing page.
//
// Three sections, all server-rendered on initial load for fast first
// paint and SEO-safe metadata:
//
//   1. Current plan card: tier name, status, next invoice date + amount.
//   2. Usage card: audits used / quota for the current month, with a
//      progress bar and reset date.
//   3. Invoice history: last 12 months of invoices, with date,
//      amount, status, and a link to the Stripe-hosted PDF/URL.
//
// Action buttons (update payment, change tier, cancel) are in the
// client component <BillingActions />. They POST to dedicated
// route handlers and re-fetch the affected sections on success —
// keeping the Stripe secret key server-side.
//
// Auth + tenant scope: this page requires a signed-in user with an
// active tenant. The proxy enforces the auth gate; getActiveTenant()
// returns null when the user has memberships but hasn't picked
// one yet (rare — the onboarding flow always sets the first
// membership as active). For users without any tenant we render
// an empty state pointing at /pricing.
//
// No data is exposed to the client bundle that shouldn't be. The
// API responses are tenant-scoped (proxy enforces the membership
// before the request reaches the route), so even if the response
// were cached in the browser it's only ever visible to the owning
// tenant's members.

import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import {
  loadInvoiceHistory,
  loadSubscriptionSnapshot,
  loadUsageSnapshot,
  getPricingConfig,
} from "@/lib/billing-page";
import { isDemoMode } from "@/lib/stripe";
import { PortalNav } from "../portal-nav";
import styles from "../shell.module.css";
import { BillingActions } from "./BillingActions";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Tier name lookup (mirrors the pricing page's name mapping).
const TIER_NAMES: Record<string, string> = {
  small: "Small practice",
  mid: "Mid clinic",
  large: "Large practice",
};

export default async function BillingPage() {
  const session = await auth();
  if (!session?.user?.id) {
    redirect("/login?callbackUrl=/billing");
  }
  const tenant = await getActiveTenant();

  if (!tenant) {
    return (
      <main className={styles.shell}>
        <h1 className={styles.heading}>Billing</h1>
        <section className={styles.empty}>
          <h2>No clinic connected</h2>
          <p>
            You&rsquo;re signed in, but you aren&rsquo;t a member of a clinic
            yet. Subscribe to a plan on the pricing page to get started.
          </p>
          <p>
            <a href="/pricing" className={styles.link}>
              View pricing →
            </a>
          </p>
        </section>
      </main>
    );
  }

  // Fetch all three sections server-side. We use Promise.all so
  // the three queries run in parallel — the page renders only
  // after all three resolve. Each helper handles its own error
  // paths internally and returns safe defaults.
  const [subscription, usage, invoices, tenantRow, pricing] =
    await Promise.all([
      loadSubscriptionSnapshot(tenant.id),
      loadUsageSnapshot(tenant.id),
      loadInvoiceHistory(tenant.id),
      prisma.tenant.findUnique({
        where: { id: tenant.id },
        select: {
          stripeCustomerId: true,
          canceledAt: true,
          firstPaymentFailureAt: true,
          lastPaymentFailureAt: true,
        },
      }),
      Promise.resolve(getPricingConfig()),
    ]);

  const tierName =
    (subscription.tier && TIER_NAMES[subscription.tier]) ?? "—";
  const nextInvoiceDateDisplay = subscription.nextInvoiceAt
    ? new Date(subscription.nextInvoiceAt).toUTCString().slice(0, 16)
    : null;

  return (
    <main className={styles.shell}>
      <PortalNav current="/billing" tenant={tenant} />

      <h1 className={styles.heading}>Billing</h1>
      <p className={styles.subheading}>
        Manage your subscription, monitor usage, and review invoices for{" "}
        <strong>{tenant.name}</strong>.
      </p>

      {subscription.status === "past_due" ? (
        <section className={styles.alertWarn} data-testid="past-due-banner">
          <strong>Payment past due.</strong> Update your payment method to
          avoid losing access. The system will retry the most recent failed
          charge before the next billing cycle.
        </section>
      ) : null}
      {subscription.status === "canceled" && tenantRow?.canceledAt ? (
        <section className={styles.alertDanger} data-testid="canceled-banner">
          <strong>Subscription canceled.</strong> Service ended on{" "}
          {tenantRow.canceledAt.toISOString().slice(0, 10)}. Data is retained
          for 30 days — re-subscribe anytime from the pricing page to restore
          your account.
        </section>
      ) : null}

      <section className={styles.billingGrid}>
        <article className={styles.billingCard} data-testid="current-plan">
          <header className={styles.cardHeader}>
            <h2>Current plan</h2>
            <span
              className={`${styles.statusPill} ${styles[`statusPill_${subscription.status}`] ?? ""}`}
              data-status={subscription.status}
            >
              {subscription.status}
            </span>
          </header>
          <div className={styles.tierName}>{tierName}</div>
          <dl className={styles.kv}>
            <dt>Tier</dt>
            <dd data-testid="current-tier">{subscription.tier ?? "—"}</dd>
            <dt>Next invoice</dt>
            <dd data-testid="next-invoice">
              {nextInvoiceDateDisplay ?? "—"}
              {subscription.nextInvoiceAmount
                ? ` · ${subscription.nextInvoiceAmount}`
                : ""}
            </dd>
            <dt>Customer portal</dt>
            <dd>
              {subscription.hasStripeCustomer
                ? "Configured"
                : "Not configured (subscribe to a plan first)"}
            </dd>
          </dl>
        </article>

        <article className={styles.billingCard} data-testid="usage-card">
          <header className={styles.cardHeader}>
            <h2>Monthly usage</h2>
            <span className={styles.muted}>
              resets {usage.resetsAt}
            </span>
          </header>
          <div className={styles.usageNumber}>
            <strong data-testid="usage-used">{usage.used.toLocaleString("en-US")}</strong>
            <span className={styles.muted}>
              {" "}of {usage.quota.toLocaleString("en-US")} audits
            </span>
          </div>
          <div
            className={styles.progress}
            role="progressbar"
            aria-valuenow={usage.used}
            aria-valuemin={0}
            aria-valuemax={usage.quota}
            data-testid="usage-progress"
          >
            <div
              className={styles.progressBar}
              data-state={
                usage.percent >= 100
                  ? "over"
                  : usage.percent >= 80
                    ? "near"
                    : "ok"
              }
              style={{ width: `${Math.min(100, usage.percent)}%` }}
            />
          </div>
          <p className={styles.muted}>
            {usage.percent.toFixed(1)}% of your monthly quota. Period
            started {usage.periodStart}.
          </p>
        </article>

        <article className={styles.billingCard} data-testid="actions-card">
          <header className={styles.cardHeader}>
            <h2>Manage subscription</h2>
          </header>
          <BillingActions
            tenantId={tenant.id}
            currentTier={subscription.tier}
            currentStatus={subscription.status}
            hasStripeCustomer={subscription.hasStripeCustomer}
            demo={isDemoMode()}
            tiers={pricing.tiers.map((t) => ({
              id: t.id,
              name: t.name,
              auditCap: t.auditCap,
              priceCAD: t.priceCAD,
              priceUSD: t.priceUSD,
              currencyPrimary: pricing.currency.primary,
            }))}
          />
        </article>
      </section>

      <section className={styles.invoiceSection} data-testid="invoice-section">
        <header className={styles.cardHeader}>
          <h2>Invoice history</h2>
          <span className={styles.muted}>last 12 months</span>
        </header>
        {invoices.length === 0 ? (
          <p className={styles.muted}>
            No invoices yet. Once your first billing cycle completes, the
            receipt will appear here.
          </p>
        ) : (
          <table className={styles.invoiceTable}>
            <thead>
              <tr>
                <th>Date</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Receipt</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id} data-testid="invoice-row">
                  <td>{inv.date}</td>
                  <td>{inv.amount}</td>
                  <td>
                    <span
                      className={`${styles.statusPill} ${styles[`statusPill_${inv.status}`] ?? ""}`}
                    >
                      {inv.status}
                    </span>
                  </td>
                  <td>
                    {inv.hostedUrl ? (
                      <a
                        href={inv.hostedUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.link}
                      >
                        View ↗
                      </a>
                    ) : inv.pdfUrl ? (
                      <a
                        href={inv.pdfUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.link}
                      >
                        PDF ↗
                      </a>
                    ) : (
                      <span className={styles.muted}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
