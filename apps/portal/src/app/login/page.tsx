// /login — magic-link sign-in.
//
// The page is a Server Component. It renders a small form that POSTs
// to a Server Action; the Server Action calls NextAuth's `signIn`
// helper with the Resend provider, which triggers the magic-link
// email (or, in dev mode without AUTH_RESEND_KEY, logs the link to
// the terminal — see src/auth.ts).
//
// Flow (issue #47 — magic-link lifecycle):
//   1. User submits the form with their email.
//   2. We call signIn(..., { redirect: false }) so NextAuth does
//      NOT navigate us away — we want to land on /verify-request
//      ourselves so the biller sees a durable waiting state.
//   3. We redirect to /verify-request?from=<callbackUrl>&email=<email>
//      with the email passed as a query param. /verify-request
//      masks the address in the rendered HTML so a screenshot or
//      shoulder-surf does not leak it.
//   4. The user clicks the link in their email. NextAuth verifies
//      the token and redirects to the `from` URL.
//
// Auth gate: src/proxy.ts lists "/login" in PUBLIC_PREFIXES, so the
// middleware lets unauthenticated users reach this page. Anyone
// already signed in is bounced to the callbackUrl (or /dashboard).

import type { Metadata } from "next";
import { redirect } from "next/navigation";
import Link from "next/link";
import { signIn, auth } from "@/auth";
import styles from "../shell.module.css";

interface PageProps {
  searchParams: Promise<{ callbackUrl?: string; error?: string }>;
}

export const metadata: Metadata = {
  title: "Sign in — Zorva",
  description:
    "Sign in to Zorva with a magic link to your email. No passwords to remember.",
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * Allow-list the callbackUrl to a same-origin portal path. Any
 * external URL is dropped back to /dashboard. This prevents
 * open-redirect via the magic-link flow.
 */
function safeReturnUrl(raw: string | undefined, fallback = "/dashboard"): string {
  if (!raw) return fallback;
  if (!raw.startsWith("/")) return fallback;
  if (raw.startsWith("//")) return fallback;
  if (/^\/[^/]*$/.test(raw) && raw.includes(":")) return fallback;
  return raw;
}

async function sendMagicLink(formData: FormData): Promise<void> {
  "use server";
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const callbackUrl = String(formData.get("callbackUrl") ?? "/dashboard");
  const safeFrom = safeReturnUrl(callbackUrl);

  if (!email) {
    redirect("/login?error=missing_email");
  }

  // Issue the magic link. redirect: false prevents NextAuth from
  // navigating to its default verify-request page; we redirect
  // ourselves to /verify-request so the biller sees the masked
  // email + resend UI.
  try {
    await signIn("resend", { email, redirectTo: safeFrom, redirect: false });
  } catch {
    // signIn() may still throw NEXT_REDIRECT in some NextAuth
    // versions; ignore and let our own redirect win.
  }
  const params = new URLSearchParams({ from: safeFrom, email });
  redirect(`/verify-request?${params.toString()}`);
}

export default async function LoginPage({ searchParams }: PageProps) {
  const { callbackUrl, error } = await searchParams;
  const session = await auth();
  const safeFrom = safeReturnUrl(callbackUrl);

  // If the user is already signed in, skip the form.
  if (session?.user?.id) {
    redirect(safeFrom);
  }

  return (
    <main id="main" className={styles.loginPage}>
      <div className={styles.loginCard}>
        <h1>Sign in</h1>
        <p>
          We&rsquo;ll email you a one-time link. No password needed.
        </p>

        {error === "missing_email" ? (
          // P11 round-2 (2026-07-01): role="alert" for error conditions.
          // Pre-fix was role="status" which is for advisory messages —
          // errors should be assertive so SR users hear them
          // immediately, not after the next polite-region sweep.
          <div role="alert" className={styles.flash}>Please enter your email address.</div>
        ) : error ? (
          <div role="alert" className={styles.flash}>
            Couldn&rsquo;t send the link: {error}. Check the email address
            and try again.
          </div>
        ) : null}

        <form action={sendMagicLink}>
          <input type="hidden" name="callbackUrl" value={safeFrom} />
          <label className={styles.label} htmlFor="email">Work email</label>
          <input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            placeholder="you@clinic.com"
            className={styles.input}
          />
          <button type="submit" className={styles.button}>
            Send magic link
          </button>
        </form>
      </div>
      <footer className={styles.footer}>
        <div className={styles.footerLinks}>
          <Link href="/">Home</Link>
          <span aria-hidden="true">·</span>
          <Link href="/security">Security</Link>
          <span aria-hidden="true">·</span>
          <Link href="/contact">Contact</Link>
        </div>
        <p>Questions? Email us at hello@ashbi.ca</p>
      </footer>
    </main>
  );
}
