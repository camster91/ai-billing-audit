// /portal/billing — manage-subscription entry point.
//
// Reads ?tenantId=<id> from the URL (set by the onboarding page's
// "Manage billing" link). Calls /api/billing/portal server-side to get
// a Stripe Customer Portal URL, then redirects.
//
// In demo mode, the API returns a local stub URL; we render a small
// "demo mode" page instead of redirecting (to avoid an infinite loop).
//
// Server component — no client JS required for the happy path.

import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { isDemoMode } from "@/lib/stripe";
import styles from "../onboarding/onboarding.module.css";

export const metadata: Metadata = {
  // Authenticated portal page — must stay out of search engine indexes.
  // Overrides the root layout's `robots: { index: true, follow: true }`.
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface PageProps {
  searchParams: Promise<{ tenantId?: string }>;
}

export default async function PortalBillingPage({ searchParams }: PageProps) {
  const { tenantId } = await searchParams;

  if (!tenantId) {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <h1>Manage billing</h1>
          <p>This page expects a <code>?tenantId=...</code> query parameter.</p>
          <p>
            <a href="/pricing" className={styles.link}>Back to pricing →</a>
          </p>
        </div>
      </div>
    );
  }

  const tenant = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: { id: true, name: true, stripeCustomerId: true },
  });

  if (!tenant) {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <h1>Tenant not found</h1>
          <p>No tenant with id <code>{tenantId}</code>.</p>
        </div>
      </div>
    );
  }

  if (!tenant.stripeCustomerId) {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <div className={styles.badge}>No Stripe customer</div>
          <h1>{tenant.name}</h1>
          <p>
            This tenant has no Stripe customer yet — the first checkout
            hasn't completed. Once a subscription is active, this page
            will route you to the Stripe Customer Portal for plan changes.
          </p>
          <p>
            <a className={styles.link} href="/pricing">View pricing →</a>
          </p>
        </div>
      </div>
    );
  }

  // We can't redirect from a server component by calling our own POST
  // endpoint cleanly (would be a self-loop). The /api/billing/portal
  // route is the canonical entry; this page is just a convenience
  // landing for the onboarding CTA. In demo mode, show a card.
  if (isDemoMode()) {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <div className={styles.badge}>Demo mode</div>
          <h1>Manage billing for {tenant.name}</h1>
          <p>
            Stripe is in demo mode — the Customer Portal isn't actually
            available. In production this page would redirect to
            <code>billing.stripe.com</code> for the customer's self-serve
            portal.
          </p>
          <p>
            <a className={styles.link} href="/portal/onboarding?demo=1">Back to onboarding →</a>
          </p>
        </div>
      </div>
    );
  }

  // Production: redirect to a tiny server route that POSTs to the API
  // and 302s to the Stripe URL. Implemented as a Next.js Route Handler
  // for clarity. See /api/billing/portal-redirect.
  redirect(`/api/billing/portal-redirect?tenantId=${encodeURIComponent(tenantId)}`);
}
