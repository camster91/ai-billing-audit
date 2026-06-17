// /portal/onboarding — first-run wizard landing page.
//
// Stripe Checkout sends buyers to `${BASE_URL}/portal/onboarding?session_id=...`
// after a successful subscription payment. This page:
//
//   1. Validates the session_id (rejects with a friendly state if it's
//      missing or unverifiable).
//   2. If the user is signed in, redeems the session server-side so
//      step 1 (clinic profile) can render on the same page render.
//   3. If the user is NOT signed in, shows a "sign in to continue" CTA
//      that bounces them through /login with the session_id preserved
//      as the callback.
//
// The actual multi-step UI is a Client Component (`<OnboardingWizard>`)
// — it walks through the four data steps and posts to the
// /api/onboarding/* routes. The Server Component is a thin shell that
// hands the wizard everything it needs: the verified tenantId, the
// current step, the captured fields, and the user identity.

import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import {
  OnboardingError,
  isDemoSessionId,
  loadWizardState,
  redeemCheckoutSession,
} from "@/lib/onboarding";
import OnboardingWizard from "./OnboardingWizard";
import styles from "./onboarding.module.css";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface PageProps {
  searchParams: Promise<{ session_id?: string; demo?: string }>;
}

export default async function OnboardingPage({ searchParams }: PageProps) {
  const { session_id, demo } = await searchParams;

  // ----- Branch 1: no session_id -----
  if (!session_id) {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <h1>Start here</h1>
          <p>This page expects a <code>?session_id=...</code> query parameter from Stripe Checkout.</p>
          <p><a className={styles.link} href="/pricing">Back to pricing →</a></p>
        </div>
      </div>
    );
  }

  const session = await auth();
  const isDemo = isDemoSessionId(session_id) || demo === "1";

  // ----- Branch 2: anonymous visitor -----
  if (!session?.user?.id) {
    const callback = `/portal/onboarding?session_id=${encodeURIComponent(session_id)}`;
    const signInUrl = `/login?callbackUrl=${encodeURIComponent(callback)}`;
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <div className={styles.badge}>Almost there</div>
          <h1>Sign in to continue</h1>
          <p>
            Your subscription is active. Sign in (or create an account) with the
            same email you used at checkout and we'll finish setting up your
            clinic.
          </p>
          <div className={styles.actions}>
            <a className={styles.btn} href={signInUrl}>Sign in to continue</a>
            <a className={styles.btnGhost} href="/pricing">Back to pricing</a>
          </div>
        </div>
      </div>
    );
  }

  // ----- Branch 3: signed in, redeem (or replay) the session -----
  const userId = session.user.id;

  // Fast path: a previous redemption exists for this user. Skip the
  // Stripe call entirely — we already have a tenant.
  const existing = await prisma.redeemedCheckoutSession.findUnique({
    where: { sessionId: session_id },
    select: { userId: true, tenantId: true },
  });
  let tenantId: string;
  let state = null as Awaited<ReturnType<typeof loadWizardState>> | null;
  let replay: "self" | "other" | null = null;
  let redemptionError: string | null = null;

  if (existing) {
    if (existing.userId !== userId) {
      replay = "other";
    } else {
      replay = "self";
      tenantId = existing.tenantId;
      state = await loadWizardState({
        tenantId,
        sessionId: session_id,
        userId,
      });
    }
  }

  if (!existing || replay === "other") {
    try {
      const result = await redeemCheckoutSession({
        sessionId: session_id,
        userId,
      });
      if (result.alreadyClaimed) {
        replay = "other";
        tenantId = result.tenant.id;
      } else {
        tenantId = result.tenant.id;
        state = await loadWizardState({
          tenantId,
          sessionId: session_id,
          userId,
        });
      }
    } catch (e) {
      if (e instanceof OnboardingError) {
        redemptionError = e.message;
      } else {
        const message = e instanceof Error ? e.message : "unknown error";
        console.error("[/portal/onboarding] redeem error:", message);
        redemptionError =
          "We couldn't verify your checkout session. Please contact support if this persists.";
      }
    }
  }

  if (redemptionError) {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <div className={styles.badge}>Heads up</div>
          <h1>Couldn't verify session</h1>
          <p>{redemptionError}</p>
          <div className={styles.actions}>
            <a className={styles.btnGhost} href="/pricing">Back to pricing</a>
          </div>
        </div>
      </div>
    );
  }

  if (replay === "other") {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <div className={styles.badge}>Already claimed</div>
          <h1>Different account</h1>
          <p>
            This checkout session has already been attached to a different
            account. If that's you, sign out and sign back in with the email
            you used at checkout.
          </p>
          <div className={styles.actions}>
            <a className={styles.btnGhost} href="/api/auth/signout">Sign out</a>
            <a className={styles.link} href="/pricing">Back to pricing</a>
          </div>
        </div>
      </div>
    );
  }

  if (!state || !tenantId!) {
    // Should be unreachable.
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <h1>Something went wrong</h1>
          <p>We couldn't load your onboarding state. Please refresh.</p>
        </div>
      </div>
    );
  }

  // ----- Render the wizard -----
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.badge}>{isDemo ? "Demo session" : "Welcome aboard"}</div>
        <h1>Set up your clinic</h1>
        <p>
          A few quick steps and you'll be ready to run your first audit. We
          save your progress as you go, so you can return any time.
        </p>
        <OnboardingWizard
          initialState={state}
          sessionId={session_id}
        />
      </div>
    </div>
  );
}
