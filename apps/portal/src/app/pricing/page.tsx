// /pricing — Zorva 3-tier CAD/USD pricing page.
//
// Server component. Renders the same design as t_f00717ff's pricing.html
// but fetches tier data from getPricingConfig() (env-driven) instead of
// a runtime JSON fetch. The 3 CTAs POST to /api/billing/checkout with
// the tier + currency; the response.url is the redirect target.
//
// Compliance block uses pricing.compliance.* fields from the config so
// the Zorva §11 message can be edited in env without a redeploy — but
// falls back to a hard-coded string if the env is missing so the page
// is never broken.

import { getPricingConfig } from "@/lib/pricing";
import type { Tier, CurrencyCode, PricingConfig } from "@/lib/pricing";
import { CheckoutButton } from "./CheckoutButton";
import styles from "./pricing.module.css";

export const dynamic = "force-static";
export const revalidate = 60;

function formatCurrency(n: number, code: CurrencyCode): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
      maximumFractionDigits: 0,
    }).format(n);
  } catch {
    return (code === "USD" ? "$" : "CA$") + n.toLocaleString("en-US");
  }
}

function isRecommended(tier: Tier): boolean {
  // Heuristic: the mid tier carries the "Most clinics" badge. Easy to
  // flip later by adding a `recommended: boolean` field to the config.
  return tier.id === "mid";
}

export default function PricingPage() {
  const config: PricingConfig = getPricingConfig();
  const { tiers, currency, compliance } = config;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1>Pricing</h1>
        <p>
          Flat monthly fees, volume-bracketed. Built for Canadian and US
          clinics that need a billing-audit engine without per-claim
          revenue share.
        </p>
      </header>

      <main className={styles.main}>
        <div className={styles.tiers}>
          {tiers.map((tier) => (
            <article
              key={tier.id}
              className={`${styles.tier} ${isRecommended(tier) ? styles.recommended : ""}`}
            >
              <h2>{tier.name}</h2>
              <div className={styles.cap}>
                Up to {tier.auditCap.toLocaleString("en-US")} audits / month
              </div>
              <div className={styles.priceBlock}>
                <div className={`${styles.priceLine} ${styles.priceLinePrimary}`}>
                  <span className={styles.amount}>
                    {formatCurrency(tier.priceCAD, currency.primary)}
                  </span>
                  <span className={styles.label}>{currency.primary} / month</span>
                </div>
                <div className={`${styles.priceLine} ${styles.priceLineSecondary}`}>
                  <span className={styles.amount}>
                    {formatCurrency(tier.priceUSD, currency.secondary)}
                  </span>
                  <span className={styles.label}>{currency.secondary} / month</span>
                </div>
              </div>
              <ul className={styles.features}>
                {tier.features.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
              <div className={styles.ctaRow}>
                <CheckoutButton
                  tierId={tier.id}
                  currency="CAD"
                  label={`Start ${currency.primary} plan`}
                  variant={isRecommended(tier) ? "primary" : "secondary"}
                />
                <CheckoutButton
                  tierId={tier.id}
                  currency="USD"
                  label={`Start ${currency.secondary} plan`}
                  variant="ghost"
                />
              </div>
            </article>
          ))}
        </div>

        <section className={styles.compliance}>
          <h3>{compliance.framework.replace(/_/g, " / ")} compliance</h3>
          <p>
            This pricing is built on a{" "}
            <strong>flat-fee, volume-bracketed</strong> model
            {compliance.specReference ? ` (per ${compliance.specReference})` : ""}.{" "}
            We explicitly do not charge a percentage of collected revenue, a
            percentage of billings, or any fee that scales with the dollar
            value of claims processed.
          </p>
          <p className={styles.ref}>
            Reference: {compliance.specReference} — flat-volume-bracketed
            pricing; percentage-of-revenue and percentage-of-collected models
            are rejected as not AKS / Stark safe-harbor compliant.
          </p>
          <ul>
            <li>Flat monthly fee per tier — predictable, audit-friendly.</li>
            <li>Volume cap tied to encounter audits, not to revenue.</li>
            <li>No commission, no per-dollar markup, no success fee.</li>
          </ul>
        </section>
      </main>

      <footer className={styles.footer}>
        Prices in {currency.primary} are the primary billing currency for
        Canadian clinics; {currency.secondary} shown for US clinics. Static
        {currency.secondary} values — no live FX conversion.
      </footer>
    </div>
  );
}
