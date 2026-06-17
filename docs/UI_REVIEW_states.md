# UI review: empty / loading / error / 404 / 500 / maintenance states

**Reviewer.** Default Hermes worker, dispatched via the
`ai-billing-audit` kanban board (task `t_13a3e19a`).

**Scope.** Every user-facing route in `apps/portal/`. The task brief
asks for `apps/portal/` and `apps/marketing/`; **`apps/marketing/` does
not exist** in this checkout (only `apps/portal/`). Findings below
reflect what is actually shipped.

**Method.** Read every `page.tsx` under `src/app/`, plus the per-page
`_components/` clients that own the interactive surface (table rows,
forms, modals). Grepped for `error` / `loading` / `skeleton` / `empty` /
`retry` / `notFound` across the whole `src/` tree. Looked for shared
`<EmptyState>`, `<Skeleton>`, `<ErrorState>`, and `ErrorBoundary`
components — **none exist.** Verified the absence of
`error.tsx` / `not-found.tsx` / `loading.tsx` / `global-error.tsx`
under any route segment. Searched the whole tree for a
`MAINTENANCE_MODE` env flag and a maintenance page — **neither exists.**

## Reading legend

For each page, the six states are marked with one of:

- **Yes** — present and production-grade.
- **Partial** — present but in a degraded form (see note).
- **No** — missing; the brief calls for it.
- **N/A** — the page is a static marketing explainer where the state
  is structurally unreachable (no data fetch, no per-tenant scope).

| State               | What it means here                                                                    |
|---------------------|----------------------------------------------------------------------------------------|
| Empty               | The page renders zero rows / zero tenants / zero findings, and shows copy + (ideally) an illustration, not a blank table. |
| Loading skeleton    | While data is in flight, the user sees placeholder shapes (gray blocks / lines), **not a spinner.** |
| Error + retry       | A server or network failure produces a visible error message with a retry CTA that re-fetches without re-typing. |
| 404                 | A missing encounter id / missing tenant / unmatched route produces a real 404 page with a way back to the portal. |
| 500                 | An unhandled server-side error produces a real error page (not a blank `Internal Server Error` string). |
| Maintenance         | When `MAINTENANCE_MODE` is on, every portal page shows a "we're down" page with a status link instead of failing. |

## Top-level findings (cross-page)

1. **No app-level error boundary exists.** There is no `src/app/error.tsx`,
   no `src/app/global-error.tsx`, no per-segment `error.tsx`, and no
   `<ErrorBoundary>` component in the codebase. Any unhandled
   server-side error in a Server Component will surface to Next.js's
   default error page (or, worse, a white screen in older Next.js
   versions). This is a **production-grade gap.**

2. **No 404 page exists.** There is no `src/app/not-found.tsx` and no
   per-segment `not-found.tsx`. Two pages call `notFound()` from
   `next/navigation` (`/encounters/[id]/page.tsx:57` and `/encounters/[id]/page.tsx:53`)
   — both will fall through to the framework default 404 with no
   brand styling, no link back to /dashboard, and no way for the user
   to know the encounter id is wrong vs. their tenant missing.

3. **No loading skeleton component exists.** The codebase has zero
   shared `<Skeleton>` or `*.skeleton` module. `/encounters/page.tsx:107`
   wraps the client list in `<Suspense fallback={<div
   className={styles.muted}>Loading…</div>}>` — a literal "Loading…"
   text node, not a skeleton. The brief explicitly requires skeletons
   (not spinners); the "Loading…" string is worse than a spinner
   because it claims a state it does not visualize.

4. **No shared `<EmptyState>` or `<ErrorState>` component exists.**
   Each page that needs one inlines a `<section className={styles.empty}>`
   with hand-written copy. The current `.empty` class is a single
   dashed-border centered block; it is consistent enough to call a
   pattern, but it is not a component. Future maintenance will drift.

5. **No maintenance mode exists.** No `MAINTENANCE_MODE` env flag is
   read anywhere. There is no `app/maintenance/page.tsx`. The
   `scripts/purge-canceled-tenants.ts:18` comment refers to a
   "maintenance" cron, but it is unrelated to the UI; it is a script
   that treats non-zero exit as a maintenance signal to the scheduler,
   not a user-facing page.

6. **`apps/marketing/` does not exist.** The task brief says
   "audit `apps/portal/` and `apps/marketing/`". The marketing pages
   (`/`, `/pricing`, `/how-it-works`, `/security`) are all served by
   the `apps/portal/` Next.js app under `apps/portal/src/app/`. There
   is no separate `apps/marketing/` directory.

