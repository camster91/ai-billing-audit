// /encounters — list page (tenant-scoped).
//
// Server Component. Pulls the active tenant from the session via
// getActiveTenant() and lists that tenant's encounters newest-first.
// Each row links to /encounters/[id] for the split-screen review.
//
// Auth + tenant scope: proxy.ts already redirects unauthenticated
// users to /login, and getActiveTenant() returns null for a user
// with no memberships — we render an empty state in that case
// (matches the dashboard).

import { redirect } from "next/navigation";
import Link from "next/link";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { PortalNav } from "../portal-nav";
import styles from "../shell.module.css";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const STATUS_PILL: Record<string, string> = {
  pending: "statusPillPending",
  auditing: "statusPillAuditing",
  awaiting_review: "statusPillPending",
  completed: "statusPillCompleted",
};

function formatDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export default async function EncountersListPage() {
  const session = await auth();
  if (!session?.user?.id) {
    redirect("/login?callbackUrl=/encounters");
  }

  const tenant = await getActiveTenant();

  const encounters = tenant
    ? await prisma.encounter.findMany({
        where: { tenantId: tenant.id },
        orderBy: { dateOfService: "desc" },
        take: 50,
        select: {
          id: true,
          patientHash: true,
          dateOfService: true,
          specialty: true,
          status: true,
        },
      })
    : [];

  return (
    <main className={styles.shell}>
      {tenant ? <PortalNav current="/encounters" tenant={tenant} /> : null}

      <h1 className={styles.heading}>Encounters</h1>
      <p className={styles.subheading}>
        {tenant
          ? `Most recent ${encounters.length} encounter${encounters.length === 1 ? "" : "s"} for ${tenant.name}.`
          : "Tenant scope required to view encounters."}
      </p>

      {!tenant ? (
        <section className={styles.empty}>
          <h2>No clinic connected</h2>
          <p>You aren&rsquo;t a member of a clinic yet.</p>
        </section>
      ) : encounters.length === 0 ? (
        <section className={styles.empty}>
          <h2>No encounters yet</h2>
          <p>
            Encounters submitted for billing review will appear here.
            This is a route shell in the v1 milestone — the submit
            pipeline lives in the engine service.
          </p>
        </section>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Date of service</th>
              <th>Specialty</th>
              <th>Patient (hashed)</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {encounters.map((e) => {
              const pillKey = STATUS_PILL[e.status] ?? "statusPill";
              return (
                <tr key={e.id}>
                  <td>{formatDate(e.dateOfService)}</td>
                  <td>{e.specialty}</td>
                  <td>
                    <code style={{ fontSize: 12 }}>{e.patientHash.slice(0, 12)}…</code>
                  </td>
                  <td>
                    <span className={`${styles.statusPill} ${styles[pillKey] ?? ""}`}>
                      {e.status}
                    </span>
                  </td>
                  <td>
                    <Link href={`/encounters/${e.id}`}>Review →</Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </main>
  );
}
