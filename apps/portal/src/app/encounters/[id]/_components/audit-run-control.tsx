"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface AuditRunControlProps {
  encounterId: string;
  initialStatus: string | null;
  canWrite: boolean;
}

const activeStatuses = new Set(["dispatching", "queued", "running"]);

export function AuditRunControl(props: AuditRunControlProps) {
  const router = useRouter();
  const [status, setStatus] = useState(props.initialStatus);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!status || !activeStatuses.has(status)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const response = await fetch(
          `/api/audit/status?encounterId=${encodeURIComponent(props.encounterId)}`,
          { cache: "no-store" },
        );
        const body = (await response.json()) as {
          status?: string;
          error?: string;
        };
        if (stopped) return;
        if (!response.ok) {
          setError("The audit status is temporarily unavailable.");
          timer = setTimeout(poll, 2000);
          return;
        }
        const nextStatus = body.status ?? "queued";
        setStatus(nextStatus);
        setError(null);
        if (nextStatus === "done") {
          router.refresh();
          return;
        }
        if (nextStatus === "failed") {
          setError("The audit did not complete. Please contact support before retrying.");
          return;
        }
        timer = setTimeout(poll, 1000);
      } catch {
        if (!stopped) {
          setError("The audit status is temporarily unavailable.");
          timer = setTimeout(poll, 2000);
        }
      }
    };
    timer = setTimeout(poll, 250);
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [props.encounterId, router, status]);

  async function startAudit() {
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/api/audit/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ encounterId: props.encounterId }),
      });
      const body = (await response.json()) as { error?: string };
      if (!response.ok) {
        setError(
          body.error === "audit_quota_exhausted"
            ? "This clinic has reached its audit quota."
            : "The audit could not be queued. Please try again.",
        );
        return;
      }
      setStatus("queued");
    } catch {
      setError("The audit service is temporarily unavailable.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!props.canWrite) {
    return <p role="status">An auditor or owner can run this audit.</p>;
  }
  if (status === "done") return null;

  return (
    <div style={{ marginBottom: "1rem" }}>
      {status && activeStatuses.has(status) ? (
        <p role="status" aria-live="polite">
          Audit {status === "dispatching" ? "is being queued" : status}…
        </p>
      ) : status === "failed" ? (
        <p role="alert">The audit did not complete. Please contact support before retrying.</p>
      ) : (
        <button type="button" onClick={startAudit} disabled={submitting}>
          {submitting ? "Queueing audit…" : "Run AI audit"}
        </button>
      )}
      {error ? <p role="alert">{error}</p> : null}
    </div>
  );
}
