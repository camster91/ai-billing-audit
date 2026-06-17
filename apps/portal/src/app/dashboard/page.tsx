// /dashboard — post-login landing.
//
// Renders a tenant overview card: name, tier, subscription status,
// audit quota used/limit, and a list of the user's other tenants
// (the active one is highlighted). Below that, quick links to the
// other portal sections (encounters list, billing, settings, team).
//
// Auth + tenant: src/proxy.ts gates this route; getActiveTenant()
// returns null if the user is signed in but has no membership yet
// (e.g. they just created an account). In that case we render an
// empty state explaining that they need to be invited to a clinic.

import { redirect } from "next/navigation";
import Link from "next/link";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { PortalNav } from "../portal-nav";
import styles from "../shell.module.css";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function DashboardPage() {
  const session = await auth();
  if (!session?.user?.id) {
    redirect("/login?callbackUrl=/dashboard");
  }

  const tenant = await getActiveTenant();
  const allTenants = session.user.tenants ?? [];

  // Quota: the spec says "audit_quota_used / audit_quota_limit" is on
  // the Tenant row. Pull the live counts so the dashboard reflects
  // real data, not the cached value. Also pull the wizard's completed
  // state so a newly-onboarded tenant sees a "run your first audit"
  // CTA.
  let quotaUsed: number | null = null;
  let quotaLimit: number | null = null;
  let onboardingCompletedAt: Date | null = null;
  let firstEncounterUploadMode: string | null = null;
  let firstEncounterFileName: string | null = null;
  if (tenant) {
    const row = await prisma.tenant.findUnique({
      where: { id: tenant.id },
      select: {
        auditQuotaUsed: true,
        auditQuotaLimit: true,
        onboardingCompletedAt: true,
        firstEncounterUploadMode: true,
        firstEncounterFileName: true,
      },
    });
    quotaUsed = row?.auditQuotaUsed ?? null;
    quotaLimit = row?.auditQuotaLimit ?? null;
    onboardingCompletedAt = row?.onboardingCompletedAt ?? null;
    firstEncounterUploadMode = row?.firstEncounterUploadMode ?? null;
    firstEncounterFileName = row?.firstEncounterFileName ?? null;
  }

  return (
    <main className={styles.shell}>
      {tenant ? <PortalNav current="/dashboard" tenant={tenant} /> : null}

      <h1 className={styles.heading}>Dashboard</h1>
      <p className={styles.subheading}>
        Welcome back{session.user.email ? `, ${session.user.email}` : ""}.
      </p>

      {!tenant ? (
        <section className={styles.empty}>
          <h2>No clinic connected</h2>
          <p>
            Your account is verified, but you aren&rsquo;t a member of a
            clinic yet. Ask your administrator to invite you, or
            contact support.
          </p>
        </section>
      ) : (
        <>
          <section className={styles.card}>
            <div className={styles.cardRow}>
              <div>
                <h2 style={{ margin: "0 0 4px", fontSize: 20 }}>{tenant.name}</h2>
                <p className={styles.muted} style={{ margin: 0 }}>
                  Tier: <strong>{tenant.tier}</strong> · Status:{" "}
                  <strong>{tenant.subscriptionStatus}</strong>
                </p>
              </div>
              <span
                className={styles.statusPill}
                aria-label={`Status ${tenant.subscriptionStatus}`}
              >
                {tenant.subscriptionStatus}
              </span>
            </div>
            {quotaUsed !== null && quotaLimit !== null ? (
              <p className={styles.muted} style={{ marginTop: 16, marginBottom: 0 }}>
                Audit quota: {quotaUsed} / {quotaLimit}
                {quotaLimit > 0
                  ? ` (${Math.round((quotaUsed / quotaLimit) * 100)}%)`
                  : ""}
              </p>
            ) : null}
          </section>

          {onboardingCompletedAt &&
          firstEncounterUploadMode === "uploaded" &&
          firstEncounterFileName ? (
            <section className={styles.card}>
              <h2 style={{ margin: "0 0 8px", fontSize: 16 }}>
                First audit queued
              </h2>
              <p className={styles.muted} style={{ margin: 0 }}>
                We&rsquo;re running an audit on{" "}
                <strong>{firstEncounterFileName}</strong>. You&rsquo;ll see
                findings here as soon as the auditor finishes.
              </p>
            </section>
          ) : null}

          <section className={styles.card}>
            <h2 style={{ margin: "0 0 12px", fontSize: 16 }}>Your clinics</h2>
            {allTenants.length === 0 ? (
              <p className={styles.muted}>You don&rsquo;t belong to any clinics yet.</p>
            ) : (
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {allTenants.map((t) => (
                  <li
                    key={t.id}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "8px 0",
                      borderBottom: "1px solid #28324f",
                    }}
                  >
                    <span>
                      {t.name}{" "}
                      <span className={styles.muted}>
                        · {t.role} · {t.tier}
                      </span>
                    </span>
                    {t.id === tenant.id ? (
                      <span className={styles.statusPill}>active</span>
                    ) : (
                      <span className={styles.muted}>(inactive)</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <Link href="/encounters" className={styles.navLink}>
              View encounters →
            </Link>
            <Link href="/findings" className={styles.navLink}>
              Findings queue →
            </Link>
            <Link href="/billing" className={styles.navLink}>
              Manage billing →
            </Link>
            <Link href="/team" className={styles.navLink}>
              Team →
            </Link>
            <Link href="/settings" className={styles.navLink}>
              Settings →
            </Link>
          </section>
        </>
      )}
    </main>
  );
}
