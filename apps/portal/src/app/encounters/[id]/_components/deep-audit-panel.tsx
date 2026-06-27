// _components/deep-audit-panel.tsx
//
// Surfaces the FastAPI's denial-risk + appeal-letter data on the
// portal's encounter-detail page. The portal at zorva.ashbi.ca has
// its own Prisma DB for the encounter workspace; the FastAPI at
// ai-billing-audit.ashbi.ca is where the auditor actually runs and
// produces the audited findings + denial-risk score + appeal letters.
//
// The two data stores use the same encounter_id when an encounter
// is uploaded via the FastAPI's upload portal (which both the
// FastAPI and the portal read from via /api/tenants/{id}/export.jsonl).
// When the IDs match, this panel shows the real audit results. When
// they don't (e.g. portal-only demo encounters), the panel renders
// a graceful "deep audit not available for this encounter" fallback
// with a "Open in Zorva API" link so the biller can still navigate
// to the FastAPI directly.
//
// Architecture note: this is a Server Component (no "use client")
// because the data is fetched at request time on the server. The
// panel is a pure data sink; future interactive bits (a "generate
// appeal letter" button that POSTs back to the FastAPI) would
// require either a Client Component sub-tree or a service-to-service
// auth between the portal and the FastAPI (out of scope here).

import Link from "next/link";
import type {
  AppealLetterSummary,
  DenialRisk,
} from "@/lib/fastapi";
import styles from "./deep-audit-panel.module.css";

interface DeepAuditPanelProps {
  encounterId: string;
  denialRisk: DenialRisk | null;
  denialRiskUnavailable: boolean;
  /** Most recent appeal letter for the encounter (summary shape,
   *  no body). The full body is fetched on-demand via a separate
   *  route (out of scope for this initial panel). */
  appealLetter: AppealLetterSummary | null;
  appealLetterUnavailable: boolean;
  appealLetters: AppealLetterSummary[];
  appealLettersUnavailable: boolean;
  /** Full URL to the FastAPI's encounter-detail page (canonical
   *  source of truth for the audited encounter). */
  fastapiEncounterUrl: string;
  /** Just the origin (used for the "Powered by ai-billing-audit" footer). */
  fastapiOrigin: string;
}

export function DeepAuditPanel({
  encounterId,
  denialRisk,
  denialRiskUnavailable,
  appealLetter,
  appealLetterUnavailable,
  appealLetters,
  appealLettersUnavailable,
  fastapiEncounterUrl,
  fastapiOrigin,
}: DeepAuditPanelProps) {
  return (
    <aside
      className={styles.panel}
      aria-label="Deep audit (powered by ai-billing-audit FastAPI)"
    >
      <header className={styles.panelHeader}>
        <h3>Deep audit</h3>
        <a
          href={fastapiEncounterUrl}
          target="_blank"
          rel="noopener noreferrer"
          className={styles.openInFastApi}
        >
          Open in Zorva API ↗
        </a>
      </header>

      <section className={styles.subpanel} aria-label="Denial risk score">
        <h4>Denial risk</h4>
        {denialRisk === null ? (
          <NotAvailable
            unavailable={denialRiskUnavailable}
            encounterId={encounterId}
            fastapiUrl={fastapiEncounterUrl}
          />
        ) : (
          <DenialRiskBody risk={denialRisk} />
        )}
      </section>

      <section
        className={styles.subpanel}
        aria-label="Appeal letter"
      >
        <h4>Appeal letter</h4>
        {appealLetter === null ? (
          <NotAvailable
            unavailable={appealLetterUnavailable}
            encounterId={encounterId}
            fastapiUrl={fastapiEncounterUrl}
            whatFor="appeal letter"
          />
        ) : (
          <AppealLetterBody letter={appealLetter} history={appealLetters} />
        )}
      </section>

      <footer className={styles.panelFooter}>
        Powered by{" "}
        <a
          href={fastapiOrigin}
          target="_blank"
          rel="noopener noreferrer"
        >
          {new URL(fastapiOrigin).host}
        </a>
      </footer>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function NotAvailable({
  unavailable,
  encounterId,
  fastapiUrl,
  whatFor = "deep audit",
}: {
  unavailable: boolean;
  encounterId: string;
  fastapiUrl: string;
  whatFor?: string;
}) {
  if (!unavailable) {
    // The FastAPI returned ok but with no data (e.g. zero findings,
    // so denialRisk.n_findings == 0 → data is null). Distinguish from
    // "not available because the FastAPI doesn't know this encounter".
    return (
      <p className={styles.empty}>
        No {whatFor} data. Open the encounter in the Zorva API to view
        or generate one.
      </p>
    );
  }
  return (
    <p className={styles.unavailable}>
      <strong>Not available in the portal.</strong> Encounter{" "}
      <code>{encounterId}</code> isn&apos;t registered in the Zorva
      FastAPI audit registry.{" "}
      <a href={fastapiUrl} target="_blank" rel="noopener noreferrer">
        Open in Zorva API ↗
      </a>
    </p>
  );
}

function DenialRiskBody({ risk }: { risk: DenialRisk }) {
  const tierClass = `${styles.tier} ${styles[`tier_${risk.tier}`] ?? ""}`;
  const pct =
    risk.denial_probability === null
      ? "—"
      : `${Math.round(risk.denial_probability * 100)}%`;
  return (
    <>
      <p className={tierClass}>
        <span className={styles.tierValue}>{pct}</span>
        <span className={styles.tierLabel}>{risk.tier.replace("_", " ")}</span>
      </p>
      <p className={styles.meta}>
        {risk.n_findings} finding{risk.n_findings === 1 ? "" : "s"}
        {risk.top_risk ? (
          <>
            {" "}— top risk: <code>{risk.top_risk.rule_id}</code>{" "}
            ({risk.top_risk.severity})
          </>
        ) : null}
      </p>
      {risk.per_finding.length > 0 ? (
        <ul className={styles.findingList}>
          {risk.per_finding
            .filter((f) => f.contributes_to_risk)
            .slice(0, 3)
            .map((f) => (
              <li key={f.finding_id}>
                <code>{f.rule_id}</code>{" "}
                <span className={styles.severity}>{f.severity}</span>{" "}
                <span className={styles.weight}>w={f.weight.toFixed(2)}</span>
              </li>
            ))}
        </ul>
      ) : null}
    </>
  );
}

function AppealLetterBody({
  letter,
  history,
}: {
  letter: AppealLetterSummary;
  history: AppealLetterSummary[];
}) {
  const generated = new Date(letter.generated_at);
  return (
    <>
      <p className={styles.meta}>
        Generated {generated.toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" })}
        {" — "}
        <strong>{letter.basis}</strong>
        {letter.has_outcome ? (
          <span className={styles.outcome}>
            {" "}— outcome: <em>{letter.outcome_status ?? "unknown"}</em>
          </span>
        ) : null}
      </p>
      <p className={styles.nextActions}>
        Requested action: <em>{letter.requested_action}</em>
      </p>
      <p className={styles.viewFull}>
        <a
          href={`https://ai-billing-audit.ashbi.ca/encounter/${encodeURIComponent(letter.encounter_id)}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open letter in Zorva API ↗
        </a>
      </p>
      {history.length > 1 ? (
        <p className={styles.history}>
          {history.length} letters on file for this encounter.
        </p>
      ) : null}
    </>
  );
}