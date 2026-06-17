// /team — membership list route shell.
//
// Reads the active tenant's Membership rows (user + role). Per
// spec, the team-invitation/role-management UI is out of scope —
// this is a read-only list of who already has access.
//
// The session callback (src/auth.ts) already returns
// `session.user.tenants` with each entry's role. For the active
// tenant specifically, we re-query to get the full user list
// (everyone who has access, not just the current user).

import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { PortalNav } from "../portal-nav";
import styles from "../shell.module.css";

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
      <main className={styles.shell}>
        <h1 className={styles.heading}>Team</h1>
        <section className={styles.empty}>
          <h2>No clinic connected</h2>
          <p>You aren&rsquo;t a member of a clinic yet.</p>
        </section>
      </main>
    );
  }

  const memberships = await prisma.membership.findMany({
    where: { tenantId: tenant.id },
    orderBy: { createdAt: "asc" },
    include: {
      user: { select: { id: true, email: true, name: true } },
    },
  });

  return (
    <main className={styles.shell}>
      <PortalNav current="/team" tenant={tenant} />

      <h1 className={styles.heading}>Team</h1>
      <p className={styles.subheading}>
        {memberships.length} member{memberships.length === 1 ? "" : "s"} of {tenant.name}.
        Invitation/role-management UI is out of scope for this milestone.
      </p>

      {memberships.length === 0 ? (
        <section className={styles.empty}>
          <h2>No members yet</h2>
          <p>This clinic has no users yet. The invite flow ships next milestone.</p>
        </section>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Joined</th>
            </tr>
          </thead>
          <tbody>
            {memberships.map((m) => (
              <tr key={m.id}>
                <td>{m.user.name ?? "—"}</td>
                <td>{m.user.email}</td>
                <td>{m.role}</td>
                <td>{m.createdAt.toISOString().slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
