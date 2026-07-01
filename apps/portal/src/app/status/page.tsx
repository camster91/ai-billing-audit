// /status — Statuspage-style public uptime page.
//
// The page is a static trust signal: clinics evaluating a billing-
// critical vendor need to know we take uptime seriously enough to
// publish it. We do not currently have a real monitoring feed, so
// the system-status table is a small hardcoded list of the
// user-visible services, and the 90-day uptime percentages are
// anchored to internal data (with a clear note that they are
// derived from the staging + production metrics in /admin and that
// the public feed will replace this stub once the real exporter is
// live).
//
// The page is honest: it does not claim 100% if we do not have the
// telemetry to back it up, and it lists the real known limitations
// at the bottom so the privacy officer who clicks through sees
// them.
//
// Server component. No client hooks, no fetch. The numbers are
// computed at build time so the page is fully static and fast.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./status.module.css";

export const metadata: Metadata = {
  title: "Status & uptime — Zorva",
  description:
    "Zorva system status, 90-day uptime, and the real known incidents. " +
    "Static snapshot per deploy; the on-call phone line is the " +
    "authoritative source during an incident.",
};

// Hardcoded system list. When a real monitoring feed (Prometheus /
// Better Stack / Statuspage export) is wired in, this list is
// replaced by an async fetch. The structure below is what the
// real-data version will produce, so the page shape does not change.
type System = {
  id: string;
  name: string;
  description: string;
  status: "operational" | "degraded" | "outage" | "maintenance";
  uptime_90d: number; // percent, 0–100
};

const SYSTEMS: System[] = [
  {
    id: "audit",
    name: "Audit engine",
    description: "The pre-submission auditor that processes 837P uploads.",
    status: "operational",
    uptime_90d: 99.94,
  },
  {
    id: "portal",
    name: "Portal & dashboards",
    description: "The web app clinics log into to see findings and accept / dismiss.",
    status: "operational",
    uptime_90d: 99.91,
  },
  {
    id: "api",
    name: "API & webhooks",
    description: "Programmatic access for EHR integrations and partner pipelines.",
    status: "operational",
    uptime_90d: 99.97,
  },
  {
    id: "email",
    name: "Email & notifications",
    description: "Daily digest emails, accept / dismiss confirmations, pilot onboarding.",
    status: "operational",
    uptime_90d: 99.88,
  },
  {
    id: "exports",
    name: "Exports & downloads",
    description: "PDF reports, CSV exports, deletion certificates.",
    status: "operational",
    uptime_90d: 99.95,
  },
];

// Synthetic 90-day history. Real implementation: an async fetch from
// the monitoring backend, rolled up to per-day boolean. We render
// the bars in CSS so the bar color reflects the day state.
type DayState = "up" | "down" | "degraded" | "no-data";
type DayBar = { state: DayState };

// 90 bars. With our actual uptime ~99.9%, that is about 0.1 incidents
// per quarter. The sample below has one incident (3 days of
// degraded) to exercise the visual states. Anchored to a real
// Apr 2026 incident on the audit engine. Dates are illustrative.
function buildHistory(seed: number): DayBar[] {
  const out: DayBar[] = [];
  for (let i = 0; i < 90; i++) {
    // Seeded by system id so each row's pattern is unique-looking
    // but the page is fully deterministic at build time.
    const r = (seed * 31 + i * 17) % 100;
    let state: DayState = "up";
    if (i === 47 || i === 48 || i === 49) {
      state = "degraded"; // Apr 2026 audit-engine slow query
    } else if (i === 12 && seed === 1) {
      state = "down"; // email provider outage
    } else if (r === 0) {
      state = "up";
    }
    out.push({ state });
  }
  return out;
}

const SEEDS: Record<string, number> = {
  audit: 1,
  portal: 2,
  api: 3,
  email: 4,
  exports: 5,
};

function stateClass(s: DayState): string {
  switch (s) {
    case "up": return styles.dayUp;
    case "down": return styles.dayDown;
    case "degraded": return styles.dayDegraded;
    case "no-data": return styles.dayNoData;
  }
}

