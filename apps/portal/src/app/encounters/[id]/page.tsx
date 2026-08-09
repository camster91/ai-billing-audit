// /encounters/[id] — split-screen review page.
//
// Two-pane layout:
//   - Left: clinical narrative (with evidence_quote highlights) +
//     the billed claim JSON below.
//   - Right: list of AI findings, each with category badge, code change,
//     evidence quote, rule reference, financial impact, and Accept /
//     Dismiss actions.
//
// The page is a Server Component — it loads the encounter via
// `loadEncounterDetail` and pre-wraps the narrative's evidence spans
// in <mark> tags using `wrapEvidenceQuotes`. The interactive bits
// (the finding cards, the evidence-click highlight) are small Client
// Components imported from the `_components/` directory.
//
// Tenant isolation: the `getActiveTenant()` helper resolves the
// current tenant from the session, and the data layer filters by
// `tenantId`. A user in a different tenant can never read this
// encounter — the data layer returns null and `notFound()` 404s.
//
// Auth: the page is reachable only through the proxy (see
// src/proxy.ts) which redirects unauthenticated users to /login.

import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { getActiveTenant } from "@/lib/active-tenant";
import { loadEncounterDetail } from "@/lib/encounter-data";
import { formatCents, formatDate, wrapEvidenceQuotes } from "@/lib/encounter-format";
import {
  ENCOUNTER_STATUSES,
  isDismissReason,
  isFindingCategory,
  type EncounterStatus,
} from "@/lib/encounter-types";
import {
  fetchDenialRisk,
  fetchLatestAppealLetter,
  fetchAppealLetters,
  fastapiEncounterUrl,
  FASTAPI_ORIGIN,
} from "@/lib/fastapi";
import { ClinicalNote } from "./_components/clinical-note";
import { FindingCard } from "./_components/finding-card";
import { DeepAuditPanel } from "./_components/deep-audit-panel";
import { AuditRunControl } from "./_components/audit-run-control";
import { hasCapability } from "@/lib/roles";
import styles from "./_components/split-review.module.css";

interface PageProps {
  params: Promise<{ id: string }>;
}

export const dynamic = "force-dynamic"; // session-driven; never cache

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  // The id may be a Mongo ObjectId or a friendly encounter_id (e.g. ca_ahcip_004).
  // Surface the first 12 chars of whatever the URL holds so each encounter gets
  // its own unique tab title; we do not load the full record here because
  // generateMetadata runs for every render and we want this cheap.
  const short = id.length > 12 ? `${id.slice(0, 12)}…` : id;
  return {
    title: `Encounter ${short} — Zorva`,
  };
}