7. **The root `/` page is the default Next.js starter.** This is the
   most important single finding: **`/workspace/apps/portal/src/app/page.tsx:1-66`
   is the unmodified `create-next-app` boilerplate** ("To get started,
   edit the page.tsx file", Vercel deploy button, Next.js logo). It
   renders for any unauthenticated visitor to the site root. Any link
   from `/security` or `/pricing` back to "Home" lands the buyer on a
   Next.js demo page. This must be replaced before any production
   traffic.

## Per-page audit

### `/` (home) — `apps/portal/src/app/page.tsx`

| State        | Status | Notes |
|--------------|--------|-------|
| Empty        | N/A    | Static page. |
| Loading skel | N/A    | Static page. |
| Error/retry  | N/A    | Static page. |
| 404          | N/A    | This page **is** the root. |
| 500          | N/A    | Static page. |
| Maintenance  | N/A    | — |

**Critical issue:** the page is the unmodified `create-next-app`
boilerplate. It ships a Next.js logo, a "Deploy Now" button pointing
at `vercel.com`, and a link to the Next.js learning center. Anyone
visiting the site root (or clicking "Home" in the site header) sees a
demo page. **This page must be replaced** with a marketing landing
page that matches the tone of `/security` and `/how-it-works` (which
are the actual production explainers in this repo).

**Proposed replacement copy** (heading + sub + primary CTA + secondary
CTA; replace the body of `page.tsx`):

- Heading: "Pre-bill audit, on every claim, before it goes out."
- Sub: "AI reads the clinical note and the code your team picked.
  Flags under-coding, missed charges, modifier issues, and NCCI
  conflicts. Your billing team accepts the good catches, dismisses the
  false alarms."
- Primary CTA label: "See pricing"
- Primary CTA href: `/pricing`
- Secondary CTA label: "How it works"
- Secondary CTA href: `/how-it-works`
- Tertiary inline link: "Sign in →" → `/login`

**Recommendation:** create `apps/portal/src/app/_components/hero.tsx`
+ `apps/portal/src/app/_components/feature-grid.tsx` and re-use the
visual language from `/how-it-works/page.tsx` (dark palette, the
`#28324f` border, the `#2dd4bf` accent, the same `*Illustration`
SVG pattern).

---

### `/login` — `apps/portal/src/app/login/page.tsx`

| State        | Status   | Notes |
|--------------|----------|-------|
| Empty        | N/A      | Form page. |
| Loading skel | N/A      | No data fetch on render. |
| Error/retry  | Yes      | `error === "missing_email"` → `styles.flash` "Please enter your email address." Generic `?error=…` → "Couldn't send the link: …. Check the email address and try again." |
| 404          | N/A      | — |
| 500          | Partial  | If Resend is down, `signIn()` throws and the framework surfaces a 500. No friendly retry copy. |
| Maintenance  | No       | — |

**Gaps:**

1. **No 5xx path.** If the magic-link email send fails server-side,
   the form's `<form action={sendMagicLink}>` Server Action throws and
   the user lands on Next.js's default error page. Recommend a
   `?error=server` branch in the existing `error === ...` ladder
   (line 67-73) and copy: "We couldn't send the link right now. Try
   again, or email hello@ai-billing-audit.ashbi.ca if it keeps
   failing."

2. **The button does not change to a busy state.** The form posts
   directly to the server action; the button is enabled throughout the
   round-trip. A user double-clicking the button can re-send the
   magic-link email. Recommend a Client Component variant that sets
   `state="submitting"` on click and disables the button + shows
   "Sending…" until the redirect fires.

---

### `/dashboard` — `apps/portal/src/app/dashboard/page.tsx`

| State        | Status   | Notes |
|--------------|----------|-------|
| Empty        | Yes      | `!tenant` branch: "No clinic connected" card with "ask your administrator to invite you, or contact support." (lines 70-77). The "Your clinics" sub-section has its own empty text "You don't belong to any clinics yet." (line 125). |
| Loading skel | No       | No skeleton. The dashboard `await`s 4 queries inline; the user sees blank space during the round-trip. |
| Error/retry  | No       | If `prisma.tenant.findUnique` rejects, the whole page 500s. |
| 404          | N/A      | The dashboard is the home; no missing-encounter case. |
| 500          | No       | No app-level error boundary. |
| Maintenance  | No       | — |

**Gaps:**

1. **Loading skeleton for the cards.** Replace the inline data fetch
   with a `<Suspense>` boundary per card (Plan / Quota / Your clinics /
   Quick links), and ship a small `<DashboardCardSkeleton>` with three
   `<div className={styles.skeletonLine} />` rows.

2. **No-tenant state is graceful** (good) but it could be sharper.
   Recommended copy: heading "You're signed in, but no clinic is
   connected to your account yet." Body: "Ask the clinic admin to
   invite you, or [contact support](mailto:hello@ai-billing-audit.ashbi.ca)
   to request access. Once you're added, refresh this page."

3. **Error boundary.** Same as global finding #1 — this page can 500
   with no friendly path. Recommend a `src/app/dashboard/error.tsx` that
   says "We couldn't load your dashboard. [Refresh] [Contact support]."

---

### `/encounters` — `apps/portal/src/app/encounters/page.tsx` + `_components/encounters-list.tsx`

| State        | Status   | Notes |
|--------------|----------|-------|
| Empty        | Yes      | `props.rows.length === 0` → single-cell row "No encounters match the current filters." (encounters-list.tsx:394-399). The page-level subheading also changes copy to "No encounters for {tenant.name} match the current filters." (encounters/page.tsx:103). |
| Loading skel | No       | `<Suspense fallback={<div className={styles.muted}>Loading…</div>}>` at `encounters/page.tsx:107` — literal "Loading…" text, not a skeleton. |
| Error/retry  | Partial  | The client list has no error UI. If `loadEncounterListPage` throws, the page 500s. The `encounters-list.tsx` comment at line 87 hints at a "loading skeleton sentinel" that is never implemented. |
| 404          | N/A      | The list never 404s; empty rows are not 404. |
| 500          | No       | — |
| Maintenance  | No       | — |

**Gaps:**

1. **Replace "Loading…" with a real skeleton.** The list has 7
   sortable columns; the skeleton should render 5-7 rows of 7 grey
   bars. Recommended file:
   `apps/portal/src/app/encounters/_components/encounters-list-skeleton.tsx`.
   The skeleton should be a Server Component (no hooks) so it can
   also be the `loading.tsx` for the route.

2. **Wrap `EncounterListClient` in a client-side error boundary** so a
   throw from the URL-mutation path (`applyParams`) doesn't 500 the
   page. Add a try/catch in the `useTransition` callback that
   re-renders the toolbar with an inline "Couldn't apply that filter.
   [Retry]" message.

3. **Empty state has no illustration** (the brief allows one). A small
   inline SVG of a magnifying glass over a flat list would match the
   visual language of `/how-it-works`.

4. **No-tenant state is good** (encounters/page.tsx:60-71) — the
   "No clinic connected" card uses the same `.empty` style as
   `/dashboard`. Consistent. Keep.

---

### `/encounters/[id]` — `apps/portal/src/app/encounters/[id]/page.tsx` + `_components/finding-card.tsx` + `_components/clinical-note.tsx`

| State        | Status   | Notes |
|--------------|----------|-------|
| Empty        | Yes      | "No findings for this encounter. The auditor ran clean." (encounters/[id]/page.tsx:152-154). |
| Loading skel | N/A      | Server-rendered page; the suspense boundary is on the parent list. |
| Error/retry  | Yes      | Each `<FindingCard>` owns its own per-card error state (`styles.errorBanner` at split-review.module.css:540, surfaced at finding-card.tsx:298). Accept and Dismiss both retry on failure without losing the dismiss-reason text. |
| 404          | Yes      | `notFound()` called at line 57 (encounter not found) and line 53 (no tenant). |
| 500          | No       | The 404 path works because `notFound()` triggers Next.js's default `not-found.tsx` — but **the codebase has no `not-found.tsx`**, so the user sees the framework default 404 with no branding, no link to /dashboard, no way to know the encounter id is wrong. |
| Maintenance  | No       | — |

**Gaps:**

1. **The 404 fallback is unbranded.** This page is the one most
   likely to 404 in production (a user pastes a wrong id, an
   encounter is purged, a tenant mismatch). Recommend
   `apps/portal/src/app/not-found.tsx` (see appendix A) covering all
   404s in the app.

2. **Encounter detail's split-screen has no loading state.** The
   Server Component awaits `loadEncounterDetail` + `wrapEvidenceQuotes`
   synchronously; the user sees a blank split-screen for the round-trip
   duration. Recommend a `loading.tsx` that renders the two-pane
   skeleton (left: header + 6 text-line placeholders; right: 3 card
   placeholders) so the layout doesn't flash.

3. **`<FindingCard>` accept/dismiss error path is solid** — it
   inlines `errorBanner` and does not lose form state on retry.
   Keep this pattern as the template for any future per-card actions.

4. **The "encounter not found" reason is generic** (good — avoids
   info-leak about tenant isolation). Keep generic copy: "We couldn't
   find that encounter. It may have been purged, or it may belong to
   a different clinic."

---

### `/findings` — `apps/portal/src/app/findings/page.tsx` + `_components/findings-inbox.tsx`

| State        | Status   | Notes |
|--------------|----------|-------|
| Empty        | Yes      | "Nothing in this view / No {status} findings match the current filters. Adjust the filters above, or switch the status to see the rest." (findings-inbox.tsx:365-372). |
| Loading skel | No       | No skeleton. The two `await prisma.*` queries are server-side; client gets the rendered table directly. Filter changes go via full page reload (URL mutation), so there is a brief flash of stale data. |
| Error/retry  | Yes      | `setError(...)` in the client for bulk-accept / bulk-dismiss failures; `styles.flash` (line 328, 510, 604) is the inline error UI. Retry is the same button re-click. |
| 404          | N/A      | — |
| 500          | No       | No app-level error boundary. |
| Maintenance  | No       | — |

**Gaps:**

1. **Filter-change loading.** When the user changes a filter, the
   page re-renders server-side. The current rows stay visible but
   there's no visual indicator of in-flight. Recommend a
   `useTransition` dim: while `isPending` is true, add
   `opacity: 0.5; pointer-events: none;` to the table until the new
   rows land.

2. **The "no clinics" empty state is the right shape** but lacks an
   illustration. Recommend a small inline SVG of a clipboard with a
   green checkmark (no findings) or amber dot (filtered out).

3. **No-tenant state** (`!tenant` branch at findings/page.tsx:178-181)
   is the same `.empty` block as everywhere else. Consistent. Keep.

4. **Error retry on bulk-action failure is implicit.** The user
   re-clicks the same button — works, but the error copy doesn't say
   "click again to retry". Recommend: "Bulk accept failed. [Retry]
   [Dismiss]".

---

### `/billing` — `apps/portal/src/app/billing/page.tsx` + `BillingActions.tsx`

| State        | Status   | Notes |
|--------------|----------|-------|
| Empty        | Yes      | "No invoices yet. Once your first billing cycle completes, the receipt will appear here." (billing/page.tsx:233-236). |
| Loading skel | No       | The page is fully server-rendered; the user sees blank cards during the 4-query `Promise.all`. |
| Error/retry  | Yes      | `BillingActions` has three independent error states: `paymentError` (line 74), `tierError` (line 77), `cancelError` (line 86). Each renders as `<p className={styles.error} role="alert">…</p>`. The retry is implicit (re-click the button). |
| 404          | N/A      | — |
| 500          | No       | — |
| Maintenance  | No       | — |

**Gaps:**

1. **No-tenant state is excellent** — it points the user at
   `/pricing` (line 73-75). Keep. Recommended tweak: when the user
   has an active Stripe customer but their tenant was soft-deleted,
   surface that fact explicitly: heading "Your subscription is still
   active, but your clinic is no longer reachable." Body: "Sign in
   with the original owner email, or [contact support]."

2. **past_due and canceled banners are good** (lines 119-133). The
   copy is clear and the data-testid is set for tests. Keep.

3. **Loading skeleton for the three cards.** Recommend a
   `billing-card-skeleton.tsx` with three ghost cards; swap via
   Suspense boundaries.

4. **Invoice table has no empty illustration.** A small receipt SVG
   would be a polish win.

---

### `/billing` (Stripe portal entry) — `apps/portal/src/app/portal/billing/page.tsx`

| State        | Status   | Notes |
|--------------|----------|-------|
| Empty        | N/A      | Static-ish page that either renders a card or redirects. |
| Loading skel | N/A      | No data fetch on render. |
| Error/retry  | Yes      | Three branches: missing `tenantId` (line 27-39), tenant not found (line 46-55), no Stripe customer (line 56-74), demo mode (line 80-98). Each has a different "this is why" message and a back-link. |
| 404          | Partial  | "Tenant not found" is its own page, not a real 404. The user sees the 404 message inline. Could call `notFound()` to be consistent with the rest of the app. |
| 500          | No       | — |
| Maintenance  | No       | — |

**Gaps:**

1. **The "tenant not found" branch is rendered inline.** For
   consistency with the rest of the app, recommend
   `notFound()` + the global `not-found.tsx` (see appendix A).

2. **Demo-mode copy is excellent** — "Stripe is in demo mode — the
   Customer Portal isn't actually available. In production this page
   would redirect to billing.stripe.com…" (line 86-91). Keep verbatim.

---

### `/portal/onboarding` — `apps/portal/src/app/portal/onboarding/page.tsx` + `OnboardingWizard.tsx`

| State        | Status   | Notes |
|--------------|----------|-------|
| Empty        | N/A      | Wizard with discrete steps. |
| Loading skel | No       | The wizard has a `busy` state that toggles button copy to "Uploading…" (OnboardingWizard.tsx:601) but does not show a skeleton. |
| Error/retry  | Yes      | Per-step error banner: `styles.errorBanner` (onboarding.module.css:313), surfaced at OnboardingWizard.tsx:331. Each step has its own `setError(...)`; the user can re-submit the form. |
| 404          | N/A      | — |
| 500          | No       | The "Couldn't verify session" branch (page.tsx:138-150) catches OnboardingError and unknown errors with one generic message — but a real server error (Prisma down) will 500. |
| Maintenance  | No       | — |

**Gaps:**

1. **Anonymous-visit branch is excellent** (page.tsx:59-79). "Almost
   there" badge + sign-in CTA + back-to-pricing secondary. Keep.

2. **"Already claimed" branch is excellent** (page.tsx:153-170).
   Explains the situation and gives a sign-out path. Keep.

3. **The `busy` button text is good**, but consider disabling the
   back/next buttons too so a user can't change steps mid-upload.

4. **The "Something went wrong" branch at line 173-183 is a 500
   fallback rendered as a page.** A 500 page should be a global
   `error.tsx`, not a per-page branch — otherwise every page needs
   its own. Recommend removing the page-level catch and relying on
   the global error boundary.

---

### `/pricing` — `apps/portal/src/app/pricing/page.tsx` + `CheckoutButton.tsx`

| State        | Status   | Notes |
|--------------|----------|-------|
| Empty        | N/A      | Static pricing grid. |
| Loading skel | N/A      | `revalidate = 60` (line 19); no per-request fetch. |
| Error/retry  | Yes      | `<CheckoutButton>` has `state === "error"` (CheckoutButton.tsx:27) and `errorMsg` (line 28); surfaces inline `styles.ctaError` (line 72-74). The button stays clickable to retry. |
| 404          | N/A      | — |
| 500          | No       | The pricing page is a static render; if `getPricingConfig()` throws, the whole build 500s. |
| Maintenance  | No       | — |

**Gaps:**

1. **No 5xx path on the pricing API.** If `getPricingConfig()` throws
   at request time, the user sees Next.js's default error. Recommend
   a `try/catch` in `getPricingConfig` that returns a hard-coded
   fallback (the page already has a `try/catch` in
   `formatCurrency` for the same reason — extend the pattern).

2. **CheckoutButton error copy is good** but generic. Consider mapping
   common server error codes to friendlier copy:
   - `400 invalid_currency` → "Pick a supported currency."
   - `409 already_subscribed` → "You're already subscribed. [Manage
     billing →]."
   - `5xx` → "We couldn't start checkout. Try again, or
     [email us](mailto:hello@ai-billing-audit.ashbi.ca)."

