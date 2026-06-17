// /billing — spec route shell.
//
// The Stripe Customer Portal redirect logic was built at
// /portal/billing in the first iteration (which expects a
// `?tenantId=` query param). /billing is the user-facing entry
// in the spec — it resolves the active tenant from the session
// and forwards to /portal/billing?tenantId=<id>.
//
// If the user has no tenant, we render an empty state.
//
// Auth + tenant scope are inherited from /portal/billing itself
// (it lives under PUBLIC_PREFIXES because the post-checkout flow
// needs to land unauthenticated users there). This page is gated
// by the proxy — the only authenticated users reach it.

import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { PortalNav } from "../portal-nav";
import styles from "../shell.module.css";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

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
          <p>You aren&rsquo;t a member of a clinic yet.</p>
        </section>
      </main>
    );
  }

  // Forward to the existing Stripe-Customer-Portal wrapper with the
  // active tenant id attached.
  redirect(`/portal/billing?tenantId=${encodeURIComponent(tenant.id)}`);
}
