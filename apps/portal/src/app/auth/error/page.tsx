// /auth/error — NextAuth error destination (issue #47).
//
// NextAuth redirects here when a magic link is expired, used, or
// otherwise invalid (configured via `pages: { error: "/auth/error" }`
// in src/auth.ts).
//
// The `error` query parameter is one of the NextAuth error codes:
//   Verification          — link invalid, expired, or already redeemed
//   AccessDenied          — the signIn callback returned false
//   Configuration         — server-side misconfiguration
//   Default               — anything else
//
// Copy here is enumeration-safe: we never reveal whether the
// email is registered, and we never echo the token. Distinct
// actionable recovery is given per code.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./auth-error.module.css";
import "../../shell.module.css";

export const metadata: Metadata = {
  title: "Sign-in link problem — Zorva",
  description:
    "That sign-in link didn't work. Try sending a new one or contact support.",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type ErrorCode =
  | "Verification"
  | "AccessDenied"
  | "Configuration"
  | "Default"
  | string;

interface PageProps {
  searchParams: Promise<{ error?: ErrorCode }>;
}

interface ErrorCopy {
  title: string;
  body: string;
  /** Recovery CTA label. */
  cta: string;
  /** Whether the copy implies the address is registered. Enumeration-safe required. */
  enumerationSafe: boolean;
}

const ERROR_COPY: Record<string, ErrorCopy> = {
  Verification: {
    title: "That sign-in link is no longer valid.",
    body: "It may be expired, already used, or malformed. Request a fresh one.",
    cta: "Send a new link",
    enumerationSafe: true,
  },
  AccessDenied: {
    title: "We couldn't sign you in.",
    body: "Your account may not be active, or your sign-in was denied by an admin. If you think this is wrong, contact support.",
    cta: "Try again",
    enumerationSafe: true,
  },
  Configuration: {
    title: "Sign-in is temporarily unavailable.",
    body: "Something on our side is misconfigured. Please try again in a few minutes. If the problem persists, contact support.",
    cta: "Try again",
    enumerationSafe: true,
  },
  Default: {
    title: "That sign-in link didn't work.",
    body: "It may be expired, used, or malformed. Send a new one and open it in this browser.",
    cta: "Send a new link",
    enumerationSafe: true,
  },
};

function copyFor(code: ErrorCode | undefined): ErrorCopy {
  if (!code) return ERROR_COPY.Default;
  return ERROR_COPY[code] ?? ERROR_COPY.Default;
}

export default async function AuthErrorPage({ searchParams }: PageProps) {
  const { error } = await searchParams;
  const copy = copyFor(error);

  // The CTA goes back to /login. We deliberately do NOT prefill the
  // email — if the user is on a shared device, the previous email
  // could leak into the next session.
  return (
    <main id="main" className={styles.page}>
      <div className={styles.card} role="alert" aria-live="assertive">
        <span className={styles.code}>Sign-in problem</span>
        <h1 className={styles.title}>{copy.title}</h1>
        <p className={styles.body}>{copy.body}</p>

        <div className={styles.actions}>
          <Link href="/login" className={styles.primary}>
            {copy.cta}
          </Link>
          <Link href="/contact" className={styles.secondary}>
            Contact support
          </Link>
        </div>

        {error && error !== "Default" ? (
          <p className={styles.codeLine}>
            Reference: <code className={styles.codeValue}>{error}</code>
          </p>
        ) : null}
      </div>
      <footer className={styles.footer}>
        <p>
          For your security, sign-in links expire and can only be used
          once. If you didn&rsquo;t request this, you can close this page.
        </p>
      </footer>
    </main>
  );
}