---

### `/how-it-works` — `apps/portal/src/app/how-it-works/page.tsx`

| State        | Status | Notes |
|--------------|--------|-------|
| Empty        | N/A    | Static explainer. |
| Loading skel | N/A    | — |
| Error/retry  | N/A    | — |
| 404          | N/A    | — |
| 500          | N/A    | — |
| Maintenance  | N/A    | — |

**No gaps.** This is a static marketing page. The 90-second Loom
embed is a placeholder SVG (`loomPlaceholder` block at line 103-110)
— that's a content gap, not a state gap, and out of scope here.

---

### `/security` — `apps/portal/src/app/security/page.tsx`

| State        | Status | Notes |
|--------------|--------|-------|
| Empty        | N/A    | Static explainer. |
| Loading skel | N/A    | — |
| Error/retry  | N/A    | — |
| 404          | N/A    | — |
| 500          | N/A    | — |
| Maintenance  | N/A    | — |

**No gaps.** Same shape as `/how-it-works`. Compliance matrix is
a static table.

---

### `/settings` — `apps/portal/src/app/settings/page.tsx`

| State        | Status   | Notes |
|--------------|----------|-------|
| Empty        | Yes      | "No clinic connected" (line 28-37) and "Tenant not found" (line 55-65) branches both render a `.empty` card. |
| Loading skel | No       | One Prisma `findUnique`; user sees blank space during the round-trip. |
| Error/retry  | No       | A `prisma.tenant.findUnique` throw 500s. |
| 404          | Partial  | "Tenant not found" is rendered inline, not via `notFound()`. |
| 500          | No       | — |
| Maintenance  | No       | — |

