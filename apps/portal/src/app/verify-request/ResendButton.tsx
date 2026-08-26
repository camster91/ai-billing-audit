"use client";

// Client component for the "Send another link" button on /verify-request
// (issue #47). Mirrors the server-authoritative cooldown while a
// server action re-issues the magic link. Displays a status message
// on success / failure.
//
// Privacy contract:
//   - The encrypted HttpOnly pending-state cookie is the authoritative
//     cooldown gate. This client timer only keeps the button label in sync.
//   - Status messages do not disclose whether the address is
//     registered.

import { useEffect, useState, useTransition } from "react";
import styles from "./verify-request.module.css";
import { resendMagicLink } from "./actions";

type Status =
  | { kind: "idle" }
  | { kind: "sent" }
  | { kind: "error"; message: string };

interface Props {
  enabled: boolean;
  initialCooldownSeconds: number;
}

function formatSeconds(n: number): string {
  if (n <= 0) return "0s";
  if (n < 60) return `${n}s`;
  const m = Math.floor(n / 60);
  const s = n % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

export default function ResendButton({
  enabled,
  initialCooldownSeconds,
}: Props) {
  const [cooldown, setCooldown] = useState(initialCooldownSeconds);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [pending, startTransition] = useTransition();
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  function onClick() {
    if (pending || cooldown > 0 || !enabled) return;
    startTransition(async () => {
      try {
        const result = await resendMagicLink();
        setCooldown(result.retryAfterSeconds);
        if (result.ok) {
          setStatus({ kind: "sent" });
        }
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

  const disabled = pending || cooldown > 0 || !enabled;
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
