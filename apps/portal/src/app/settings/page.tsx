// /settings — tenant settings route (t_1bab62b6).
//
// Four sections, per the task spec:
//   1. Clinic Profile   — editable; name, address, billing NPI, timezone
//   2. EHR Connection   — read-only; connected/disconnected, last sync,
//                          next scheduled sync
//   3. Data Residency   — region selector; locked once the first audit
//                          has been recorded
//   4. PHI Handling     — redaction toggle for audit log exports
//
// Section 1, 3, 4 are owned by the SettingsForms client component. The
// EHR section is fully read-only and rendered server-side.
//
// Data residency lock is computed in two places and OR'd together:
//   - the wizard's residencyRegionLocked flag (set on completion)
//   - the existence of an Encounter row for this tenant
// Both server-enforce the lock at the lib layer; the UI surfaces the
// condition via a disabled select and a tooltip.

import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";
import { tenantHasAudit } from "@/lib/settings";
import { RESIDENCY_REGIONS } from "@/lib/settings";
import { PortalNav } from "../portal-nav";
import styles from "../shell.module.css";
import SettingsForms from "./SettingsForms";

export const metadata: Metadata = {
  // Authenticated portal page — must stay out of search engine indexes.
  // Overrides the root layout's `robots: { index: true, follow: true }`.
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// EHR sync cadence: a single value kept here so the page and any
// future /api/ehr/* route can agree. Real production would source
// this from the cron schedule or a SFTP-pull config; for now the
// portal shows "next pull = lastSync + this interval" so the user
// sees a sensible number.
const EHR_SYNC_INTERVAL_MS = 24 * 60 * 60 * 1000; // 24 hours

export default async function SettingsPage() {
  const session = await auth();
  if (!session?.user?.id) {
    redirect("/login?callbackUrl=/settings");
  }

  const tenant = await getActiveTenant();

  if (!tenant) {
    return (
      <main id="main" className={styles.shell}>
        <h1 className={styles.heading}>Settings</h1>
        <section className={styles.empty}>
          <h2>No clinic connected</h2>
          <p>You aren&rsquo;t a member of a clinic yet.</p>
        </section>
      </main>
    );
  }

  // Pull the row + derive the lock state + derive the EHR sync state
  // in a single read. We need:
  //   - clinic profile fields (for the form's initial state)
  //   - dataResidencyRegion + residencyRegionLocked
  //   - redactPatientNamesInExports
  //   - ehrConnectionMode + ehrSftpHost/Username (display only)
  //   - the latest Encounter.createdAt for the EHR "last sync" derivation
  const [row, hasAudit, latestEncounter] = await Promise.all([
    prisma.tenant.findUnique({
      where: { id: tenant.id },
      select: {
        name: true,
        clinicName: true,
        clinicAddress: true,
        clinicNpi: true,
        clinicTimezone: true,
        dataResidencyRegion: true,
        residencyRegionLocked: true,
        ehrConnectionMode: true,
        ehrSftpHost: true,
        ehrSftpUsername: true,
        redactPatientNamesInExports: true,
      },
    }),
    tenantHasAudit(tenant.id),
    prisma.encounter.findFirst({
      where: { tenantId: tenant.id },
      orderBy: { createdAt: "desc" },
      select: { createdAt: true },
    }),
  ]);

  if (!row) {
    return (
      <main id="main" className={styles.shell}>
        <h1 className={styles.heading}>Settings</h1>
        <section className={styles.empty}>
          <h2>Tenant not found</h2>
          <p>The active tenant no longer exists.</p>
        </section>
      </main>
    );
  }

  const residencyLocked = row.residencyRegionLocked || hasAudit;
  const ehrStatus = deriveEhrStatus({
    mode: row.ehrConnectionMode,
    lastSyncAt: latestEncounter?.createdAt ?? null,
    intervalMs: EHR_SYNC_INTERVAL_MS,
  });

  return (
    <main id="main" className={styles.shell}>
      <PortalNav current="/settings" tenant={tenant} />

      <h1 className={styles.heading}>Settings</h1>
      <p className={styles.subheading}>
        Clinic configuration. Edits save through to the database and
        reflect on reload.
      </p>

      {/* 1. Clinic profile (editable) */}
      {/* 3. Data residency (editable while no audit exists) */}
      {/* 4. PHI handling (editable) */}
      <SettingsForms
        tenantId={tenant.id}
        initial={{
          clinicName: row.clinicName,
          clinicAddress: row.clinicAddress,
          clinicNpi: row.clinicNpi,
          clinicTimezone: row.clinicTimezone,
          dataResidencyRegion: row.dataResidencyRegion,
          redactPatientNamesInExports: row.redactPatientNamesInExports,
        }}
        residencyRegions={RESIDENCY_REGIONS}
        residencyLocked={residencyLocked}
      />

      {/* 2. EHR connection (read-only) */}
      <section className={styles.card}>
        <header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 12,
            gap: 8,
          }}
        >
          <h2 style={{ margin: 0, fontSize: 16 }}>EHR connection</h2>
          <EhrStatusBadge connected={ehrStatus.connected} />
        </header>
        <p className={styles.muted} style={{ margin: "0 0 12px" }}>
          {ehrStatus.summary}
        </p>
        <Field
          label="Mode"
          value={ehrStatus.modeLabel}
        />
        {row.ehrSftpHost ? (
          <Field label="SFTP host" value={row.ehrSftpHost} mono />
        ) : null}
        {row.ehrSftpUsername ? (
          <Field
            label="SFTP username"
            value={row.ehrSftpUsername}
            mono
          />
        ) : null}
        <Field
          label="Last sync"
          value={ehrStatus.lastSyncLabel}
        />
        <Field
          label="Next scheduled sync"
          value={ehrStatus.nextSyncLabel}
        />
        <p
          className={styles.muted}
          style={{ margin: "12px 0 0", fontSize: 12 }}
        >
          {ehrStatus.footnote}
        </p>
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
          textAlign: "right",
          maxWidth: "60%",
        }}
      >
        {value}
      </span>
    </div>
  );
}