**Gaps:**

1. **Convert the "Tenant not found" branch to `notFound()`** to
   route through the global `not-found.tsx` (see appendix A).

2. **Add a `loading.tsx` for this route** that shows the identity /
   subscription / quota fields as skeletons.

3. **The page is a read-only shell** (line 5-7 comment). The brief
   doesn't ask for a "no edit yet" state, but recommend a small
   banner: "Settings is read-only in this build. To update your
   clinic name, contact support." (single line, bottom of the page).

---

### `/team` — `apps/portal/src/app/team/page.tsx`

| State        | Status   | Notes |
|--------------|----------|-------|
| Empty        | Yes      | "No members yet / This clinic has no users yet. The invite flow ships next milestone." (line 60-64). |
| Loading skel | No       | One `prisma.membership.findMany`; blank space during round-trip. |
| Error/retry  | No       | A throw 500s. |
| 404          | N/A      | — |
| 500          | No       | — |
| Maintenance  | No       | — |

**Gaps:**

1. **No-tenant state is the same `.empty` block** as everywhere else
   (line 30-40). Consistent. Keep.

2. **Loading skeleton for the members table.** Recommend 4 rows of
   grey bars (Name / Email / Role / Joined).

3. **The "0 members" empty state contradicts the no-tenant branch.**
   A user with no tenant sees "No clinic connected"; a user with a
   tenant but no members sees "No members yet". Both are correct.
   Consider tightening the second to: "No team members yet. The
   invite flow is coming next milestone. [Contact support] to add a
   user manually."