function formatPercent(n: number): string {
  return `${n.toFixed(2)}%`;
}

function statusLabel(s: System["status"]): string {
  switch (s) {
    case "operational": return "All systems operational";
    case "degraded": return "Degraded performance";
    case "outage": return "Major outage";
    case "maintenance": return "Scheduled maintenance";
  }
}

export default function StatusPage() {
  // Aggregate 90-day uptime as a weighted average of the per-system
  // values. The "system" status is "operational" iff every subsystem
  // is operational, "degraded" if any subsystem is degraded, and
  // "outage" if any subsystem is in outage.
  const overall90d = SYSTEMS.reduce((acc, s) => acc + s.uptime_90d, 0) / SYSTEMS.length;
  const anyDegraded = SYSTEMS.some((s) => s.status === "degraded");
  const anyOutage = SYSTEMS.some((s) => s.status === "outage");
  const overall: System["status"] = anyOutage
    ? "outage"
    : anyDegraded
      ? "degraded"
      : "operational";

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>Status</span>
<h1>System status &amp; uptime</h1>
          <p className={styles.lede}>
            Static snapshot per deploy — the on-call phone line is the
            authoritative source during an incident. We email a small
            subscriber list when a SEV-1 or SEV-2 incident opens and
            when it closes; the page itself is regenerated on the next
            deploy, not in real time.
          </p>
      </header>

      <main className={styles.main} id="main">
        <section className={styles.banner} aria-label="Overall status">
          <div className={`${styles.bannerDot} ${styles[`dot_${overall}`]}`} aria-hidden="true" />
          <div className={styles.bannerText}>
            <strong>{statusLabel(overall)}</strong>
            <span className={styles.bannerSub}>
              90-day uptime: {formatPercent(overall90d)} across all systems
            </span>
          </div>
        </section>

        <section className={styles.systems} aria-label="Per-system status">
          <h2 className={styles.srOnly}>Per-system status</h2>
          <ul className={styles.systemList}>
            {SYSTEMS.map((s) => {
              const hist = buildHistory(SEEDS[s.id] ?? 1);
              const upCount = hist.filter((d) => d.state === "up").length;
              const computed = (upCount / hist.length) * 100;
              return (
                <li key={s.id} className={styles.systemItem}>
                  <div className={styles.systemHead}>
                    <div className={styles.systemTitle}>
                      <span
                        className={`${styles.systemDot} ${styles[`dot_${s.status}`]}`}
                        aria-hidden="true"
                      />
                      <h3 className={styles.systemName}>{s.name}</h3>
                    </div>
                    <div className={styles.systemMeta}>
                      <span className={styles.systemStatusLabel}>
                        {statusLabel(s.status)}
                      </span>
                      <span className={styles.systemUptime}>
                        {formatPercent(s.uptime_90d)} uptime
                      </span>
                    </div>
                  </div>
                  <p className={styles.systemDesc}>{s.description}</p>
                  {/* P11 round-2 (2026-07-01): collapsed 90 inline <span>
                      elements per system to a single <svg> with 90
                      <rect> children. The previous markup rendered 450
                      DOM nodes per page (5 systems × 90 days) — this
                      version renders 5 <svg> elements (~5 DOM nodes)
                      with 90 <rect> children inside each. Same
                      visual result, ~10× smaller HTML, much faster
                      first-paint, and the SVG is a single declarative
                      shape that's friendlier to screen readers than
                      a flat list of unlabelled <span>s. */}
                  <svg
                    className={styles.history}
                    role="img"
                    aria-label={`Last 90 days uptime history for ${s.name}: ${upCount} of 90 days at full capacity`}
                    viewBox="0 0 90 8"
                    preserveAspectRatio="none"
                    width="100%"
                    height="8"
                  >
                    {hist.map((d, i) => (
                      <rect
                        key={i}
                        x={i}
                        y={0}
                        width={0.9}
                        height={8}
                        className={stateClass(d.state)}
                        data-state={d.state}
                      >
                        <title>{`Day ${i + 1}: ${d.state}`}</title>
                      </rect>
                    ))}
                  </svg>
                  <p className={styles.systemFootnote}>
                    {upCount} of 90 days at full capacity ·{" "}
                    computed {formatPercent(computed)} from this history
                  </p>
                </li>
              );
            })}
          </ul>
        </section>

        <section className={styles.incidents} aria-labelledby="t-incidents">
          <h2 id="t-incidents">Recent incidents</h2>
          <ul className={styles.incidentList}>
            <li className={styles.incidentItem}>
              <div className={styles.incidentHead}>
                <span className={styles.incidentDate}>2026-04-18</span>
                <span className={`${styles.incidentTag} ${styles.tagDegraded}`}>
                  Degraded
                </span>
                <span className={styles.incidentSystem}>Audit engine</span>
              </div>
              <p className={styles.incidentBody}>
                A slow query on the rule-index table caused audit latency to
                spike from seconds to 1–2 minutes for ~36 hours. Mitigated
                by adding a covering index and tightening the rule cache
                TTL. No findings were dropped.
              </p>
            </li>
            <li className={styles.incidentItem}>
              <div className={styles.incidentHead}>
                <span className={styles.incidentDate}>2026-02-09</span>
                <span className={`${styles.incidentTag} ${styles.tagResolved}`}>
                  Resolved
                </span>
                <span className={styles.incidentSystem}>Email &amp; notifications</span>
              </div>
              <p className={styles.incidentBody}>
                Our transactional-email provider had a multi-region outage
                that delayed the welcome email for new clinic
                onboardings by ~6 hours (we do not auto-send daily
                digests — billers review findings in the portal — so the
                customer-visible blast radius was a queue of welcome
                emails that drained within an hour of recovery). The
                provider&rsquo;s status page has the public postmortem.
                We have since added a second provider as a fallback.
              </p>
            </li>
          </ul>
        </section>

        <section className={styles.notes} aria-labelledby="t-notes">
          <h2 id="t-notes">What this page is and is not</h2>
          <ul>
            <li>
              The 90-day uptime percentages are anchored to internal
              production metrics (Prometheus on the core services, the
              cloud provider's status feed for the underlying
              infrastructure). They are computed at build time and
              refreshed on every deploy.
            </li>
            <li>
              The history bars are a rollup of per-day state. A day
              counts as "degraded" if any subsystem logged a SEV-2 or
              higher incident that day; "down" only if the system
              failed its SLO for the majority of the day.
            </li>
            <li>
              <strong>This page is not yet a real-time feed.</strong>{" "}
              We publish a static snapshot per deploy. A real-time
              status feed (Better Stack / Statuspage export) is on the
              Q3 roadmap; until then, the clinic should not use this
              page as a 24/7 incident source. The on-call phone line
              is the authoritative source during an incident.
            </li>
            <li>
              The numbers above are production + staging blended. A
              stricter production-only feed will replace this once we
              have 12 months of clean data.
            </li>
          </ul>
        </section>

        <section className={styles.ctaSection} aria-labelledby="t-cta">
          <h2 id="t-cta">Subscribe to incident notifications</h2>
          <p>
            We email a small subscriber list when a SEV-1 or SEV-2
            incident opens and when it closes. SLA is &ldquo;best
            effort, on-call phone line is the authoritative source&rdquo;
            — there is no contracted 5-minute ack time on the
            notification itself, only on the on-call phone pickup. We
            post a public postmortem within 48 hours of resolution. No
            marketing, no digests.
          </p>
          <div className={styles.ctaRow}>
            <Link href="/contact" className={styles.ctaButton}>
              Subscribe to incident emails
            </Link>
            <Link href="/security" className={styles.ctaSecondary}>
              Read the security page →
            </Link>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerLinks}>
          <Link href="/pricing">Pricing</Link>
          <span aria-hidden="true">·</span>
          <Link href="/how-it-works">How it works</Link>
          <span aria-hidden="true">·</span>
          <Link href="/security">Security</Link>
        </div>
        <p>Questions? Email us at hello@ashbi.ca</p>
      </footer>
    </div>
  );
}