function EhrStatusBadge({ connected }: { connected: boolean }) {
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: 0.5,
        textTransform: "uppercase",
        padding: "2px 10px",
        borderRadius: 999,
        background: connected
          ? "rgba(45, 212, 191, 0.12)"
          : "rgba(156, 163, 189, 0.12)",
        color: connected ? "#2dd4bf" : "#9aa3bd",
      }}
    >
      {connected ? "Connected" : "Not connected"}
    </span>
  );
}

// ---------------------------------------------------------------------------
// EHR status derivation
// ---------------------------------------------------------------------------

interface DeriveArgs {
  mode: string | null;
  lastSyncAt: Date | null;
  intervalMs: number;
}

interface DeriveResult {
  connected: boolean;
  summary: string;
  modeLabel: string;
  lastSyncLabel: string;
  nextSyncLabel: string;
  footnote: string;
}

/**
 * The portal does not own an EHR sync pipeline. The honest read-only
 * view derives "last sync" from the most recent Encounter row
 * (data flowing in == we last pulled) and "next scheduled" as
 * lastSync + 24h. Both are labelled as derivations in the footnote
 * so the operator knows where they came from.
 *
 * When the tenant has no ehrConnectionMode set, the panel reports
 * "Not connected" with a hint to finish the onboarding wizard.
 */
function deriveEhrStatus(args: DeriveArgs): DeriveResult {
  const { mode, lastSyncAt, intervalMs } = args;
  const connected = mode === "sftp" || mode === "manual";

  if (!connected) {
    return {
      connected: false,
      summary:
        "EHR not configured. The onboarding wizard can connect an SFTP pull or set the clinic to manual uploads.",
      modeLabel: "—",
      lastSyncLabel: "—",
      nextSyncLabel: "—",
      footnote: "Mode is set during the onboarding wizard step 4.",
    };
  }

  const modeLabel = mode === "sftp" ? "SFTP pull" : "Manual upload";

  if (!lastSyncAt) {
    return {
      connected: true,
      summary:
        mode === "sftp"
          ? "SFTP credentials are configured. The portal hasn't ingested any encounters yet, so there's no sync history to display."
          : "Manual upload mode is configured. The portal hasn't ingested any encounters yet.",
      modeLabel,
      lastSyncLabel: "—",
      nextSyncLabel: "—",
      footnote:
        "Last sync is shown once at least one encounter has been ingested.",
    };
  }

  const lastSyncLabel = formatTimestamp(lastSyncAt);
  const nextSyncAt = new Date(lastSyncAt.getTime() + intervalMs);
  const nextSyncLabel = formatTimestamp(nextSyncAt);

  return {
    connected: true,
    summary:
      mode === "sftp"
        ? `SFTP pull is configured. Last successful ingest: ${lastSyncLabel}.`
        : `Manual upload is configured. Last upload: ${lastSyncLabel}.`,
    modeLabel,
    lastSyncLabel,
    nextSyncLabel,
    footnote:
      "Last sync is derived from the most recent encounter ingest. Next sync is a 24-hour estimate from that timestamp.",
  };
}

function formatTimestamp(d: Date): string {
  // Render in UTC for predictability; the user sees their browser tz
  // implicitly when they read the page. Date-only would lose
  // precision for "next sync" calculations; full ISO is too noisy.
  const pad = (n: number) => n.toString().padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
  );
}
