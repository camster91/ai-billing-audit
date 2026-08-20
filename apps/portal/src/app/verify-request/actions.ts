"use server";

// Server action for the resend button on /verify-request (issue #47).
// Re-issues the magic link for the same email and `from` URL. The
// actual sign-in is delegated to NextAuth's signIn() so the same
// rate-limit / dev-mock / Resend-key paths apply.
//
// Throws on hard failure (e.g. misconfigured AUTH_RESEND_KEY in
// production) so the client button can show the error. Soft
// outcomes (already-sent, throttled) are returned as a normal
// resolution — the client doesn't need to distinguish them from
// a successful resend for privacy reasons.

import { signIn } from "@/auth";

export interface ResendInput {
  email: string;
  from: string;
}

export async function resendMagicLink(input: ResendInput): Promise<{ ok: true }> {
  const email = String(input.email ?? "").trim().toLowerCase();
  if (!email) {
    throw new Error("Email is required to resend a sign-in link.");
  }
  // Same allow-list as /login. Anything else is rejected.
  const safeFrom =
    input.from && input.from.startsWith("/") && !input.from.startsWith("//")
      ? input.from
      : "/dashboard";

  // signIn() throws NEXT_REDIRECT to /verify-request on success —
  // we don't want to follow that redirect because the user is
  // already on /verify-request. We use redirect: false to suppress
  // it and swallow the throw. signIn() is the framework's "issue a
  // magic link" primitive; whether it navigates is orthogonal.
  try {
    await signIn("resend", { email, redirectTo: safeFrom, redirect: false });
  } catch (e) {
    // NextAuth may still throw a NEXT_REDIRECT-style error even
    // with redirect: false; treat anything that doesn't carry a
    // real error message as success.
    if (e instanceof Error && /NEXT_REDIRECT/.test(e.message ?? "")) {
      return { ok: true };
    }
    // Re-throw real errors so the client can show them.
    if (e instanceof Error && e.message && e.message !== "NEXT_REDIRECT") {
      throw e;
    }
  }
  return { ok: true };
}
