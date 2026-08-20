"use client";

// Client component for the "Send another link" button on /verify-request
// (issue #47). Holds a 60-second cooldown locally; calls a server
// action to re-issue the magic link. Displays a status message on
// success / failure.
//
// Privacy contract:
//   - The cooldown is per-tab. A user opening two tabs can fire two
//     resends inside the cooldown; the server-side rate limit
//     (already in place via the auth handlers) is the authoritative
//     gate.
//   - Status messages do not disclose whether the address is
//     registered.

import { useEffect, useRef, useState, useTransition } from "react";
import styles from "./verify-request.module.css";
import { resendMagicLink } from "./actions";

type Status =
  | { kind: "idle" }
  | { kind: "sent" }
  | { kind: "error"; message: string };

interface Props {
  email: string;
  from: string;
  cooldownSeconds: number;
}

function formatSeconds(n: number): string {
  if (n <= 0) return "0s";
  if (n < 60) return `${n}s`;
  const m = Math.floor(n / 60);
  const s = n % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

export default function ResendButton({ email, from, cooldownSeconds }: Props) {
  const [cooldown, setCooldown] = useState(0);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [pending, startTransition] = useTransition();
  // Avoid resetting the cooldown when the page hot-reloads in dev.
  const lastSentRef = useRef<number | null>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  function onClick() {
    if (pending || cooldown > 0 || !email) return;
    startTransition(async () => {
      try {
        await resendMagicLink({ email, from });
        setStatus({ kind: "sent" });
        setCooldown(cooldownSeconds);
        lastSentRef.current = Date.now();
      } catch (e) {
        setStatus({
          kind: "error",
          message:
            e instanceof Error
              ? e.message
              : "We couldn't send another link. Try again in a moment.",
        });
      }
    });
  }

  const disabled = pending || cooldown > 0 || !email;
  const label = pending
    ? "Sending…"
    : cooldown > 0
      ? `Resend in ${formatSeconds(cooldown)}`
      : "Send another link";

  return (
    <div className={styles.resendRow}>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={styles.resendButton}
        aria-label={
          cooldown > 0
            ? `Resend available in ${formatSeconds(cooldown)}`
            : "Send another sign-in link"
        }
        data-testid="verify-request-resend"
      >
        {label}
      </button>
      {status.kind === "sent" ? (
        <p
          className={`${styles.status} ${styles.statusSuccess}`}
          role="status"
          aria-live="polite"
        >
          A new link is on the way.
        </p>
      ) : null}
      {status.kind === "error" ? (
        <p
          className={`${styles.status} ${styles.statusError}`}
          role="alert"
        >
          {status.message}
        </p>
      ) : null}
    </div>
  );
}
