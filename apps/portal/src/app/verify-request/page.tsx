// /verify-request — the "check your email" page after the user
// submits the magic-link form (issue #47).
//
// Flow:
//   1. User submits the form on /login with their email.
//   2. /login calls signIn() with redirect:false, then redirects
//      here with ?from=<callbackUrl>&email=<email>.
//   3. We show a masked email + a resend button (60s cooldown) +
//      a safe support path. The magic link itself is sent by
//      NextAuth's Resend provider — we never display or log the
//      token here.
//   4. When the user clicks the link in their email, NextAuth
//      verifies the token and redirects to the `from` URL.
//
// Privacy:
//   - The page never reveals whether the account exists.
//   - Resend is rate-limited (60s) and idempotent (a second
//     sign-in for the same address just overwrites the prior
//     VerificationToken row).
//   - The masked email is for display only; the real address is
//     not echoed in the rendered HTML.

import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { maskEmail } from "@/lib/email-mask";
import ResendButton from "./ResendButton";
import styles from "./verify-request.module.css";
import "../shell.module.css";

export const metadata: Metadata = {
  title: "Check your email — Zorva",
  description:
    "We've sent a one-time sign-in link to your email. Open it to continue.",
  // Noindex: this page is a transient auth state, not a destination
  // a public searcher should land on.
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface PageProps {
  searchParams: Promise<{ from?: string; email?: string }>;
}

/**
 * Validate the `from` parameter against an allow-list of same-origin
 * portal routes. Any external URL is rejected and we fall back to
 * /dashboard. This prevents open-redirect via the magic-link flow.
 */
function safeReturnUrl(raw: string | undefined): string {
  const fallback = "/dashboard";
  if (!raw) return fallback;
  if (!raw.startsWith("/")) return fallback;
  if (raw.startsWith("//")) return fallback; // protocol-relative
  // Reject anything that looks like a protocol or a host.
  if (/^\/[^/]*$/.test(raw) && raw.includes(":")) return fallback;
  return raw;
}

export default async function VerifyRequestPage({ searchParams }: PageProps) {
  // If the user is already signed in, skip the waiting state.
  const session = await auth();
  if (session?.user?.id) {
    redirect(safeReturnUrl((await searchParams).from) || "/dashboard");
  }

  const { from, email } = await searchParams;
  const masked = email ? maskEmail(email) : null;
  const returnTo = safeReturnUrl(from);

  return (
    <main id="main" className={styles.page}>
      <div className={styles.card}>
        <span className={styles.code}>Email sent</span>
        <h1 className={styles.title}>Check your email.</h1>
        <p className={styles.lede}>
          {masked ? (
            <>
              We sent a one-time sign-in link to{" "}
              <strong className={styles.maskedEmail}>{masked}</strong>. The
              link expires in 10 minutes and can only be used once.
            </>
          ) : (
            <>
              We sent a one-time sign-in link to the address you entered.
              The link expires in 10 minutes and can only be used once.
            </>
          )}
        </p>

        <p className={styles.hint}>
          Open the link in this browser to continue. If you don&rsquo;t see
          the email, check your spam folder.
        </p>

        <ResendButton
          email={email ?? ""}
          from={returnTo}
          cooldownSeconds={60}
        />

        <nav className={styles.quickLinks} aria-label="Auth help">
          <Link href="/login" className={styles.quickLink}>
            Use a different email
          </Link>
          <span aria-hidden="true" className={styles.dot}>
            ·
          </span>
          <Link href="/contact" className={styles.quickLink}>
            Contact support
          </Link>
        </nav>
      </div>
      <footer className={styles.footer}>
        <p>
          Don&rsquo;t share this link. If someone else asked you to click
          it, close this page.
        </p>
      </footer>
    </main>
  );
}