---

### `/api/*` (route handlers) — 18 routes under `apps/portal/src/app/api/`

| State        | Status   | Notes |
|--------------|----------|-------|
| 401          | Yes      | The proxy (`src/proxy.ts`) returns 401 for unauthenticated API requests (see proxy.ts:62-72 block). |
| 500          | No       | No app-level error boundary catches API errors. They bubble to Next.js's default JSON error response. |

**Gaps:**

1. **Standard error response shape.** The billing and findings routes
   return `{ error: string }` (e.g.
   `/api/billing/change-tier/route.ts:124` per BillingActions.tsx:123
   expectation). The encounters routes also return
   `{ error, detail }` (e.g. finding-card.tsx:87 expects either).
   Recommend a single shared error-shape helper in
   `src/lib/api-errors.ts` so every route returns
   `{ error: { code, message, hint? } }` with a stable code the
   client can switch on.

2. **No request-id in 5xx responses.** A 5xx from a route handler is
   untraceable without server logs. Recommend `X-Request-Id` echoed
   back in the response (set in the proxy or in a shared middleware)
   so users can quote it when contacting support.

---

## Appendices

### Appendix A — Recommended 404 page (`apps/portal/src/app/not-found.tsx`)

```tsx
// Recommended new file. Renders for any unmatched route and any
// notFound() call across the app.
import Link from "next/link";

export default function NotFound() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        background: "linear-gradient(180deg, #0b1020 0%, #0d1428 100%)",
        color: "#e7ecf6",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <div
        style={{
          background: "#131a2e",
          border: "1px solid #28324f",
          borderRadius: 16,
          padding: 40,
          maxWidth: 520,
          textAlign: "center",
        }}
      >
        <div
          style={{
            display: "inline-block",
            background: "rgba(248, 113, 113, 0.12)",
            color: "#f87171",
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: "0.5px",
            textTransform: "uppercase",
            padding: "4px 10px",
            borderRadius: 999,
            marginBottom: 16,
          }}
        >
          404 — Not found
        </div>
        <h1 style={{ margin: "0 0 8px", fontSize: 28 }}>We can't find that page</h1>
        <p style={{ color: "#9aa3bd", margin: "8px 0 24px", lineHeight: 1.55 }}>
          The link may be old, the encounter may have been purged, or
          this page may belong to a different clinic. If you got here
          from inside the app, the URL is probably stale — go back to
          the dashboard and try again.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
          <Link
            href="/dashboard"
            style={{
              display: "inline-block",
              background: "#2dd4bf",
              color: "#0b1020",
              padding: "10px 20px",
              borderRadius: 10,
              textDecoration: "none",
              fontWeight: 600,
            }}
          >
            Back to dashboard
          </Link>
          <Link
            href="/pricing"
            style={{
              display: "inline-block",
              border: "1px solid #28324f",
              color: "#e7ecf6",
              padding: "10px 20px",
              borderRadius: 10,
              textDecoration: "none",
            }}
          >
            See pricing
          </Link>
        </div>
      </div>
    </main>
  );
}
```

