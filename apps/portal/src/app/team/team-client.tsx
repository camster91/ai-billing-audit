"use client";

// Client component for /team — handles the invite form, role
// change dropdown, and disable button. Receives the initial
// membership list as a prop and re-fetches on mutation so the
// state stays in sync with the server.

import { useState, useTransition } from "react";
import { toUserFacingError } from "@/lib/ui-error";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { InlineBanner } from "@/components/InlineBanner";
import { useToastOptional } from "@/components/Toast";
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
  const toast = useToastOptional();
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
  const [pendingDisable, setPendingDisable] = useState<MembershipRow | null>(
    null,
  );
  const [isPending, startTransition] = useTransition();

  const canManage =
    viewerStatus === "active" &&
    (viewerRole === "owner" || viewerRole === "admin");

  async function refreshList() {
    try {
      const res = await fetch("/api/team", { method: "GET" });
      if (!res.ok) return;
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
          const msg =
            data.detail ?? data.error ?? `Invite failed (${res.status})`;
          setError(msg);
          toast.push({
            title: "Invite failed",
            description: msg,
            tone: "error",
          });
          return;
        }
        setInviteEmail("");
        if (data.emailDispatch?.mock) {
          setInfo(
            `Invite recorded. Email dispatch is in dev-mock mode — the link is in the dev server's stdout.`,
          );
        } else {
          setInfo(
            `Invite email sent to ${data.membership?.email ?? inviteEmail}.`,
          );
        }
        toast.push({
          title: "Invite sent",
          description: data.membership?.email ?? inviteEmail,
          tone: "success",
        });
        await refreshList();
      } catch (e) {
        const msg = toUserFacingError(e, "Network error");
        setError(msg);
        toast.push({
          title: "Invite failed",
          description: msg,
          tone: "error",
        });
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
        const res = await fetch(
          `/api/team/${encodeURIComponent(membership.id)}`,
          {
            method: "PATCH",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ role: newRole }),
          },
        );
        const data = (await res.json().catch(() => ({}))) as {
          error?: string;
          detail?: string;
        };
        if (!res.ok) {
          const msg =
            data.detail ?? data.error ?? `Update failed (${res.status})`;
          setError(msg);
          toast.push({
            title: "Role update failed",
            description: msg,
            tone: "error",
          });
          return;
        }
        setInfo(`Role updated for ${membership.email}.`);
        toast.push({ title: "Role updated", tone: "success" });
        await refreshList();
      } catch (e) {
        const msg = toUserFacingError(e, "Network error");
        setError(msg);
        toast.push({
          title: "Role update failed",
          description: msg,
          tone: "error",
        });
      } finally {
        setBusyMembershipId(null);
      }
    });
  }

  function requestDisable(membership: MembershipRow) {
    setError(null);
    setInfo(null);
    setPendingDisable(membership);
  }

  function confirmDisable() {
    const membership = pendingDisable;
    if (!membership) return;
    setPendingDisable(null);
    setBusyMembershipId(membership.id);
    startTransition(async () => {
      try {
        const res = await fetch(
          `/api/team/${encodeURIComponent(membership.id)}`,
          {
            method: "DELETE",
          },
        );
        const data = (await res.json().catch(() => ({}))) as {
          error?: string;
          detail?: string;
        };
        if (!res.ok) {
          const msg =
            data.detail ?? data.error ?? `Disable failed (${res.status})`;
          setError(msg);
          toast.push({
            title: "Disable failed",
            description: msg,
            tone: "error",
          });
          return;
        }
        setInfo(`${membership.email} has been disabled.`);
        toast.push({ title: "Member disabled", tone: "success" });
        await refreshList();
      } catch (e) {
        const msg = toUserFacingError(e, "Network error");
        setError(msg);
        toast.push({
          title: "Disable failed",
          description: msg,
          tone: "error",
        });
      } finally {
        setBusyMembershipId(null);
      }
    });
  }

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
                background: "var(--zorva-accent-bg, #2563eb)",
                color: "white",
                border: 0,
                borderRadius: 8,
                minHeight: 44,
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

      {error ? <InlineBanner tone="error">{error}</InlineBanner> : null}
      {info ? <InlineBanner tone="success">{info}</InlineBanner> : null}

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

      <ConfirmDialog
        open={pendingDisable !== null}
        title="Disable team member?"
        description={
          pendingDisable
            ? `Disable ${pendingDisable.email}? They'll lose access to ${tenantName} immediately. You can re-invite them later.`
            : ""
        }
        confirmLabel="Disable"
        cancelLabel="Cancel"
        tone="danger"
        busy={busyMembershipId === pendingDisable?.id}
        onCancel={() => setPendingDisable(null)}
        onConfirm={confirmDisable}
      />
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
                        <div
                          style={{
                            fontSize: 12,
                            color: "var(--zorva-ink-2, #b6bfd6)",
                          }}
                        >
                          {m.email}
                        </div>
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
                          padding: "8px 10px",
                          minHeight: 44,
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
                    <span className={statusBadgeClass(m.status)}>
                      {m.status}
                    </span>
                  </td>
                  <td
                    style={{
                      color: "var(--zorva-ink-2, #b6bfd6)",
                      fontSize: 12,
                    }}
                  >
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
                          onClick={() => requestDisable(m)}
                          disabled={busy || isSelf}
                          title={
                            isSelf
                              ? "You can't disable yourself"
                              : "Disable this member"
                          }
                          style={{
                            background: "transparent",
                            color: "var(--zorva-error, #fca5a5)",
                            border:
                              "1px solid var(--zorva-error-border, rgba(252,165,165,0.35))",
                            borderRadius: 8,
                            minHeight: 44,
                            minWidth: 44,
                            padding: "8px 12px",
                            fontSize: 13,
                            cursor:
                              busy || isSelf ? "not-allowed" : "pointer",
                            opacity: busy || isSelf ? 0.5 : 1,
                          }}
                        >
                          {busy ? "Working…" : "Disable"}
                        </button>
                      ) : (
                        <span
                          style={{
                            color: "var(--zorva-ink-3, #8b93ad)",
                            fontSize: 12,
                          }}
                        >
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
  background: "var(--zorva-bg, #0b1020)",
  color: "var(--zorva-ink, #e7ecf6)",
  border: "1px solid var(--zorva-line, #28324f)",
  borderRadius: 8,
  padding: "10px 12px",
  minHeight: 44,
  fontSize: 14,
  fontFamily: "inherit",
};
