// /pricing — Zorva 3-tier CAD/USD pricing page with tier picker and
// "60-day no-cost pilot. After that, $499/mo. Cancel any time." CTAs.
//
// Server component. Tier data is sourced from getPricingConfig() (env-driven)
// so prices, claim caps, and Stripe price IDs can change without a code
// change. The Enterprise tier ("3,000+ claims? Talk to sales") is rendered
// separately below the picker.
//
// Three tiers, $499 / $1,499 / $2,999 CAD; US clinics see static USD
// equivalents (no live FX). The middle tier carries the "Most popular"
// highlight to match the task spec. All CTAs route to /contact for the
// no-cost-pilot sign-up; Stripe checkout handoff is wired in CheckoutButton.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./pricing.module.css";
import { getPricingConfig } from "@/lib/pricing";
import type { Tier } from "@/lib/pricing";

export const metadata: Metadata = {
  title: "Pricing — flat monthly fees, no revenue share",
  description:
    "Zorva pricing: three flat monthly tiers bracketed by claim volume for Alberta clinics. No per-claim fees, no revenue share — every recovered dollar stays with you.",
};

function formatCurrency(n: number, code: "CAD" | "USD"): string {
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
  // Middle tier carries the "Most popular" highlight per the marketing
  // spec — most clinics land here. Easy to flip by promoting a different
  // tier.id in future.
  return tier.id === "mid";
}

export default function PricingPage() {
  const config = getPricingConfig();
  const { tiers, currency } = config;
  const enterpriseTier = tiers.find((t) => t.id === "large");

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>Pricing</span>
        <h1>Flat monthly fees. No percentage of revenue.</h1>
        <p className={styles.lede}>
          Three tiers bracketed by claim volume. Pick the one that matches
          your monthly throughput — no per-claim fees, no revenue share, no
          surprises when you scale.
        </p>
        <p className={styles.currencyNote}>
          Alberta clinics billed in CAD. US clinics billed in USD.{" "}
          <span className={styles.muted}>
            USD values are static — no live FX conversion.
          </span>
        </p>
      </header>

      <main className={styles.main}>
        <div className={styles.tiers} role="list" aria-label="Pricing tiers">
          {tiers.map((tier) => {
            const recommended = isRecommended(tier);
            const claimVolumeLabel = claimVolumeFor(tier.id);
            return (
              <article
                key={tier.id}
                role="listitem"
                className={`${styles.tier} ${recommended ? styles.recommended : ""}`}
                aria-label={`${tier.name} tier, ${formatCurrency(tier.priceCAD, currency.primary)} per month`}
              >
                {recommended && (
                  <div className={styles.popularBadge} aria-hidden="true">
                    Most clinics
                  </div>
                )}
                <h2>{tier.name}</h2>
                <div className={styles.cap}>{claimVolumeLabel}</div>

                <div className={styles.priceBlock}>
                  <div className={styles.pricePrimary}>
                    <span className={styles.amount}>
                      {formatCurrency(tier.priceCAD, "CAD")}
                    </span>
                    <span className={styles.per}>/ month</span>
                    <span className={styles.code}>CAD</span>
                  </div>
                  <div className={styles.priceSecondary}>
                    <span className={styles.amount}>
                      {formatCurrency(tier.priceUSD, "USD")}
                    </span>
                    <span className={styles.per}>/ month USD</span>
                  </div>
                </div>

                <ul className={styles.features}>
                  {FEATURES_BY_TIER[tier.id].map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>

                <Link
                  href="/contact"
                  className={`${styles.cta} ${recommended ? styles.ctaPrimary : styles.ctaSecondary}`}
                  aria-label={`Start the ${tier.name} tier — 60-day no-cost pilot. After that, $499/mo. Cancel any time.`}
                >
                  60-day no-cost pilot. After that, $499/mo. Cancel any time.
                </Link>
              </article>
            );
          })}
        </div>

        <section className={styles.enterprise} aria-label="Enterprise tier">
          <div>
            <h3>3,000+ claims a month?</h3>
            <p>
              We work with multi-clinic groups and large billing teams on
              custom volume, custom data residency, and dedicated support.
              Let&apos;s scope it on a 20-minute call.
            </p>
            {enterpriseTier && (
              <p className={styles.enterprisePrice}>
                Enterprise pricing starts at{" "}
                <strong>{formatCurrency(enterpriseTier.priceCAD, "CAD")}</strong>{" "}
                / month with a custom audit cap.
              </p>
            )}
          </div>
          <Link href="/contact" className={styles.enterpriseCta}>
            Talk to sales →
          </Link>
        </section>

        <section className={styles.assurance}>
          <h3>What you always get, on every tier</h3>
          <ul>
            <li>
              <strong>Deterministic audit runs.</strong> Seed pinned,
              temperature 0. Same input, same output, every time — required
              for any real appeal defence.
            </li>
            <li>
              <strong>Region-pinned data.</strong> Canadian data centre,
              region confirmed in the BAA. No cross-region replication, no
              analytics egress, no sale of customer data.
            </li>
            <li>
              <strong>Hash-chain audit trail.</strong> Every finding is
              hash-chained to the prior one. HIA, PHIPA, and HIPAA-aligned
              by default.
            </li>
            <li>
              <strong>No percentage-of-revenue pricing.</strong> Flat fee
              only — AKS / Stark safe-harbor clean. Compliance details on
              the security page.
            </li>
          </ul>
        </section>
      </main>

      <footer className={styles.footer}>
        Questions about fit?{" "}
        <Link href="/contact" className={styles.footerLink}>
          Talk to sales
        </Link>{" "}
        — no demo gauntlet, no procurement form.
      </footer>
    </div>
  );
}

/**
 * Map tier id to the human-readable claim-volume cap displayed on the
 * card. Numbers match the marketing spec:
 *   - small: under 1,000 claims / month
 *   - mid:   1,000 - 3,000 claims / month
 *   - large: 3,000+ claims / month (rendered as Enterprise block)
 */
function claimVolumeFor(tierId: Tier["id"]): string {
  switch (tierId) {
    case "small":
      return "Under 1,000 claims / month";
    case "mid":
      return "1,000 - 3,000 claims / month";
    case "large":
      return "3,000+ claims / month";
  }
}

/**
 * Marketing-spec feature lists. Kept local to the page (not the lib)
 * because the spec calls out specific copy — audit findings, appeal
 * letters, revenue opportunity detection, monthly report, support tier —
 * and we don't want env config to drift the public copy.
 */
const FEATURES_BY_TIER: Record<Tier["id"], string[]> = {
  small: [
    "Pre-bill audit findings on every claim",
    "Appeal letter drafting for flagged encounters",
    "Revenue opportunity detection (under-coded, missed procedures)",
    "Monthly performance report (PDF + CSV)",
    "Email support, next-business-day response",
  ],
  mid: [
    "Pre-bill audit findings on every claim",
    "Appeal letter drafting for flagged encounters",
    "Revenue opportunity detection (under-coded, missed procedures, missed modifiers)",
    "Monthly performance report with revenue-leak breakdown",
    "Priority email support, same-day response",
    "Up to 5 biller seats",
  ],
  large: [
    "Pre-bill audit findings on every claim",
    "Appeal letter drafting for flagged encounters",
    "Revenue opportunity detection (under-coded, missed procedures, missed modifiers, premium-eligible services)",
    "Monthly performance report with executive summary",
    "Priority support with same-day response SLA",
    "Unlimited biller seats",
    "Quarterly billing-rules tuning session",
  ],
};