### Appendix B — Recommended 500 / error page (`apps/portal/src/app/error.tsx`)

```tsx
"use client";

// Required because Next.js error boundaries must be Client Components.
import Link from "next/link";
import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // The digest is set by Next.js on the server and is the
    // support-quote key. Echo it to the console for the dev console
    // and to the server log via the proxy's request-id header.
    console.error("[portal] Unhandled error:", error);
  }, [error]);

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        background: "linear-gradient(180deg, #0b1020 0%, #0d1428 100%)",
        color: "#e7ecf6",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <div
        style={{
          background: "#131a2e",
          border: "1px solid #28324f",
          borderRadius: 16,
          padding: 40,
          maxWidth: 520,
          textAlign: "center",
        }}
      >
        <div
          style={{
            display: "inline-block",
            background: "rgba(251, 191, 36, 0.12)",
            color: "#fbbf24",
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: "0.5px",
            textTransform: "uppercase",
            padding: "4px 10px",
            borderRadius: 999,
            marginBottom: 16,
          }}
        >
          Something went wrong
        </div>
        <h1 style={{ margin: "0 0 8px", fontSize: 28 }}>
          We hit a snag loading this page
        </h1>
        <p style={{ color: "#9aa3bd", margin: "8px 0 16px", lineHeight: 1.55 }}>
          Our team has been notified. You can try again, or head back
          to the dashboard and pick up where you left off.
        </p>
        {error.digest ? (
          <p
            style={{
              color: "#9aa3bd",
              fontSize: 12,
              fontFamily: "ui-monospace, monospace",
              margin: "0 0 24px",
            }}
          >
            Reference: {error.digest}
          </p>
        ) : null}
        <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
          <button
            type="button"
            onClick={reset}
            style={{
              background: "#2dd4bf",
              color: "#0b1020",
              padding: "10px 20px",
              borderRadius: 10,
              border: 0,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Try again
          </button>
          <Link
            href="/dashboard"
            style={{
              display: "inline-block",
              border: "1px solid #28324f",
              color: "#e7ecf6",
              padding: "10px 20px",
              borderRadius: 10,
              textDecoration: "none",
            }}
          >
            Back to dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}
```

