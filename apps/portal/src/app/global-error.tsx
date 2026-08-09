// Global error boundary for the root layout.
//
// Catches any unhandled error thrown in a server component or
// route handler under the root layout. Renders a friendly fallback
// instead of Next.js's default unthemed error UI.
//
// The portal is dark-only (see layout.tsx color-scheme meta). This
// component uses inline styles to avoid coupling to globals.css
// during an error render — globals.css may not be loaded if the
// error happened during page boot.
//
// P11 bug-sweep fix (2026-07-01): the portal had only not-found.tsx
// and no error.tsx / global-error.tsx. Any thrown error in a Prisma
// round-trip or auth() call would surface as the framework's
// unthemed default error page, which (a) breaks the dark UI and
// (b) makes the error look like the site is broken rather than a
// recoverable incident.

"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface to the browser console + any installed error reporter.
    // We deliberately do NOT send the error anywhere server-side here
    // because the global-error boundary renders BEFORE the root layout,
    // so the server-side logger isn't available.
    console.error("[global-error] caught:", error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          background: "#0b1020",
          color: "#e8eaf6",
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
          margin: 0,
          padding: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            maxWidth: 480,
            padding: "32px 24px",
            textAlign: "center",
          }}
        >
          <h1 style={{ fontSize: 28, margin: "0 0 12px" }}>
            Something went wrong.
          </h1>
          <p style={{ fontSize: 16, lineHeight: 1.5, color: "#a8b2d1" }}>
            We hit an unexpected error loading this page. Your data is
            safe — this is a render issue, not a billing issue.
          </p>
          {error.digest ? (
            <p
              style={{
                fontSize: 12,
                color: "#6b7299",
                fontFamily: "ui-monospace, monospace",
                margin: "16px 0 24px",
              }}
            >
              Error ID: <code>{error.digest}</code>
            </p>
          ) : null}
          <button
            type="button"
            onClick={reset}
            style={{
              background: "#38bdf8",
              color: "#0b1020",
              border: "none",
              borderRadius: 6,
              padding: "10px 20px",
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Try again
          </button>
          <p style={{ fontSize: 14, color: "#a8b2d1", marginTop: 24 }}>
            If this keeps happening, email{" "}
            <a
              href="mailto:support@ashbi.ca"
              style={{ color: "#38bdf8", textDecoration: "underline" }}
            >
              support@ashbi.ca
            </a>{" "}
            with the error ID above.
          </p>
        </div>
      </body>
    </html>
  );
}
