"use client";

// Client component for /team — handles the invite form, role
// change dropdown, and disable button. Receives the initial
// membership list as a prop and re-fetches on mutation so the
// state stays in sync with the server.
//
// The component is intentionally minimal — no animations, no
// optimistic updates. The user reloads the list after every
// mutation so the server is the source of truth (matters for
// the "last active owner" check in the API).

import { useState, useTransition } from "react";
import { toUserFacingError } from "@/lib/ui-error";
import styles from "../shell.module.css";

export interface MembershipRow {
  id: string;
  email: string;
  role: string;
  status: "pending" | "active" | "inactive";
  invitedAt: string;
  activatedAt: string | null;
  createdAt: string;
  user: { id: string; email: string; name: string | null } | null;
}

interface TeamClientProps {
  viewerUserId: string;
  viewerRole: string;
  viewerStatus: "pending" | "active" | "inactive";
  tenantName: string;
  initialMemberships: MembershipRow[];
}

const ROLE_OPTIONS = [
  { value: "owner", label: "Owner" },
  { value: "auditor", label: "Auditor" },
  { value: "viewer", label: "Viewer" },
] as const;

function roleLabel(role: string): string {
  const found = ROLE_OPTIONS.find((r) => r.value === role);
  return found?.label ?? role;
}

function roleBadgeClass(role: string): string {
  // Stylized by role: owner is purple, auditor blue, viewer
  // grey, admin (legacy) the same as owner.
  if (role === "owner" || role === "admin") return styles.badgeOwner ?? "";
  if (role === "auditor") return styles.badgeAuditor ?? "";
  return styles.badgeViewer ?? "";
}

function statusBadgeClass(status: MembershipRow["status"]): string {
  if (status === "active") return styles.badgeActive ?? "";
  if (status === "pending") return styles.badgePending ?? "";
  return styles.badgeInactive ?? "";
}