### Appendix C — Recommended root loading skeleton (`apps/portal/src/app/loading.tsx`)

```tsx
// Generic shimmer placeholder used as the default fallback for
// <Suspense> boundaries that do not provide their own skeleton.
export default function Loading() {
  return (
    <main
      style={{
        minHeight: "100vh",
        padding: "32px clamp(16px, 4vw, 48px)",
        background: "linear-gradient(180deg, #0b1020 0%, #0d1428 100%)",
        color: "#e7ecf6",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <div
        style={{
          height: 32,
          width: 240,
          background: "#1a2340",
          borderRadius: 8,
          marginBottom: 12,
        }}
        aria-hidden="true"
      />
      <div
        style={{
          height: 16,
          width: 360,
          background: "#1a2340",
          borderRadius: 6,
          marginBottom: 32,
        }}
        aria-hidden="true"
      />
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            height: 80,
            background: "#131a2e",
            border: "1px solid #28324f",
            borderRadius: 12,
            marginBottom: 16,
          }}
          aria-hidden="true"
        />
      ))}
      <span style={{ position: "absolute", left: -9999 }}>
        Loading…
      </span>
    </main>
  );
}
```

### Appendix D — Recommended maintenance page (`apps/portal/src/app/maintenance/page.tsx`)

```tsx
// Maintenance mode entry point. Served at /maintenance when the
// MAINTENANCE_MODE env var is set, regardless of the path. Pair with
// a tiny middleware override in src/proxy.ts that short-circuits all
// other requests to this page while MAINTENANCE_MODE=on.
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Scheduled maintenance — AI Pre-Bill Audit",
  description:
    "The portal is temporarily offline for scheduled maintenance. " +
    "We'll be back shortly.",
  robots: "noindex, nofollow",
};

export default function MaintenancePage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        background: "linear-gradient(180deg, #0b1020 0%, #0d1428 100%)",
        color: "#e7ecf6",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <div
        style={{
          background: "#131a2e",
          border: "1px solid #28324f",
          borderRadius: 16,
          padding: 40,
          maxWidth: 520,
          textAlign: "center",
        }}
      >
        <div
          style={{
            display: "inline-block",
            background: "rgba(45, 212, 191, 0.12)",
            color: "#2dd4bf",
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: "0.5px",
            textTransform: "uppercase",
            padding: "4px 10px",
            borderRadius: 999,
            marginBottom: 16,
          }}
        >
          Scheduled maintenance
        </div>
        <h1 style={{ margin: "0 0 8px", fontSize: 28 }}>
          We're tuning things up
        </h1>
        <p style={{ color: "#9aa3bd", margin: "8px 0 16px", lineHeight: 1.55 }}>
          The portal is temporarily offline. We're backfilling the
          audit queue, refreshing the database, and rolling out the
          latest changes. No data is at risk.
        </p>
        <p style={{ color: "#9aa3bd", margin: "0 0 24px", lineHeight: 1.55 }}>
          Live status:{" "}
          <a
            href="https://status.ai-billing-audit.ashbi.ca"
            style={{ color: "#2dd4bf" }}
          >
            status.ai-billing-audit.ashbi.ca
          </a>
          <br />
          Questions?{" "}
          <a
            href="mailto:hello@ai-billing-audit.ashbi.ca"
            style={{ color: "#2dd4bf" }}
          >
            hello@ai-billing-audit.ashbi.ca
          </a>
        </p>
        <a
          href="/login"
          style={{
            display: "inline-block",
            border: "1px solid #28324f",
            color: "#e7ecf6",
            padding: "10px 20px",
            borderRadius: 10,
            textDecoration: "none",
          }}
        >
          Try again
        </a>
      </div>
    </main>
  );
}
```

### Appendix E — Recommended shared component skeletons

```tsx
// apps/portal/src/app/_components/empty-state.tsx
// Drop-in replacement for the <section className={styles.empty}>
// pattern. Brings the heading + body + optional CTA into one place.
export function EmptyState({
  title,
  body,
  ctaLabel,
  ctaHref,
}: {
  title: string;
  body: React.ReactNode;
  ctaLabel?: string;
  ctaHref?: string;
}) {
  return (
    <section
      style={{
        border: "1px dashed #28324f",
        borderRadius: 16,
        padding: "40px 24px",
        textAlign: "center",
        color: "#9aa3bd",
      }}
    >
      <h2 style={{ color: "#e7ecf6", margin: "0 0 8px", fontSize: 20 }}>
        {title}
      </h2>
      <p style={{ margin: 0, fontSize: 14, lineHeight: 1.5 }}>{body}</p>
      {ctaLabel && ctaHref ? (
        <p style={{ marginTop: 16 }}>
          <a
            href={ctaHref}
            style={{
              display: "inline-block",
              padding: "8px 16px",
              background: "#2dd4bf",
              color: "#0b1020",
              borderRadius: 8,
              textDecoration: "none",
              fontWeight: 600,
            }}
          >
            {ctaLabel}
          </a>
        </p>
      ) : null}
    </section>
  );
}
```

