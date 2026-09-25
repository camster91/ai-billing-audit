// /team — team management page.
//
// Renders the tenant's Membership list, an invite form (owner
// only), and per-row actions (change role, disable) gated by
// the viewer's own role.
//
// Composition:
//   - page.tsx (this file): server component, fetches data.
//   - team-client.tsx: client component, handles the invite
//     form, role-change dropdown, and disable button.

import { redirect } from "next/navigation";
import type { Metadata } from "next";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { PortalNav } from "../portal-nav";
import { EmptyStateCTA } from "@/components/EmptyStateCTA";
import styles from "../shell.module.css";
import { TeamClient } from "./team-client";

export const metadata: Metadata = {
  title: "Team — Zorva",
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function TeamPage() {
  const session = await auth();
  if (!session?.user?.id) {
    redirect("/login?callbackUrl=/team");
  }

  const tenant = await getActiveTenant();

  if (!tenant) {
    return (
      <main id="main" className={styles.shell}>
        <h1 className={styles.heading}>Team</h1>
        <EmptyStateCTA
          testId="team-no-clinic-cta"
          title="No clinic connected"
          description="You aren't a member of a clinic yet. Ask an owner to invite you, or start a plan."
          primaryAction={{ label: "View pricing", href: "/pricing" }}
          secondaryAction={{ label: "Contact support", href: "/contact" }}
        />
      </main>
    );
  }

  // Read the viewer's own role for the active tenant. We need
  // it to decide whether to render the invite form / per-row
  // actions. The team-client component re-checks via /api/team
  // but we also need it server-side for the first paint.
  const viewerMembership = await prisma.membership.findFirst({
    where: { userId: session.user.id, tenantId: tenant.id },
    select: { role: true, status: true },
  });

  // The page itself never lists inactive members by default;
  // the team-client can opt in via a "show disabled" toggle
  // (currently not exposed in the UI; the GET /api/team
  // endpoint accepts ?status=inactive when needed).
  const memberships = await prisma.membership.findMany({
    where: { tenantId: tenant.id },
    orderBy: [{ status: "asc" }, { createdAt: "asc" }],
    include: {
      user: { select: { id: true, email: true, name: true } },
    },
  });

  const canManage = viewerMembership
    ? viewerMembership.status === "active" &&
      (viewerMembership.role === "owner" || viewerMembership.role === "admin")
    : false;

  return (
    <main id="main" className={styles.shell}>
      <PortalNav current="/team" tenant={tenant} />

      <h1 className={styles.heading}>Team</h1>
      <p className={styles.subheading}>
        {memberships.length} member{memberships.length === 1 ? "" : "s"} of{" "}
        {tenant.name}.
        {!canManage
          ? " Your role is read-only on this page."
          : " Invite teammates and manage their roles below."}
      </p>

      <TeamClient
        viewerUserId={session.user.id}
        viewerRole={viewerMembership?.role ?? "viewer"}
        viewerStatus={(viewerMembership?.status as "active" | "pending" | "inactive" | undefined) ?? "inactive"}
        tenantName={tenant.name}
        initialMemberships={memberships.map((m) => ({
          id: m.id,
          email: m.email,
          role: m.role,
          status: m.status as "active" | "pending" | "inactive",
          invitedAt: m.invitedAt.toISOString(),
          activatedAt: m.activatedAt ? m.activatedAt.toISOString() : null,
          createdAt: m.createdAt.toISOString(),
          user: m.user
            ? { id: m.user.id, email: m.user.email, name: m.user.name }
            : null,
        }))}
      />
    </main>
  );
}
