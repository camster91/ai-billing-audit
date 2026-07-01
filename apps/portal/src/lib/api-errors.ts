// Shared error handling for portal API routes.
//
// Centralises the "log full error server-side, return sanitized error
// client-side" pattern. P11 bug-sweep finding: 8+ portal route
// handlers (leads, billing/*, settings/*, onboarding/*, findings/*,
// audit/*) were returning the raw exception message in the 500
// response body. DB error messages can include connection strings,
// schema details, table/column names, and Prisma stack traces — all
// of which are useful to an attacker probing for SQLi or
// information-disclosure. The fix:
//
//   - Server-side: full error logged at ERROR level with the route
//     name + a generated requestId so support can correlate.
//   - Client-side: only `{ error: "internal_error", requestId }` is
//     returned. The requestId is shown to the user so support can
//     find the matching log line.
//
// Use it as a drop-in for the existing `catch (e) { ... return 500 }
// pattern:
//
//   catch (e) {
//     return internalErrorResponse(request, e, "/api/leads");
//   }
//
// If the route handler does not have a `Request` available, pass
// `null` and we still generate a requestId; the route name is used as
// the only correlation key.

import { randomUUID } from "node:crypto";
import { NextResponse } from "next/server";

export interface InternalErrorOptions {
  /** Override the auto-generated requestId. Useful when the route
   *  already minted one earlier (e.g. for the request log line). */
  requestId?: string;
  /** Optional human-readable hint for the operator (NEVER shown to
   *  the client). E.g. "while looking up Stripe subscription". */
  hint?: string;
}

export function internalErrorResponse(
  request: Request | null,
  error: unknown,
  route: string,
  opts: InternalErrorOptions = {},
): NextResponse {
  const requestId = opts.requestId ?? randomUUID();
  const message = error instanceof Error ? error.message : String(error);
  // Server-side: full context for support correlation.
  // eslint-disable-next-line no-console
  console.error(
    `[${route}] ${opts.hint ?? "internal_error"} requestId=${requestId} message=${message}`,
    error instanceof Error ? error.stack : undefined,
  );
  // Client-side: sanitized. Never include `message`.
  const body: { error: string; requestId: string } = {
    error: "internal_error",
    requestId,
  };
  // Add a `WWW-Authenticate`-style header so support can find the
  // requestId without re-parsing the body. Convention borrowed from
  // RFC 7807 / Problem Details for HTTP APIs.
  void request; // intentionally unused — kept in the signature for
  // future request-id extraction from a header if the platform adds
  // one (e.g. x-vercel-id, x-request-id from Traefik).
  return NextResponse.json(body, {
    status: 500,
    headers: { "x-request-id": requestId },
  });
}