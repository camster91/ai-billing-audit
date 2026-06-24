// /login — magic-link sign-in.
//
// The page is a Server Component. It renders a small form that POSTs
// to a Server Action; the Server Action calls NextAuth's `signIn`
// helper with the Resend provider, which triggers the magic-link
// email (or, in dev mode without AUTH_RESEND_KEY, logs the link to
// the terminal — see src/auth.ts).
//
// NextAuth's `signIn` is documented to throw a NEXT_REDIRECT on
// success (it's the framework's way of navigating to the post-login
// page). Server actions must let that throw — wrapping it in a
// try/catch breaks the redirect. We do server-side validation
// (empty email) by redirecting to /login?error=... BEFORE calling
// signIn, so the catch never has to see the redirect error.
//
// After a successful sign-in, NextAuth redirects to the URL we pass
// in `redirectTo`, defaulting to /dashboard.
//
// Auth gate: src/proxy.ts lists "/login" in PUBLIC_PREFIXES, so the
// middleware lets unauthenticated users reach this page. Anyone
// already signed in is bounced to /dashboard.

import type { Metadata } from "next";
import { redirect } from "next/navigation";
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

async function sendMagicLink(formData: FormData): Promise<void> {
  "use server";
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const callbackUrl = String(formData.get("callbackUrl") ?? "/dashboard");

  if (!email) {
    redirect("/login?error=missing_email");
  }

  // signIn() throws NEXT_REDIRECT on success — do not wrap in try/catch.
  await signIn("resend", {
    email,
    redirectTo: callbackUrl,
  });
}

export default async function LoginPage({ searchParams }: PageProps) {
  const { callbackUrl, error } = await searchParams;
  const session = await auth();

  // If the user is already signed in, skip the form.
  if (session?.user?.id) {
    redirect(callbackUrl || "/dashboard");
  }

  return (
    <main className={styles.loginPage}>
      <div className={styles.loginCard}>
        <h1>Sign in</h1>
        <p>
          We&rsquo;ll email you a one-time link. No password needed.
        </p>

        {error === "missing_email" ? (
          <div role="status" aria-live="polite" className={styles.flash}>Please enter your email address.</div>
        ) : error ? (
          <div role="status" aria-live="polite" className={styles.flash}>
            Couldn&rsquo;t send the link: {error}. Check the email address
            and try again.
          </div>
        ) : null}

        <form action={sendMagicLink}>
          <input type="hidden" name="callbackUrl" value={callbackUrl || "/dashboard"} />
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
    </main>
  );
}
