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
//   3. We store the pending address and callback path in an encrypted,
//      HttpOnly, short-lived cookie, then redirect to /verify-request.
//      The address never enters a URL or client-component props.
//   4. The user clicks the link in their email. NextAuth verifies
//      the token and redirects to the `from` URL.
//
// Auth gate: src/proxy.ts lists "/login" in PUBLIC_PREFIXES, so the
// middleware lets unauthenticated users reach this page. Anyone
// already signed in is bounced to the callbackUrl (or /dashboard).

import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { isRedirectError } from "next/dist/client/components/redirect-error";
import Link from "next/link";
import { signIn, auth } from "@/auth";
import { safeReturnUrl } from "@/lib/email-mask";
import {
  PENDING_MAGIC_LINK_COOKIE,
  PENDING_MAGIC_LINK_MAX_AGE_SECONDS,
  sealPendingMagicLink,
} from "@/lib/pending-magic-link";
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

async function sendMagicLink(formData: FormData): Promise<void> {
  "use server";
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const safeFrom = safeReturnUrl(
    String(formData.get("callbackUrl") ?? "/dashboard"),
  );

  if (!email) {
    redirect("/login?error=missing_email");
  }

  const cookieStore = await cookies();
  cookieStore.set(
    PENDING_MAGIC_LINK_COOKIE,
    sealPendingMagicLink({ email, from: safeFrom, sentAt: Date.now() }),
    {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: PENDING_MAGIC_LINK_MAX_AGE_SECONDS,
    },
  );

  let result: unknown;
  try {
    result = await signIn("resend", {
      email,
      redirectTo: safeFrom,
      redirect: false,
    });
  } catch (error) {
    if (isRedirectError(error)) throw error;
    cookieStore.delete(PENDING_MAGIC_LINK_COOKIE);
    redirect("/auth/error?error=Configuration");
  }

  if (typeof result === "string") {
    const resultUrl = new URL(result, "https://zorva.invalid");
    const authError = resultUrl.searchParams.get("error");
    if (authError) {
      cookieStore.delete(PENDING_MAGIC_LINK_COOKIE);
      redirect(`/auth/error?error=${encodeURIComponent(authError)}`);
    }
  }
  redirect("/verify-request");
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