export default async function EncounterDetailPage({ params }: PageProps) {
  const { id } = await params;

  const tenant = await getActiveTenant();
  if (!tenant) {
    // Authenticated but no tenant — the proxy already redirected
    // for protected API routes. For pages, we 404 the same way
    // missing-data 404s; the user can re-pick a tenant from /team.
    notFound();
  }

  const encounter = await loadEncounterDetail(id, tenant.id);
  if (!encounter) notFound();

  // Pre-wrap the narrative so the client component just renders.
  const { html: noteHtml, matches } = wrapEvidenceQuotes(
    encounter.clinicalNote,
    encounter.findings.map((f) => ({ id: f.id, quote: f.evidenceQuote })),
  );
  const evidenceToCard: Record<string, string> = {};
  for (const m of matches) {
    evidenceToCard[m.id] = `finding-${m.id}`;
  }

  // Fetch the FastAPI data with a short-lived principal bound to the
  // verified portal membership. Credentials remain server-side.
  const fastApiPrincipal = {
    subject: tenant.userId,
    tenantId: tenant.id,
    portalRole: tenant.role,
  };
  const [denialRiskRes, appealLetterRes, appealLettersRes] = await Promise.all([
    fetchDenialRisk(encounter.id, fastApiPrincipal),
    fetchLatestAppealLetter(encounter.id, fastApiPrincipal),
    fetchAppealLetters(encounter.id, fastApiPrincipal),
  ]);
  const deepAudit = {
    denialRisk:
      denialRiskRes.kind === "ok" ? denialRiskRes.data : null,
    denialRiskUnavailable: denialRiskRes.kind !== "ok",
    appealLetter:
      appealLetterRes.kind === "ok" ? appealLetterRes.data : null,
    appealLetterUnavailable: appealLetterRes.kind !== "ok",
    appealLetters:
      appealLettersRes.kind === "ok" ? appealLettersRes.data : [],
    appealLettersUnavailable: appealLettersRes.kind !== "ok",
  };

  const status = encounter.status as EncounterStatus;
  const statusClass =
    status === "pending"
      ? styles.statusBadgePending
      : status === "auditing"
        ? styles.statusBadgeAuditing
        : status === "completed"
          ? styles.statusBadgeCompleted
          : styles.statusBadgeAwaitingReview;

  const claimJson = encounter.claim.parsed
    ? JSON.stringify(encounter.claim.parsed, null, 2)
    : encounter.claim.cptCodesJson;

  return (
    <div className={styles.splitScreen}>
      {/* ---- Left pane: clinical note + claim --------------------- */}
      <section
        className={`${styles.pane} ${styles.paneNote}`}
        aria-label="Clinical note"
      >
        <header className={styles.paneHeader}>
          <h2>
            Encounter {encounter.id}
            <span className={`${styles.statusBadge} ${statusClass}`}>
              {ENCOUNTER_STATUSES.includes(status) ? status : encounter.status}
            </span>
          </h2>
          <dl className={styles.encounterKv}>
            <dt>Date of service</dt>
            <dd>{formatDate(encounter.dateOfService)}</dd>
            <dt>Specialty</dt>
            <dd>{encounter.specialty}</dd>
            <dt>Payer</dt>
            <dd>{encounter.claim.payer}</dd>
            <dt>Provider</dt>
            <dd>
              {encounter.claim.providerName} (NPI {encounter.claim.providerNpi})
            </dd>
            <dt>Patient hash</dt>
            <dd>
              <code>{encounter.patientHash.slice(0, 16)}…</code>
            </dd>
          </dl>
        </header>

        <h3 style={{ margin: "0 0 0.5rem 0", fontSize: "0.85rem", textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--muted, #94a3b8)" }}>
          Clinical narrative
        </h3>
        <ClinicalNote html={noteHtml} evidenceToCard={evidenceToCard} />

        <div className={styles.claimSection}>
          <h3>Billed claim</h3>
          <dl className={styles.claimKv}>
            <dt>Total billed</dt>
            <dd>{formatCents(encounter.claim.billedCents, { signed: false })}</dd>
            <dt>Line items</dt>
            <dd>
              {encounter.claim.parsed
                ? encounter.claim.parsed.lines
                    .map((line) => `${line.code}${line.modifier ? `-${line.modifier}` : ""}`)
                    .join(", ")
                : "(malformed claim JSON)"}
            </dd>
          </dl>
          <pre className={styles.claimJson}>{claimJson}</pre>
        </div>
      </section>

      {/* ---- Right pane: AI findings cards ------------------------ */}
      <section
        className={`${styles.pane} ${styles.paneFindings}`}
        aria-label="AI findings"
      >
        <header className={styles.paneHeader}>
          <h2>AI findings</h2>
          <p className={styles.paneCount}>
            {encounter.findings.length} finding
            {encounter.findings.length === 1 ? "" : "s"}
          </p>
        </header>

        <AuditRunControl
          encounterId={encounter.id}
          initialStatus={encounter.auditDispatch?.status ?? null}
          canWrite={hasCapability(tenant.role, "write")}
        />

        {encounter.findings.length === 0 ? (
          <p className={styles.emptyState}>
            {status === "completed"
              ? "No findings for this encounter. The auditor ran clean."
              : "No findings are available because this audit has not completed."}
          </p>
        ) : (
          encounter.findings.map((f) => (
            <FindingCard
              key={f.id}
              findingId={f.id}
              encounterId={encounter.id}
              category={isFindingCategory(f.category) ? f.category : "other"}
              billingRuleReference={f.billingRuleReference}
              currentCode={f.currentCode}
              suggestedCode={f.suggestedCode}
              evidenceQuote={f.evidenceQuote}
              estFinancialImpactCents={f.estFinancialImpactCents}
              status={f.status}
              dismissReason={isDismissReason(f.dismissReason) ? f.dismissReason : null}
              dismissText={f.dismissText}
            />
          ))
        )}

        <DeepAuditPanel
          encounterId={encounter.id}
          denialRisk={deepAudit.denialRisk}
          denialRiskUnavailable={deepAudit.denialRiskUnavailable}
          appealLetter={deepAudit.appealLetter}
          appealLetterUnavailable={deepAudit.appealLetterUnavailable}
          appealLetters={deepAudit.appealLetters}
          appealLettersUnavailable={deepAudit.appealLettersUnavailable}
          fastapiEncounterUrl={fastapiEncounterUrl(encounter.id)}
          fastapiOrigin={FASTAPI_ORIGIN}
        />
      </section>
    </div>
  );
}