export function TeamClient({
  viewerUserId,
  viewerRole,
  viewerStatus,
  tenantName,
  initialMemberships,
}: TeamClientProps) {
  const [memberships, setMemberships] = useState<MembershipRow[]>(
    initialMemberships,
  );
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"owner" | "auditor" | "viewer">(
    "viewer",
  );
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busyMembershipId, setBusyMembershipId] = useState<string | null>(
    null,
  );
  const [isPending, startTransition] = useTransition();

  const canManage = viewerStatus === "active" && (viewerRole === "owner" || viewerRole === "admin");

  async function refreshList() {
    try {
      const res = await fetch("/api/team", { method: "GET" });
      if (!res.ok) {
        // Fall through with stale data — the page will reload
        // on the next navigation.
        return;
      }
      const data = (await res.json()) as { memberships: MembershipRow[] };
      setMemberships(data.memberships);
    } catch {
      // Network error: leave the existing list in place.
    }
  }

  function handleInvite(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setInfo(null);
    if (!canManage) {
      setError("Your role can't invite members.");
      return;
    }
    startTransition(async () => {
      try {
        const res = await fetch("/api/team/invite", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
        });
        const data = (await res.json().catch(() => ({}))) as {
          error?: string;
          detail?: string;
          membership?: MembershipRow;
          emailDispatch?: { sent?: boolean; mock?: boolean };
        };
        if (!res.ok) {
          setError(data.detail ?? data.error ?? `Invite failed (${res.status})`);
          return;
        }
        setInviteEmail("");
        if (data.emailDispatch?.mock) {
          setInfo(
            `Invite recorded. Email dispatch is in dev-mock mode — the link is in the dev server's stdout.`,
          );
        } else {
          setInfo(`Invite email sent to ${data.membership?.email ?? inviteEmail}.`);
        }
        await refreshList();
      } catch (e) {
        setError(toUserFacingError(e, "Network error"));
      }
    });
  }

  function handleRoleChange(membership: MembershipRow, newRole: string) {
    if (newRole === membership.role) return;
    setError(null);
    setInfo(null);
    setBusyMembershipId(membership.id);
    startTransition(async () => {
      try {
        const res = await fetch(`/api/team/${encodeURIComponent(membership.id)}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ role: newRole }),
        });
        const data = (await res.json().catch(() => ({}))) as {
          error?: string;
          detail?: string;
        };
        if (!res.ok) {
          setError(data.detail ?? data.error ?? `Update failed (${res.status})`);
          return;
        }
        setInfo(`Role updated for ${membership.email}.`);
        await refreshList();
      } catch (e) {
        setError(toUserFacingError(e, "Network error"));
      } finally {
        setBusyMembershipId(null);
      }
    });
  }

  function handleDisable(membership: MembershipRow) {
    setError(null);
    setInfo(null);
    if (
      !window.confirm(
        `Disable ${membership.email}? They'll lose access to ${tenantName} immediately. You can re-invite them later.`,
      )
    ) {
      return;
    }
    setBusyMembershipId(membership.id);
    startTransition(async () => {
      try {
        const res = await fetch(`/api/team/${encodeURIComponent(membership.id)}`, {
          method: "DELETE",
        });
        const data = (await res.json().catch(() => ({}))) as {
          error?: string;
          detail?: string;
        };
        if (!res.ok) {
          setError(data.detail ?? data.error ?? `Disable failed (${res.status})`);
          return;
        }
        setInfo(`${membership.email} has been disabled.`);
        await refreshList();
      } catch (e) {
        setError(toUserFacingError(e, "Network error"));
      } finally {
        setBusyMembershipId(null);
      }
    });
  }

  // Group rows: active first, then pending, then inactive. The
  // server already orders by status asc; we keep that order
  // and just bucket them visually with section headings.
  const active = memberships.filter((m) => m.status === "active");
  const pending = memberships.filter((m) => m.status === "pending");
  const inactive = memberships.filter((m) => m.status === "inactive");

  return (
    <>
      {canManage && (
        <section className={styles.card}>
          <h2 style={{ margin: "0 0 12px", fontSize: 16 }}>Invite a teammate</h2>
          <form
            onSubmit={handleInvite}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 140px 110px",
              gap: 10,
              alignItems: "stretch",
            }}
          >
            <input
              type="email"
              required
              placeholder="name@clinic.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              aria-label="Invitee email"
              style={inputStyle}
            />
            <select
              value={inviteRole}
              onChange={(e) =>
                setInviteRole(e.target.value as "owner" | "auditor" | "viewer")
              }
              aria-label="Role"
              style={inputStyle}
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
            <button
              type="submit"
              disabled={isPending}
              style={{
                background: "#4f46e5",
                color: "white",
                border: 0,
                borderRadius: 6,
                padding: "8px 14px",
                fontWeight: 600,
                cursor: isPending ? "not-allowed" : "pointer",
                opacity: isPending ? 0.6 : 1,
              }}
            >
              {isPending ? "Sending…" : "Send invite"}
            </button>
          </form>
        </section>
      )}

      {error && (
        <p
          role="alert"
          style={{
            color: "#fca5a5",
            background: "#7f1d1d33",
            border: "1px solid #b91c1c",
            padding: "10px 14px",
            borderRadius: 6,
            margin: "12px 0",
          }}
        >
          {error}
        </p>
      )}
      {info && (
        <p
          role="status"
          style={{
            color: "#86efac",
            background: "#14532d33",
            border: "1px solid #16a34a",
            padding: "10px 14px",
            borderRadius: 6,
            margin: "12px 0",
          }}
        >
          {info}
        </p>
      )}

      {memberships.length === 0 ? (
        <section className={styles.empty}>
          <h2>No members yet</h2>
          <p>Invite a teammate to get started.</p>
        </section>
      ) : (
        <>
          {active.length > 0 && renderTable("Active members", active)}
          {pending.length > 0 && renderTable("Pending invites", pending)}
          {inactive.length > 0 && renderTable("Disabled", inactive)}
        </>
      )}
    </>
  );

  function renderTable(heading: string, rows: MembershipRow[]) {
    return (
      <section className={styles.card} style={{ marginTop: 16 }}>
        <h2 style={{ margin: "0 0 12px", fontSize: 16 }}>{heading}</h2>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>{heading === "Pending invites" ? "Invited" : "Joined"}</th>
              {canManage && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const isSelf = m.user?.id === viewerUserId;
              const busy = busyMembershipId === m.id || isPending;
              return (
                <tr key={m.id}>
                  <td>
                    {m.user?.name ? (
                      <>
                        <div>{m.user.name}</div>
                        <div style={{ fontSize: 12, color: "#9aa3bd" }}>{m.email}</div>
                      </>
                    ) : (
                      m.email
                    )}
                  </td>
                  <td>
                    {canManage && m.status !== "inactive" ? (
                      <select
                        defaultValue={m.role}
                        disabled={busy}
                        onChange={(e) => handleRoleChange(m, e.target.value)}
                        aria-label={`Role for ${m.email}`}
                        style={{
                          ...inputStyle,
                          padding: "4px 8px",
                          minWidth: 110,
                        }}
                      >
                        {ROLE_OPTIONS.map((r) => (
                          <option key={r.value} value={r.value}>
                            {r.label}
                          </option>
                        ))}
                        {m.role === "admin" && (
                          <option value="admin">Admin (legacy)</option>
                        )}
                      </select>
                    ) : (
                      <span className={roleBadgeClass(m.role)}>
                        {roleLabel(m.role)}
                      </span>
                    )}
                  </td>
                  <td>
                    <span className={statusBadgeClass(m.status)}>{m.status}</span>
                  </td>
                  <td style={{ color: "#9aa3bd", fontSize: 12 }}>
                    {heading === "Pending invites"
                      ? new Date(m.invitedAt).toISOString().slice(0, 10)
                      : m.activatedAt
                        ? new Date(m.activatedAt).toISOString().slice(0, 10)
                        : new Date(m.createdAt).toISOString().slice(0, 10)}
                  </td>
                  {canManage && (
                    <td>
                      {m.status !== "inactive" ? (
                        <button
                          type="button"
                          onClick={() => handleDisable(m)}
                          disabled={busy || isSelf}
                          title={
                            isSelf
                              ? "You can't disable yourself"
                              : "Disable this member"
                          }
                          style={{
                            background: "transparent",
                            color: "#fca5a5",
                            border: "1px solid #b91c1c",
                            borderRadius: 4,
                            padding: "4px 10px",
                            fontSize: 12,
                            cursor: busy || isSelf ? "not-allowed" : "pointer",
                            opacity: busy || isSelf ? 0.5 : 1,
                          }}
                        >
                          {busy ? "Working…" : "Disable"}
                        </button>
                      ) : (
                        <span style={{ color: "#6b7280", fontSize: 12 }}>
                          Disabled
                        </span>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    );
  }
}

const inputStyle: React.CSSProperties = {
  background: "#0b1020",
  color: "#e6e9f2",
  border: "1px solid #28324f",
  borderRadius: 6,
  padding: "8px 12px",
  fontSize: 14,
  fontFamily: "inherit",
};
