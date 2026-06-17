// /settings — tenant settings route shell.
//
// Per the milestone spec, settings is a route shell only — we read
// the active tenant and expose the fields the dashboard surfaces
// (name, tier, subscription status, quota) plus the Stripe customer
// id (the spec only requires "store the IDs", no webhook handlers).
// Edit/update flows are out of scope for this milestone.

import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { PortalNav } from "../portal-nav";
import styles from "../shell.module.css";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function SettingsPage() {
  const session = await auth();
  if (!session?.user?.id) {
    redirect("/login?callbackUrl=/settings");
  }

  const tenant = await getActiveTenant();

  if (!tenant) {
    return (
      <main className={styles.shell}>
        <h1 className={styles.heading}>Settings</h1>
        <section className={styles.empty}>
          <h2>No clinic connected</h2>
          <p>You aren&rsquo;t a member of a clinic yet.</p>
        </section>
      </main>
    );
  }

  // Pull the Stripe linkage from the row — spec says "store the
  // IDs", so we surface what we have. Read-only at this milestone.
  const row = await prisma.tenant.findUnique({
    where: { id: tenant.id },
    select: {
      name: true,
      slug: true,
      tier: true,
      subscriptionStatus: true,
      stripeCustomerId: true,
      stripeSubscriptionId: true,
      auditQuotaUsed: true,
      auditQuotaLimit: true,
    },
  });

  if (!row) {
    return (
      <main className={styles.shell}>
        <h1 className={styles.heading}>Settings</h1>
        <section className={styles.empty}>
          <h2>Tenant not found</h2>
          <p>The active tenant no longer exists.</p>
        </section>
      </main>
    );
  }

  return (
    <main className={styles.shell}>
      <PortalNav current="/settings" tenant={tenant} />

      <h1 className={styles.heading}>Settings</h1>
      <p className={styles.subheading}>
        Clinic configuration. Edit flows are out of scope for this milestone.
      </p>

      <section className={styles.card}>
        <h2 style={{ margin: "0 0 12px", fontSize: 16 }}>Identity</h2>
        <Field label="Clinic name" value={row.name} />
        <Field label="Slug" value={row.slug} mono />
        <Field label="Tier" value={row.tier} />
      </section>

      <section className={styles.card}>
        <h2 style={{ margin: "0 0 12px", fontSize: 16 }}>Subscription</h2>
        <Field label="Status" value={row.subscriptionStatus} />
        <Field
          label="Stripe customer id"
          value={row.stripeCustomerId ?? "—"}
          mono
        />
        <Field
          label="Stripe subscription id"
          value={row.stripeSubscriptionId ?? "—"}
          mono
        />
      </section>

      <section className={styles.card}>
        <h2 style={{ margin: "0 0 12px", fontSize: 16 }}>Audit quota</h2>
        <Field label="Used" value={String(row.auditQuotaUsed)} />
        <Field label="Limit" value={String(row.auditQuotaLimit)} />
      </section>
    </main>
  );
}

function Field({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "8px 0",
        borderBottom: "1px solid #28324f",
      }}
    >
      <span className={styles.muted}>{label}</span>
      <span
        style={{
          fontFamily: mono ? "ui-monospace, monospace" : "inherit",
          fontSize: mono ? 13 : 14,
        }}
      >
        {value}
      </span>
    </div>
  );
}
