// /findings — flat list of every AI finding in the active tenant.
//
// Server Component. Reads findings through the encounter's tenantId
// filter (so a user in tenant A never sees a finding from a row
// scoped to tenant B). The split-screen review at /encounters/[id]
// is the primary surface — this page is the queue view that powers
// "what still needs my attention?"
//
// Status filter via `?status=pending|accepted|dismissed` query
// param. Default is `pending` so the page is the work queue on
// first load.

import { redirect } from "next/navigation";
import Link from "next/link";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { FINDING_CATEGORY_LABEL, FINDING_STATUSES } from "@/lib/encounter-types";
import { PortalNav } from "../portal-nav";
import styles from "../shell.module.css";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface PageProps {
  searchParams: Promise<{ status?: string }>;
}

const CATEGORY_LABEL = FINDING_CATEGORY_LABEL as Record<string, string>;

function formatImpact(cents: number): string {
  const sign = cents < 0 ? "-" : "+";
  const abs = Math.abs(cents);
  return `${sign}$${(abs / 100).toFixed(2)}`;
}

function isValidStatus(value: string | undefined): value is
  | "pending"
  | "accepted"
  | "dismissed" {
  return FINDING_STATUSES.includes(value as "pending" | "accepted" | "dismissed");
}

export default async function FindingsPage({ searchParams }: PageProps) {
  const session = await auth();
  if (!session?.user?.id) {
    redirect("/login?callbackUrl=/findings");
  }

  const { status: statusParam } = await searchParams;
  const status = isValidStatus(statusParam) ? statusParam : "pending";
  const tenant = await getActiveTenant();

  const findings = tenant
    ? await prisma.finding.findMany({
        where: {
          status,
          encounter: { tenantId: tenant.id },
        },
        orderBy: { createdAt: "desc" },
        take: 100,
        select: {
          id: true,
          encounterId: true,
          category: true,
          billingRuleReference: true,
          currentCode: true,
          suggestedCode: true,
          estFinancialImpactCents: true,
          status: true,
        },
      })
    : [];

  return (
    <main className={styles.shell}>
      {tenant ? <PortalNav current="/findings" tenant={tenant} /> : null}

      <h1 className={styles.heading}>Findings</h1>
      <p className={styles.subheading}>
        {tenant
          ? `Showing ${findings.length} ${status} finding${findings.length === 1 ? "" : "s"} for ${tenant.name}.`
          : "Tenant scope required to view findings."}
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {FINDING_STATUSES.map((s) => {
          const active = s === status;
          const cls = active
            ? `${styles.navLink} ${styles.navLinkActive}`
            : styles.navLink;
          return (
            <Link key={s} href={`/findings?status=${s}`} className={cls}>
              {s}
            </Link>
          );
        })}
      </div>

      {!tenant ? (
        <section className={styles.empty}>
          <h2>No clinic connected</h2>
          <p>You aren&rsquo;t a member of a clinic yet.</p>
        </section>
      ) : findings.length === 0 ? (
        <section className={styles.empty}>
          <h2>Nothing in this status</h2>
          <p>
            No {status} findings for {tenant.name}. Switch the filter above
            to see the rest.
          </p>
        </section>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Category</th>
              <th>Code change</th>
              <th>Rule reference</th>
              <th>Impact</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {findings.map((f) => (
              <tr key={f.id}>
                <td>{CATEGORY_LABEL[f.category] ?? f.category}</td>
                <td>
                  <code style={{ fontSize: 12 }}>
                    {f.currentCode ?? "—"}{" → "}{f.suggestedCode ?? "—"}
                  </code>
                </td>
                <td>{f.billingRuleReference}</td>
                <td>
                  <span
                    style={{
                      color: f.estFinancialImpactCents >= 0 ? "#2dd4bf" : "#f87171",
                      fontFamily: "ui-monospace, monospace",
                      fontSize: 13,
                    }}
                  >
                    {formatImpact(f.estFinancialImpactCents)}
                  </span>
                </td>
                <td>
                  <Link href={`/encounters/${f.encounterId}`}>Open encounter →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
