// /how-it-works — public-facing explainer page aimed at clinic administrators.
// Three vertical steps (Connect -> AI audit -> Human review) plus a 90-second
// Loom embed slot and a CTA to /pricing.
//
// Server component. Static-friendly: no client hooks, no fetch.
// Copy targets ~8th-grade reading level — audience is clinic admins, not engineers.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./how-it-works.module.css";

export const metadata: Metadata = {
  title: "How it works — AI billing audit in 3 steps",
  description:
    "Connect your EHR, let the AI audit every claim before it goes out, and have your billing team review what matters. Plain-English walkthrough for clinic administrators.",
};

export default function HowItWorksPage() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>How it works</span>
        <h1>Three steps. Your claims, checked before they go out.</h1>
        <p>
          We sit between your billing system and the payer. Every claim gets
          read by an AI auditor first. Your team reviews what it finds.
          Nothing goes out the door unchecked.
        </p>
        <div className={styles.ctaRow}>
          <Link href="/contact" className={styles.ctaButton}>
            Book a 15-min walkthrough
          </Link>
          <Link href="/pricing" className={styles.ctaSecondary}>
            See pricing
          </Link>
        </div>
      </header>

      <main className={styles.main}>
        <section className={styles.steps} aria-label="The three steps">
          <article className={styles.step}>
            <div className={styles.stepNumber} aria-hidden="true">
              1
            </div>
            <div className={styles.illustration} aria-hidden="true">
              <ConnectIllustration />
            </div>
            <h2>Connect your EHR</h2>
            <p className={styles.stepDesc}>
              We pull claims straight from your billing system. No double
              entry, no copy-paste.
            </p>
            <ul className={styles.bulletList}>
              <li>AdvancedMD — automatic sync</li>
              <li>Athena — automatic sync</li>
              <li>Kareo — pulled over SFTP</li>
              <li>Anything else? Upload a file and we&apos;ll take it from there</li>
            </ul>
          </article>

          <article className={styles.step}>
            <div className={styles.stepNumber} aria-hidden="true">
              2
            </div>
            <div className={styles.illustration} aria-hidden="true">
              <AuditIllustration />
            </div>
            <h2>AI audits every claim pre-bill</h2>
            <p className={styles.stepDesc}>
              Before a claim is sent to the payer, the AI reads the clinical
              note and the code you picked. It flags anything that looks off.
            </p>
            <ul className={styles.bulletList}>
              <li>Under-coded visits — you billed lower than the note supports</li>
              <li>Missed charges — services in the note that never made it on the claim</li>
              <li>Modifier issues — the right CPT paired with the wrong modifier</li>
              <li>NCCI conflicts — two codes that can&apos;t be billed together on the same day</li>
            </ul>
          </article>

          <article className={styles.step}>
            <div className={styles.stepNumber} aria-hidden="true">
              3
            </div>
            <div className={styles.illustration} aria-hidden="true">
              <ReviewIllustration />
            </div>
            <h2>Your billing team reviews</h2>
            <p className={styles.stepDesc}>
              The AI shows its work side-by-side with the claim. Your team
              accepts the good catches and dismisses the false alarms. The AI
              learns from every decision.
            </p>
            <ul className={styles.bulletList}>
              <li>Split-screen view: claim on the left, AI findings on the right</li>
              <li>Accept or dismiss each finding with one click</li>
              <li>Every dismissal teaches the AI what your clinic considers a real flag</li>
            </ul>
          </article>
        </section>

        <section className={styles.demo} aria-label="90-second walkthrough">
          <h2 className={styles.demoHeading}>See it in 90 seconds</h2>
          <p className={styles.demoSub}>
            A short walkthrough of the reviewer screen, from claim in to claim out.
          </p>
          <div className={styles.loomFrame}>
            {/* Embed slot — replace src with the real Loom share URL once the
                walkthrough is recorded. Aspect ratio is 16:9 to match a standard
                Loom recording. */}
            <div className={styles.loomPlaceholder} role="img" aria-label="90-second walkthrough video placeholder">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <circle cx="12" cy="12" r="10" />
                <polygon points="10,8 16,12 10,16" fill="currentColor" stroke="none" />
              </svg>
              <strong>Walkthrough video</strong>
              <span>90-second Loom embed will appear here</span>
            </div>
          </div>
        </section>

        <section className={styles.ctaSection}>
          <h2 className={styles.ctaHeading}>Ready to see what your team is leaving on the table?</h2>
          <p className={styles.ctaSub}>
            Flat monthly pricing. No percentage of revenue. No per-claim fees.
          </p>
          <div>
            <Link href="/pricing" className={styles.ctaButton}>
              See pricing
            </Link>
            <Link href="/login" className={styles.ctaSecondary}>
              Sign in
            </Link>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        Questions? Email us at hello@ai-billing-audit.ashbi.ca
      </footer>
    </div>
  );
}

