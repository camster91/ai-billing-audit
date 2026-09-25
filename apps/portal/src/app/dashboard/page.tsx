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

import type { Metadata } from "next";
import { redirect } from "next/navigation";
import Link from "next/link";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { PortalNav } from "../portal-nav";
import { EmptyStateCTA, onboardingWizardHref } from "@/components/EmptyStateCTA";
import { FtueWalkthrough } from "@/components/FtueWalkthrough";
import { FPARTile } from "@/components/fpar-tile";
import { CalibrationCard } from "@/components/calibration-card";
import { computeFPAR } from "@/lib/fpar";
import { computeCalibration } from "@/lib/calibration";
import styles from "../shell.module.css";

export const metadata: Metadata = {
  // Authenticated portal page — must stay out of search engine indexes.
  // Overrides the root layout's `robots: { index: true, follow: true }`.
  robots: { index: false, follow: false },
};

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
  // Zero-data empty-state. The dashboard hides the "Your clinics"
  // summary and shows an onboarding CTA when the tenant has no
  // encounters AND no findings (i.e. truly fresh signup). Without
  // this the brand-new user lands on a populated-looking page with
  // no obvious next step.
  let encounterCount = 0;
  let findingCount = 0;
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
    // Single round-trip — Prisma can run two count()s in parallel.
    const [eCount, fCount] = await Promise.all([
      prisma.encounter.count({ where: { tenantId: tenant.id } }),
      prisma.finding.count({ where: { encounter: { tenantId: tenant.id } } }),
    ]);
    encounterCount = eCount;
    findingCount = fCount;
  }

  // FPAR (first-pass approval rate) — per docs/APPROVAL_RATE_KPI.md.
  // Computed server-side from the same Prisma queries the audit log
  // uses, so the portal's home dashboard always reflects the live
  // biller decision count without round-tripping the FastAPI.
  // Returns `rate: null` (and renders "Not enough data yet") when
  // the tenant has < 10 acted-on audits.
  const fpar = tenant
    ? await computeFPAR(tenant.id)
    : { auditsInWindow: 0, acceptedUnchangedCount: 0, rate: null, isStale: false };

  // Per-clinic calibration (docs/SPECIALTY_TUNING.md §2 precondition
  // for triggering a re-tune; FastAPI counterpart in
  // src/ai_billing_audit/feedback.py:280). Reads from the
  // CalibrationSignal Prisma table (scaffold migration
  // 20260627110000_add_calibration_scaffold). Returns empty signals
  // when the tenant has no signals yet — the card handles that
  // gracefully.
  const calibration = tenant
    ? await computeCalibration(tenant.id)
    : { tenantId: "", signals: [], bucketCounts: { calibrated: 0, reviewing: 0, overcalled: 0, uncalibrated: 0 } };
  const isFreshTenant =
    tenant !== null && encounterCount === 0 && findingCount === 0;

  return (
    <main id="main" className={styles.shell}>
      {tenant ? <PortalNav current="/dashboard" tenant={tenant} /> : null}
      {/* Product tour for returning / onboarded clinics — not for zero-data fresh signups. */}
      {tenant && !isFreshTenant ? <FtueWalkthrough enabled /> : null}

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

          <FPARTile tenantId={tenant.id} fpar={fpar} drillInHref="/findings" />

          <CalibrationCard calibration={calibration} />

          {onboardingCompletedAt &&
          firstEncounterUploadMode === "uploaded" &&
          firstEncounterFileName ? (
            <section className={styles.card}>
              <h2 style={{ margin: "0 0 8px", fontSize: 16 }}>
                First encounter securely staged
              </h2>
              <p className={styles.muted} style={{ margin: 0 }}>
                <strong>{firstEncounterFileName}</strong> is encrypted and
                ready for processing. An audit has not been queued yet.
              </p>
            </section>
          ) : null}

          {isFreshTenant ? (
            <EmptyStateCTA
              testId="dashboard-fresh-tenant-cta"
              variant="block"
              title="No encounters yet"
              description="Securely stage your first encounter. Audit processing begins after your clinic's engine integration is enabled."
              primaryAction={{
                label: "Upload your first encounter",
                href: onboardingWizardHref(),
                testId: "dashboard-upload-first-encounter",
              }}
              secondaryAction={{
                label: "How it works",
                href: "/how-it-works",
                testId: "dashboard-how-it-works",
              }}
            />
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
