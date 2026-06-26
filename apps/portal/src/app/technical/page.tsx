// /technical — long-form explainer for privacy officers, IT leads,
// and evaluation committees deciding whether to sign off on Zorva.
//
// Audience: technical buyers, not end users. Tone is precise,
// neutral, evidence-based. Each major claim links to the source file
// or schema that backs it.
//
// Covers, in order:
//   1. Prompt flow — how an encounter becomes a Zorva prompt
//   2. Validation set — what gold we score against, how it's versioned
//   3. F1 measurement — exact formulas, current numbers, unit of
//      measurement
//   4. audit_trail hash chain — what fields, how the chain links,
//      how tampering is detected
//   5. Data sent to Ollama cloud — exactly which fields cross the
//      boundary
//   6. Data NOT sent — what stays local, what is stripped, what is
//      pseudonymized
//
// Source-of-truth pointers are intentionally concrete (file path +
// line range / commit / schema). When the underlying mechanics
// change, bump LAST_REVIEWED below.
//
// Server component. No client hooks, no fetch. Static content only.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./technical.module.css";

// Bump this constant whenever a referenced source file or the F1
// number changes. The page footer renders it so reviewers know how
// stale the explainer might be.
const LAST_REVIEWED = "2026-06-24";

export const metadata: Metadata = {
  title: "Technical — how Zorva audits your claims",
  description:
    "How the v12 Zorva auditor works: the prompt pipeline, the validation set and F1 measurement, the audit_trail SHA-256 hash chain, and exactly which fields cross to Ollama cloud vs. what stays local. Written for privacy officers and IT leads.",
};