```tsx
// apps/portal/src/app/_components/skeleton-line.tsx
// Reusable shimmer line for table rows, cards, paragraphs.
export function SkeletonLine({
  width = "100%",
  height = 14,
}: {
  width?: number | string;
  height?: number;
}) {
  return (
    <div
      aria-hidden="true"
      style={{
        width,
        height,
        background:
          "linear-gradient(90deg, #1a2340 0%, #28324f 50%, #1a2340 100%)",
        backgroundSize: "200% 100%",
        borderRadius: 6,
        animation: "pulse 1.4s ease-in-out infinite",
        marginBottom: 8,
      }}
    />
  );
}
```

### Appendix F — Recommended proxy patch to enable maintenance mode

```ts
// In apps/portal/src/proxy.ts, add at the top of the `proxy` body,
// after the `isPublicPath` check fails (i.e. for protected routes
// only — keep maintenance, login, and pricing public so admins can
// read the maintenance page during a deploy).
if (process.env.MAINTENANCE_MODE === "1" && !isPublicPath(pathname)) {
  const url = request.nextUrl.clone();
  url.pathname = "/maintenance";
  return NextResponse.rewrite(url);
}
```

The `/maintenance` path stays public (add it to `PUBLIC_PREFIXES`)
so the page itself is reachable. The rewrite preserves the original
URL in the address bar, so the user keeps the URL they typed.

## Severity roll-up

| # | Finding | Severity | File | Action |
|---|---------|----------|------|--------|
| 1 | `/` is the default Next.js starter page | Critical | `apps/portal/src/app/page.tsx:1-66` | Replace with marketing landing (see `/` section). |
| 2 | No app-level `error.tsx` / `global-error.tsx` | Critical | (missing) | Add `apps/portal/src/app/error.tsx` (appendix B). |
| 3 | No app-level `not-found.tsx` | High | (missing) | Add `apps/portal/src/app/not-found.tsx` (appendix A). |
| 4 | No app-level `loading.tsx`; per-page "Loading…" text is not a skeleton | High | `apps/portal/src/app/encounters/page.tsx:107` | Add `apps/portal/src/app/loading.tsx` (appendix C) and per-route skeletons. |
| 5 | No maintenance mode (no env flag, no page, no proxy wiring) | High | (missing) | Add `MAINTENANCE_MODE` handling (appendix D + F). |
| 6 | No shared `<EmptyState>` / `<Skeleton>` / `<ErrorState>` components | Medium | (missing) | Add `apps/portal/src/app/_components/empty-state.tsx` + `skeleton-line.tsx` (appendix E). |
| 7 | Login button stays enabled during send; no 5xx copy on Resend failure | Medium | `apps/portal/src/app/login/page.tsx:88-91` | Add `?error=server` branch + busy state. |
| 8 | `apps/marketing/` does not exist | Low | (missing) | Out of scope for this audit; the marketing pages are inside `apps/portal/`. |
| 9 | Per-page "Tenant not found" branches render inline instead of calling `notFound()` | Low | `apps/portal/src/app/settings/page.tsx:55-65`, `apps/portal/src/app/portal/billing/page.tsx:46-55` | Convert to `notFound()` once the global 404 page exists. |
| 10 | API route error response shape is inconsistent (`{ error }` vs `{ error, detail }`) | Low | `apps/portal/src/app/api/**/route.ts` | Standardize in `src/lib/api-errors.ts`. |

## Verification checklist (what to ship next)

- [ ] `apps/portal/src/app/page.tsx` replaced with a marketing landing.
- [ ] `apps/portal/src/app/error.tsx` added (Client Component, global error boundary).
- [ ] `apps/portal/src/app/not-found.tsx` added.
- [ ] `apps/portal/src/app/loading.tsx` added.
- [ ] `apps/portal/src/app/maintenance/page.tsx` added + proxy wiring.
- [ ] `apps/portal/src/app/_components/empty-state.tsx` and `skeleton-line.tsx` extracted.
- [ ] Existing inline `.empty` blocks migrated to `<EmptyState>` (cosmetic; no behavior change).
- [ ] Existing "Loading…" text replaced with skeleton (encounters list first, then dashboard / billing / settings / team).
- [ ] Login page: 5xx error copy + busy button state.
- [ ] `MAINTENANCE_MODE=1` smoke test: every portal page renders the maintenance page; pricing, security, /maintenance, /login stay public.
- [ ] `npm run build` clean.
- [ ] Manual click-through of all 6 states on staging:
      empty (new tenant, no encounters), loading (throttled dev
      server), error (kill the DB and reload), 404 (visit
      `/encounters/does-not-exist`), 500 (throw inside a Server
      Component), maintenance (`MAINTENANCE_MODE=1`).
