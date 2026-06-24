// Pure helpers for the /billing page (date math + currency
// formatting). No imports from server-only modules so this file is
// safe to use from a Node test script (see tests/billing-page.test.ts).
//
// The DB/Stripe-touching code lives in billing-page.ts which has
// the `server-only` directive; this file is the testable subset.

// ---------------------------------------------------------------------------
// Time-window helpers
// ---------------------------------------------------------------------------

/**
 * Start of the current billing period (the 1st of the current
 * month in UTC). The page treats the calendar month as the quota
 * window — the same shape the eventual usage-quota enforcement
 * task (t_0d6f44ae) will use, so the page is forward-compatible
 * with the production rollover logic.
 *
 * UTC: the dev host and the production Postgres are in different
 * time zones, but every test I've run with non-UTC
 * `new Date(y, m, d)` initializers has lost or gained a day. UTC
 * arithmetic is the safe choice for monthly boundaries.
 */
export function startOfCurrentMonthUtc(now: Date = new Date()): Date {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
}

/**
 * Start of the month 11 months ago, used as the lower bound for
 * the invoice list. The 12-month window is inclusive of the
 * current month, so 11 months are listed in the past.
 */
export function startOfInvoiceWindowUtc(now: Date = new Date()): Date {
  const y = now.getUTCFullYear();
  const m = now.getUTCMonth() - 11;
  return new Date(Date.UTC(y, m, 1));
}

// ---------------------------------------------------------------------------
// Currency formatting
// ---------------------------------------------------------------------------

/** Format integer cents as a "$1,499" / "CA$1,499" string. */
export function formatCents(cents: number, currency: string): string {
  const dollars = cents / 100;
  const code = currency.toUpperCase();
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
      maximumFractionDigits: 0,
    }).format(dollars);
  } catch {
    const sign = code === "USD" ? "$" : code === "CAD" ? "CA$" : `${code} `;
    return `${sign}${dollars.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  }
}
