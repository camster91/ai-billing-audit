"use server";

import { cookies } from "next/headers";
import { isRedirectError } from "next/dist/client/components/redirect-error";
import { signIn } from "@/auth";
import {
  MAGIC_LINK_RESEND_COOLDOWN_SECONDS,
  PENDING_MAGIC_LINK_COOKIE,
  PENDING_MAGIC_LINK_MAX_AGE_SECONDS,
  openPendingMagicLink,
  sealPendingMagicLink,
  secondsUntilMagicLinkResend,
} from "@/lib/pending-magic-link";

export interface ResendResult {
  ok: boolean;
  retryAfterSeconds: number;
}

export async function resendMagicLink(): Promise<ResendResult> {
  const cookieStore = await cookies();
  const pending = openPendingMagicLink(
    cookieStore.get(PENDING_MAGIC_LINK_COOKIE)?.value,
  );
  if (!pending) {
    throw new Error("Start a new sign-in request before resending.");
  }

  const retryAfterSeconds = secondsUntilMagicLinkResend(pending);
  if (retryAfterSeconds > 0) {
    return { ok: false, retryAfterSeconds };
  }

  let result: unknown;
  try {
    result = await signIn("resend", {
      email: pending.email,
      redirectTo: pending.from,
      redirect: false,
    });
  } catch (error) {
    if (isRedirectError(error)) throw error;
    throw new Error("We couldn't send another link. Try again in a moment.");
  }

  if (typeof result === "string") {
    const resultUrl = new URL(result, "https://zorva.invalid");
    if (resultUrl.searchParams.has("error")) {
      throw new Error("We couldn't send another link. Try again in a moment.");
    }
  }

  cookieStore.set(
    PENDING_MAGIC_LINK_COOKIE,
    sealPendingMagicLink({
      ...pending,
      sentAt: Date.now(),
    }),
    {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: PENDING_MAGIC_LINK_MAX_AGE_SECONDS,
    },
  );
  return {
    ok: true,
    retryAfterSeconds: MAGIC_LINK_RESEND_COOLDOWN_SECONDS,
  };
}
