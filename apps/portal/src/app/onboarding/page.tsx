// /onboarding — first-run wizard for new clinics (5 steps).
//
// This is the public-facing entry point for a new clinic after they
// have signed the HIA DPA. It walks the clinic through the minimum
// setup needed before they can run their first pre-submit audit:
//
//   1. Create account        — sign-in email + clinic name
//   2. HIA paperwork         — confirm DPA on file, custodian + privacy officer
//   3. Import pilot data     — 837P / CSV / SFTP / skip
//   4. Run first audit       — triggers a real audit on the imported data
//   5. Accept first finding  — biller reviews and accepts/edits/dismisses
//
// Each step has:
//   - a progress indicator at the top (filled circles for done,
//     blue for active, gray for pending)
//   - a "Skip for now" link at the bottom (skips to the next step
//     but does NOT mark the step done; the user can return later
//     from /portal/onboarding)
//
// Server-rendered shell. The wizard itself is a Client Component
// (`<OnboardingFlow>`) that keeps step state in memory + localStorage.
//
// Route gating: this page is in the public set (no auth required),
// matching the other /onboarding* entry points. Once the clinic
// completes step 1, the rest of the steps assume they are signed in;
// if the wizard detects no session, it routes the user to
// /login?callbackUrl=/onboarding.

import type { Metadata } from "next";
import OnboardingFlow from "./OnboardingFlow";
import styles from "./onboarding.module.css";

export const metadata: Metadata = {
  title: "Get started — Zorva",
  description:
    "Five-step onboarding for new Zorva clinics. Set up your account, " +
    "HIA paperwork, pilot data, and run your first audit in under 10 minutes.",
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default function NewClinicOnboardingPage() {
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.badge}>New clinic</div>
        <h1>Set up Zorva in 5 steps</h1>
        <p className={styles.lede}>
          We&apos;ll walk you through the minimum setup so you can run
          your first pre-submit audit. Most clinics finish in under 10
          minutes. You can skip any step and come back later.
        </p>
        <OnboardingFlow />
      </div>
    </div>
  );
}