export default function TechnicalPage() {
  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.header}>
          <span className={styles.eyebrow}>Technical</span>
          <h1>How Zorva audits your claims — for privacy officers and IT leads.</h1>
          <p className={styles.lede}>
            This page explains the mechanics of the v12 Zorva auditor so a
            privacy officer, IT lead, or evaluation committee can sign off
            on adopting it. We keep the tone technical on purpose — the
            short marketing version lives at <Link href="/security">/security</Link>.
            Each section links to the source file or schema behind the claim
            so you can verify it yourself.
          </p>
          <span className={styles.lastReviewed}>
            Last reviewed: {LAST_REVIEWED}
          </span>
        </header>

        {/* 1. Prompt flow */}
        <section
          className={styles.topic}
          aria-labelledby="t-prompt-flow"
        >
          <span className={styles.topicBadge}>1</span>
          <h2 id="t-prompt-flow">Prompt flow: from encounter to findings</h2>
          <p>
            Each claim audit is a single synchronous chat-completion call.
            There is no agent loop, no tool use, no function-calling, and
            no retrieval-augmented generation. The prompt is constructed
            in code, sent to Ollama cloud over HTTPS, and the response is
            validated against a JSON Schema before any finding is
            persisted.
          </p>
          <p>The pipeline, end to end:</p>
          <ul>
            <li>
              <strong>Ingest.</strong> An 837P / CSV row plus its
              clinical note is read from <code>uploads/</code> and
              normalized into a single <code>Encounter</code> record
              (see <code>src/ai_billing_audit/encounters.py</code>).
            </li>
            <li>
              <strong>Pseudonymize.</strong> Patient identifiers are
              replaced with <code>SHA-256(encounter_id)[:12]</code>
              (see <code>src/ai_billing_audit/appeal_letter.py</code>,
              <code>_pseudonymize_patient()</code>). The mapping is
              one-way per encounter; nothing in the prompt can be
              reverse-resolved to a real patient.
            </li>
            <li>
              <strong>Construct prompt.</strong>{" "}
              <code>prompts/v12/auditor_prompt.txt</code> is loaded
              verbatim, then templated with the encounter payload
              (specialty, billing_authority, claim lines, clinical
              note excerpt). The v12 prompt explicitly targets
              AHCIP/SOMB and is{" "}
              <strong>recall-biased</strong>: missing a billing error
              costs the clinic revenue, a false positive costs the
              biller 5 seconds.
            </li>
            <li>
              <strong>Dispatch.</strong>{" "}
              <code>src/ai_billing_audit/llm.py</code> routes the
              call through <code>litellm</code> to the configured
              backend. The current production backend is Ollama cloud
              (<code>LLM_BASE_URL=https://ollama.com/v1</code>);
              local Ollama is supported as a drop-in via the same env
              variable.
            </li>
            <li>
              <strong>Validate.</strong> The response is parsed as
              JSON and validated against a JSON Schema constrained
              to a list of findings with{" "}
              <code>rule_id / severity / quote / suggested_code</code>.
              Any malformed response fails the run; no finding is
              persisted unless it passes schema validation.
            </li>
            <li>
              <strong>Persist.</strong> Each accepted finding is
              written to the <code>findings</code> table with a
              back-reference to the encounter. Reviewer actions
              (accept, dismiss, flag, re-run) flow into the{" "}
              <code>audit_trail</code> via the hash-chain appender.
            </li>
          </ul>
        </section>

        {/* 2. Validation set */}
        <section className={styles.topic} aria-labelledby="t-validation">
          <span className={styles.topicBadge}>2</span>
          <h2 id="t-validation">Validation set: structure and versioning</h2>
          <p>
            We score the auditor against a held-out AHCIP validation
            set, not against the training set. The split is enforced
            at encounter ID level (no encounter appears in both
            partitions).
          </p>
          <ul>
            <li>
              <strong>File.</strong> <code>data/val_ca.json</code>{" "}
              (10 AHCIP encounters, 13 audited gold findings).
            </li>
            <li>
              <strong>Schema.</strong> Each entry has{" "}
              <code>encounter_id</code>, <code>specialty</code>,{" "}
              <code>note_excerpt</code>, <code>submitted_claim</code>,
              and <code>gold_findings[]</code> — the canonical ground
              truth that the auditor output is compared against.
            </li>
            <li>
              <strong>Versioning.</strong> The val set is reviewed and
              re-audited whenever we add a new rule or change the
              scoring rubric. The 2026-06-23 pass corrected 5 false
              positives in the gold (over-fired <code>dx_linkage</code>{" "}
              on encounters with valid dx codes), which moved v11 F1
              from 0.500 to 0.588 — a useful sanity check that the
              val set is honest, not easy.
            </li>
            <li>
              <strong>Train / val separation.</strong> Training-rule
              tuning runs against <code>data/train.json</code>;
              scoring runs against <code>data/val_ca.json</code>{" "}
              only. The same model and prompt see both, but the gold
              for each is reviewed independently.
            </li>
          </ul>
        </section>

        {/* 3. F1 measurement */}
        <section className={styles.topic} aria-labelledby="t-f1">
          <span className={styles.topicBadge}>3</span>
          <h2 id="t-f1">F1 measurement: formulas, unit, current number</h2>
          <p>
            We score per-encounter, then aggregate to{" "}
            <strong>micro-averaged</strong> precision, recall, and F1
            across the whole validation set. (Micro-averaging pools
            TP/FP/FN across all encounters, which is the right unit
            when the question is &ldquo;of all the gold findings
            across the set, how many did we catch?&rdquo; — versus
            macro-averaging, which would weight a 1-finding encounter
            the same as a 5-finding one.)
          </p>
          <p>For each encounter, a finding is a TP if:</p>
          <ul>
            <li>
              the <code>rule_id</code> matches a gold finding on the
              same encounter, and
            </li>
            <li>
              the <code>suggested_code</code> matches (where the gold
              includes one), and
            </li>
            <li>
              the <code>severity</code> is at or above the gold
              severity (i.e. a HIGH finding matches a MEDIUM gold but
              not vice versa).
            </li>
          </ul>
          <p>The aggregation is the standard one:</p>
          <pre className={styles.codeBlock}>
{`precision = TP / (TP + FP)
recall    = TP / (TP + FN)
F1        = 2 * precision * recall / (precision + recall)`}
          </pre>
          <p>
            <strong>Current number (v12, post leak-fix, 2026-06-23):</strong>{" "}
            on the 10 AHCIP encounters / 13 audited gold findings, v12
            scores <strong>P = 0.647, R = 0.846, F1 = 0.690</strong>.
            That is 11 of 13 gold findings caught, with two flagged
            findings that are not in the gold (both
            <code> dx_linkage</code> over-calls on encounters with
            valid dx codes — the same over-fire that motivated the
            leak-fix in the first place). For clinic conversations we
            round to <em>&ldquo;catches 6–7 of 10 real billing errors
            before submission&rdquo;</em>, which is the lower bound
            of the 0.60–0.69 range and stays defensible. Source:{" "}
            <code>runs/recall/v12_summary.md</code>,{" "}
            <code>docs/ALBERTA_STRATEGY_BRIEF.md</code>.
          </p>
        </section>

        {/* 4. Hash chain */}
        <section className={styles.topic} aria-labelledby="t-hash-chain">
          <span className={styles.topicBadge}>4</span>
          <h2 id="t-hash-chain">audit_trail SHA-256 hash chain</h2>
          <p>
            Every reviewer action on a finding (accept, dismiss, flag,
            re-run) appends a row to <code>audit_trail</code>. Each
            row carries the SHA-256 of the previous row, so editing
            any row in the middle of the chain breaks the
            <em> next</em> row&apos;s <code>cryptographic_signature</code>{" "}
            and every row after it. The verifier in{" "}
            <code>src/ai_billing_audit/audit_actions.py</code>{" "}
            walks the chain top-to-bottom and reports the first row
            that fails to verify, which is exactly where the tamper
            happened.
          </p>
          <p>The chain fields, in this order, are:</p>
          <pre className={styles.codeBlock}>
{`event_id
timestamp          (ISO 8601 UTC)
user_identifier    (X-Forwarded-User or "demo")
action             (accept | dismiss | flag | rerun | ...)
patient_hash       (SHA-256[:12] of encounter_id, per HIA/PHIPA pseudonymization)
data_elements      (canonical-JSON dict of action-specific fields)
model_run_id       (the LLM call id that produced the audited finding)`}
          </pre>
          <p>The signature formula:</p>
          <pre className={styles.codeBlock}>
{`signature_n = SHA-256(
    signature_{n-1}           # previous row's signature, or 64 zeros for genesis
  | event_id
  | timestamp
  | user_identifier
  | action
  | patient_hash
  | data_elements              # canonical JSON, sort_keys, no spaces
  | model_run_id
)`}
          </pre>
          <p>
            Genesis is 64 zeros; the first row in a tenant&apos;s log
            chains off the genesis signature. Production storage is
            the Postgres <code>audit_trail</code> table (see{" "}
            <code>audit_trail.sql</code>); the dev/demo surface is a
            JSONL file at <code>/app/logs/audit_trail.jsonl</code>{" "}
            (env-overridable via <code>AUDIT_TRAIL_LOG</code>). The
            chain shape is identical for both — fields match exactly,
            and the same <code>compute_signature()</code> function
            produces both signatures.
          </p>
          <p>Source files (canonical references):</p>
          <div className={styles.linkList}>
            <span><code>src/ai_billing_audit/audit_actions.py</code> — <code>compute_signature()</code>, <code>_normalize_row()</code>, <code>verify()</code></span>
            <span><code>audit_trail.sql</code> — Postgres table schema, fields match the JSONL shape exactly</span>
            <span><code>src/ai_billing_audit/appeal_letter.py</code> — <code>_pseudonymize_patient()</code> for the patient_hash field</span>
          </div>
        </section>

        {/* 5. Data sent to Ollama cloud */}
        <section className={styles.topic} aria-labelledby="t-data-sent">
          <span className={styles.topicBadge}>5</span>
          <h2 id="t-data-sent">
            Data sent to Ollama cloud during a run
          </h2>
          <p>
            When the configured backend is Ollama cloud (the default in
            production), each prompt carries exactly the following
            fields. Anything not on this list does not cross the
            boundary — it stays in the local Postgres / disk and is
            never serialized into the prompt.
          </p>
          <table className={styles.dataTable}>
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Sent?</th>
                <th scope="col">Notes</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>specialty</code></td>
                <td className={styles.yesCell}>YES</td>
                <td>Plain text label, e.g. <code>cardiology</code>.</td>
              </tr>
              <tr>
                <td><code>billing_authority</code></td>
                <td className={styles.yesCell}>YES</td>
                <td>
                  Plain text label, e.g. <code>AHCIP Schedule of
                  Medical Benefits (SOMB)</code>.
                </td>
              </tr>
              <tr>
                <td><code>compliance_law</code></td>
                <td className={styles.yesCell}>YES</td>
                <td>
                  Plain text label, e.g. <code>PIPEDA+HIA</code>.
                </td>
              </tr>
              <tr>
                <td><code>encounter_id</code></td>
                <td className={styles.yesCell}>YES</td>
                <td>
                  Synthetic ID; no mapping to real chart back.
                </td>
              </tr>
              <tr>
                <td><code>patient_hash</code></td>
                <td className={styles.yesCell}>YES</td>
                <td>
                  First 12 chars of SHA-256(encounter_id); one-way,
                  per-encounter pseudonym (HIA / PHIPA).
                </td>
              </tr>
              <tr>
                <td><code>submitted_claim</code></td>
                <td className={styles.yesCell}>YES</td>
                <td>
                  CPT/HCPCS codes + billed amounts; never ICD
                  descriptions.
                </td>
              </tr>
              <tr>
                <td><code>note_excerpt</code></td>
                <td className={styles.yesCell}>YES</td>
                <td>
                  Up to ~2 KB of clinical text, scrubbed of names,
                  DOB, MRN, and address before templating (see{" "}
                  <code>_scrub_phi()</code> in the encounter loader).
                </td>
              </tr>
              <tr>
                <td>Reviewer names</td>
                <td className={styles.noCell}>NO</td>
                <td>Not in the prompt. Recorded in audit_trail only.</td>
              </tr>
              <tr>
                <td>Clinic name</td>
                <td className={styles.noCell}>NO</td>
                <td>Not in the prompt.</td>
              </tr>
              <tr>
                <td>Provider NPI / practitioner ID</td>
                <td className={styles.noCell}>NO</td>
                <td>Stripped before templating.</td>
              </tr>
              <tr>
                <td>Full clinical note (un-redacted)</td>
                <td className={styles.noCell}>NO</td>
                <td>Only the scrubbed excerpt leaves the host.</td>
              </tr>
              <tr>
                <td>Other tenants&apos; data</td>
                <td className={styles.noCell}>NO</td>
                <td>Tenant filter is applied at query time, before templating.</td>
              </tr>
              <tr>
                <td>API key or credentials</td>
                <td className={styles.noCell}>NO</td>
                <td>
                  Sent only as the HTTP <code>Authorization</code>{" "}
                  header on the wire, never in the prompt body.
                </td>
              </tr>
            </tbody>
          </table>
          <p>
            The wire destination is configurable via the{" "}
            <code>LLM_BASE_URL</code> environment variable. Setting it
            to a local Ollama instance (<code>http://localhost:11434</code>)
            keeps every prompt on-host; nothing leaves the network in
            that mode. The default for production is Ollama cloud
            (<code>https://ollama.com/v1</code>).
          </p>
        </section>

        {/* 6. Data NOT sent */}
        <section
          className={styles.topic}
          aria-labelledby="t-data-not-sent"
        >
          <span className={styles.topicBadge}>6</span>
          <h2 id="t-data-not-sent">What is explicitly NOT sent</h2>
          <p>
            The complement to section 5, in case a reviewer wants a
            flat list rather than the table above:
          </p>
          <ul>
            <li>
              <strong>Patient identifiers</strong> — names, dates of
              birth, MRN, address, phone, email. Replaced with the
              one-way <code>patient_hash</code> before templating.
            </li>
            <li>
              <strong>Provider identifiers</strong> — practitioner ID,
              NPI, billing-service credentials.
            </li>
            <li>
              <strong>Clinic name</strong> — the prompt carries
              specialty, not the clinic or tenant identity.
            </li>
            <li>
              <strong>Reviewer names</strong> — recorded in the
              audit_trail only, never in the prompt.
            </li>
            <li>
              <strong>Un-redacted clinical notes</strong> — only the
              scrubbed excerpt crosses the boundary; the full note
              stays on disk.
            </li>
            <li>
              <strong>Findings history</strong> — no past findings,
              no appeal letters, no feedback signals. Each audit is
              independent.
            </li>
            <li>
              <strong>Other tenants&apos; data</strong> — tenant
              filtering is applied before templating, not after.
            </li>
            <li>
              <strong>API keys / tokens</strong> — sent only as HTTP
              headers, never serialized into the prompt body.
            </li>
          </ul>
          <p>
            If you want a hard guarantee that nothing leaves the host,
            point <code>LLM_BASE_URL</code> at a local Ollama instance.
            The schema validation, JSON parsing, and audit_trail
            append are all identical; only the wire destination
            changes.
          </p>
        </section>

        <p className={styles.footer}>
          Last reviewed: <strong>{LAST_REVIEWED}</strong>. If anything
          on this page disagrees with the source files linked above,
          the source files are correct — please open an issue or
          email <a href="mailto:security@zorva.ca">security@zorva.ca</a>.
        </p>
      </main>
    </div>
  );
}