function ConnectIllustration() {
  return (
    <svg viewBox="0 0 240 120" fill="none" aria-hidden="true">
      <rect x="8" y="20" width="64" height="80" rx="8" fill="#1a2340" stroke="#2563eb" strokeWidth="1.5" />
      <text x="40" y="55" fill="#9aa3bd" fontSize="9" textAnchor="middle" fontFamily="sans-serif">
        EHR
      </text>
      <text x="40" y="70" fill="#2563eb" fontSize="8" textAnchor="middle" fontFamily="sans-serif" fontWeight="600">
        AdvMD
      </text>
      <text x="40" y="84" fill="#9aa3bd" fontSize="8" textAnchor="middle" fontFamily="sans-serif">
        Athena
      </text>
      <line x1="72" y1="60" x2="168" y2="60" stroke="#2563eb" strokeWidth="1.5" strokeDasharray="4 3" />
      <rect x="168" y="40" width="64" height="40" rx="6" fill="#1a2340" stroke="#2dd4bf" strokeWidth="1.5" />
      <text x="200" y="58" fill="#2dd4bf" fontSize="9" textAnchor="middle" fontFamily="sans-serif" fontWeight="600">
        SFTP
      </text>
      <text x="200" y="72" fill="#9aa3bd" fontSize="8" textAnchor="middle" fontFamily="sans-serif">
        Kareo
      </text>
    </svg>
  );
}

function AuditIllustration() {
  return (
    <svg viewBox="0 0 240 120" fill="none" aria-hidden="true">
      <rect x="8" y="14" width="78" height="92" rx="6" fill="#1a2340" stroke="#28324f" strokeWidth="1" />
      <text x="14" y="28" fill="#9aa3bd" fontSize="7" fontFamily="sans-serif">
        Clinical note
      </text>
      <line x1="14" y1="36" x2="80" y2="36" stroke="#28324f" strokeWidth="1" />
      <line x1="14" y1="44" x2="74" y2="44" stroke="#28324f" strokeWidth="1" />
      <line x1="14" y1="52" x2="80" y2="52" stroke="#28324f" strokeWidth="1" />
      <line x1="14" y1="60" x2="68" y2="60" stroke="#28324f" strokeWidth="1" />
      <rect x="14" y="68" width="42" height="6" fill="#f59e0b" opacity="0.4" />
      <line x1="14" y1="82" x2="80" y2="82" stroke="#28324f" strokeWidth="1" />
      <line x1="14" y1="90" x2="72" y2="90" stroke="#28324f" strokeWidth="1" />

      <line x1="86" y1="60" x2="106" y2="60" stroke="#2563eb" strokeWidth="1.5" />

      <rect x="106" y="14" width="60" height="92" rx="6" fill="#1a2340" stroke="#2563eb" strokeWidth="1.5" />
      <text x="136" y="28" fill="#2563eb" fontSize="8" textAnchor="middle" fontFamily="sans-serif" fontWeight="600">
        AI AUDIT
      </text>
      <circle cx="118" cy="44" r="3" fill="#22c55e" />
      <text x="126" y="47" fill="#9aa3bd" fontSize="7" fontFamily="sans-serif">
        under-coding
      </text>
      <circle cx="118" cy="58" r="3" fill="#f59e0b" />
      <text x="126" y="61" fill="#9aa3bd" fontSize="7" fontFamily="sans-serif">
        modifier
      </text>
      <circle cx="118" cy="72" r="3" fill="#f59e0b" />
      <text x="126" y="75" fill="#9aa3bd" fontSize="7" fontFamily="sans-serif">
        NCCI
      </text>
      <circle cx="118" cy="86" r="3" fill="#22c55e" />
      <text x="126" y="89" fill="#9aa3bd" fontSize="7" fontFamily="sans-serif">
        missed chg
      </text>

      <line x1="166" y1="60" x2="186" y2="60" stroke="#2563eb" strokeWidth="1.5" />

      <rect x="186" y="34" width="46" height="52" rx="6" fill="#1a2340" stroke="#28324f" strokeWidth="1" />
      <text x="209" y="48" fill="#9aa3bd" fontSize="7" textAnchor="middle" fontFamily="sans-serif">
        claim
      </text>
      <line x1="194" y1="58" x2="224" y2="58" stroke="#28324f" strokeWidth="1" />
      <line x1="194" y1="66" x2="220" y2="66" stroke="#28324f" strokeWidth="1" />
      <line x1="194" y1="74" x2="224" y2="74" stroke="#28324f" strokeWidth="1" />
    </svg>
  );
}

