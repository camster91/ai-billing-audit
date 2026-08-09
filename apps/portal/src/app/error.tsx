// Segment-level error boundary for the portal.
//
// Catches errors thrown in any server component under the root
// layout that is NOT already wrapped by a more-specific error.tsx.
// Renders a dark-themed fallback that matches the rest of the
// portal instead of the framework's default unthemed error page.
//
// P11 bug-sweep fix (2026-07-01): the portal had no segment-level
// error boundary. Any thrown error in /dashboard, /encounters, etc.
// would surface as the framework's default error UI, which doesn't
// match the dark marketing palette and looks like the site is broken.

"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[portal error boundary] caught:", error);
  }, [error]);

  return (
    <div
      style={{
        background: "#0d1428",
        border: "1px solid #28324f",
        borderRadius: 8,
        padding: "24px 20px",
        margin: "32px auto",
        maxWidth: 560,
        textAlign: "center",
        color: "#e8eaf6",
      }}
    >
      <h2 style={{ fontSize: 22, margin: "0 0 8px", color: "#f87171" }}>
        Couldn&apos;t load this page
      </h2>
      <p
        style={{
          fontSize: 14,
          lineHeight: 1.5,
          color: "#a8b2d1",
          margin: "0 0 16px",
        }}
      >
        We hit an unexpected error. Your data is safe — this is a
        render issue, not a billing issue. Try again, or head back to
        the dashboard.
      </p>
      {error.digest ? (
        <p
          style={{
            fontSize: 12,
            color: "#6b7299",
            fontFamily: "ui-monospace, monospace",
            margin: "0 0 20px",
          }}
        >
          Error ID: <code>{error.digest}</code>
        </p>
      ) : null}
      <div
        style={{
          display: "flex",
          gap: 12,
          justifyContent: "center",
          flexWrap: "wrap",
        }}
      >
        <button
          type="button"
          onClick={reset}
          style={{
            background: "#38bdf8",
            color: "#0b1020",
            border: "none",
            borderRadius: 6,
            padding: "8px 16px",
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Try again
        </button>
        <a
          href="/dashboard"
          style={{
            background: "transparent",
            color: "#38bdf8",
            border: "1px solid #38bdf8",
            borderRadius: 6,
            padding: "8px 16px",
            fontSize: 14,
            fontWeight: 600,
            textDecoration: "none",
          }}
        >
          Back to dashboard
        </a>
      </div>
    </div>
  );
}