function ReviewIllustration() {
  return (
    <svg viewBox="0 0 240 120" fill="none" aria-hidden="true">
      <rect x="8" y="14" width="110" height="92" rx="6" fill="#1a2340" stroke="#28324f" strokeWidth="1" />
      <text x="14" y="28" fill="#9aa3bd" fontSize="7" fontFamily="sans-serif">
        Claim detail
      </text>
      <line x1="14" y1="36" x2="110" y2="36" stroke="#28324f" strokeWidth="1" />
      <line x1="14" y1="44" x2="100" y2="44" stroke="#28324f" strokeWidth="1" />
      <line x1="14" y1="52" x2="106" y2="52" stroke="#28324f" strokeWidth="1" />
      <line x1="14" y1="60" x2="92" y2="60" stroke="#28324f" strokeWidth="1" />
      <line x1="14" y1="68" x2="106" y2="68" stroke="#28324f" strokeWidth="1" />
      <line x1="14" y1="76" x2="80" y2="76" stroke="#28324f" strokeWidth="1" />
      <line x1="14" y1="84" x2="100" y2="84" stroke="#28324f" strokeWidth="1" />
      <line x1="14" y1="92" x2="96" y2="92" stroke="#28324f" strokeWidth="1" />

      <line x1="118" y1="60" x2="122" y2="60" stroke="#2563eb" strokeWidth="2" />

      <rect x="122" y="14" width="110" height="92" rx="6" fill="#1a2340" stroke="#2563eb" strokeWidth="1" />
      <text x="128" y="28" fill="#2563eb" fontSize="7" fontFamily="sans-serif" fontWeight="600">
        AI findings
      </text>
      <rect x="128" y="36" width="98" height="18" rx="3" fill="#131a2e" stroke="#f59e0b" strokeWidth="1" />
      <text x="132" y="48" fill="#f59e0b" fontSize="7" fontFamily="sans-serif" fontWeight="600">
        Modifier -25
      </text>
      <text x="178" y="48" fill="#9aa3bd" fontSize="6" fontFamily="sans-serif">
        accept
      </text>
      <text x="208" y="48" fill="#9aa3bd" fontSize="6" fontFamily="sans-serif">
        dismiss
      </text>
      <rect x="128" y="58" width="98" height="18" rx="3" fill="#131a2e" stroke="#22c55e" strokeWidth="1" />
      <text x="132" y="70" fill="#22c55e" fontSize="7" fontFamily="sans-serif" fontWeight="600">
        Under-coded
      </text>
      <text x="178" y="70" fill="#9aa3bd" fontSize="6" fontFamily="sans-serif">
        accept
      </text>
      <text x="208" y="70" fill="#9aa3bd" fontSize="6" fontFamily="sans-serif">
        dismiss
      </text>
      <rect x="128" y="80" width="98" height="18" rx="3" fill="#131a2e" stroke="#28324f" strokeWidth="1" />
      <text x="132" y="92" fill="#9aa3bd" fontSize="7" fontFamily="sans-serif">
        NCCI conflict
      </text>
    </svg>
  );
}
