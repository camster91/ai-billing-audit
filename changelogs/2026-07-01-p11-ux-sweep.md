# Changelog — `ai-billing-audit`

Reverse-chronological. Newest at top.

## 2026-07-01 — P11 UX sweep (5 commits)

`f844564`, `e4ab940`, `e05edbe`, `fd367e1`, `d1f977a`, `6804454`.

### Production-blockers (round 1)

- **FastAPI 503 blanket-block killed.** `AUDIT_BEARER_TOKEN` is now
  configured on the live VPS (`/opt/projects/ai-billing-audit/.env`).
  Old literal `pilot-bearer-token-2026-06-17-ashbi` removed from
  `docs/PILOT_DEMO_RECORDING{,_v2}.md`; the live token is now in
  `/root/.ai_billing_bearer_dir/token` (chmod 600).
- **`/encounters/{id}/audit` auth gate.** Added
  `Depends(require_biller_or_admin)` to the 420-line handler at
  `src/ai_billing_audit/api.py:6225`. Was unauthenticated for any
  caller with a valid bearer token.
- **Magic-link URL leak in `auth.ts` killed.** The dev-mock
  `sendVerificationRequest` was logging the full magic-link URL
  (which contains the one-shot token) to stdout. Anyone with log
  access got a one-shot account-takeover vector. All three debug
  logs (`debugNormalizer`, `sendVerificationRequest`, `signIn`)
  are now `NODE_ENV !== "production"`-gated. Email addresses are
  replaced with `sha256:<8hex>` prefix redaction via
  `devRedactEmail()`. The magic-link URL is **never** logged.
- **Resend webhook + RFC 8058 unsubscribe reachable.** Both routes
  were 307-redirecting to `/login` because they were missing from
  `PUBLIC_PREFIXES`. Resend would have disabled the sender after
  retry-exhaustion; CAN-SPAM requires the unsubscribe to be
  reachable. Added `/api/email/webhook` and `/api/email/unsubscribe`
  to `PUBLIC_PREFIXES`.
- **`/pilot` page rewritten.** Was internally inconsistent (titled
  30/60/90 but body said 60-day) and promised a "daily digest
  email" that the product does not ship. Now two-phase (Days 1-30
  / Days 31-60), 60-day no-cost framing, weekly reviews, day-60
  decision call.
- **`/press` page rewritten.** Removed fabricated "Maya Okafor"
  founder quote + example.com URLs. Now honestly says "No
  third-party coverage yet."

### Code-quality hot-path crashes

- `auditor.py:42` — added `import re`. `re.split(...)` at line 331
  was a `NameError` on every quota-finding audit. Fixed.
- `dashboard.py:65` — initialized `seen_encounters: set[str] = set()`.
  The "top missed-revenue rules" tile on the home dashboard was
  permanently empty because `NameError` was swallowed by
  `except Exception:` at `api.py:1540`.
- `audit_actions.compute_signature` — dropped the `|` field
  separator. Rows written by `audit_actions.append()` now verify
  cleanly against the canonical `audit_log.verify_chain` (and vice
  versa). Module + function docstrings updated.

### Marketing reality (vs code)

- **Global `@zorva.ca` → `@ashbi.ca` rename.** 37 references across
  23 portal pages + 4 docs files (DNS for zorva.ca never existed;
  every `mailto:` link was silently dead).
- **5 conflicting pricing tier schemes unified.** `pricing.ts`,
  `pricing/page.tsx`, `faq/page.tsx`, `ONE_PAGER`, and
  `tenant.ts` all said different things (500/2000/5000 vs
  1K/3K/3K+ vs 100/1000/10000). Picked 1K/3K/3K+ (P11 reality-
  check) and propagated.
- **`/legal/privacy`** — `Anthropic` → `MiniMax` (the actual LLM
  provider). Hostinger framing clarified.
- **`/compare`** — "Per-specialty learning from accept/dismiss"
  overclaim replaced with honest "Accept/dismiss history export"
  (we log + export, we don't auto-tune in real time).
- 3 broken `/docs/...` and `/legal/...md` deep-links — replaced
  with working routes or GitHub-blob links.
- **`/status`** — "5-minute ack" + "daily digest" claims replaced
  with honest "static snapshot per deploy, on-call phone is
  authoritative".
- 12 metadata titles audited for double-dash rendering.

### Portal handlers info-leak (round 2)

- New `apps/portal/src/lib/api-errors.ts::internalErrorResponse()` —
  log full server-side, return sanitized client-side with
  `x-request-id` header.
- Migrated 6 handlers (`/api/leads`, `/api/usage`, plus the 4 leaky
  `/api/billing/*` handlers). Other 10 onboarding/settings handlers
  were already safe (use `mapError()` pattern).

### UX sweep (round 3 + round 4)

UX audit re-spawned with concrete prompts returned 2 critical +
7 high + 12 low findings. Fixed:

- **Viewport meta tag** added to layout.tsx (mobile browsers were
  rendering at ~980px desktop width without it). Includes
  `viewport-fit=cover` for the iPhone notch area.
- **7 portal pages** — added `id="main"` to `<main>` so the
  skip-link works (was jumping into the marketing header nav).
- **`error.tsx` + `global-error.tsx` + `loading.tsx`** added at
  the root. Pre-fix, any thrown error in a Prisma round-trip
  surfaced as the framework's default unthemed error page.
- **`/encounters` loading fallback** — replaced plain
  "Loading…" with the canonical `<EncounterListSkeleton rows={5} />`.
- **Focus rings** on Accept/Dismiss buttons — added explicit
  outline (`#38bdf8`, 2px solid, offset 2px) so keyboard users
  can see focus against the dark dismiss-panel background
  (WCAG SC 2.4.7).
- **`/billing` invoice table** wrapped in a horizontally-scrollable
  container so the page doesn't horizontal-scroll at <400px.

### Technical page + investor doc (round 4)

- `/technical` — `patient_hash` formula description was "SHA-256[:12]"
  but the implementation is now full 64-hex salted SHA-256 with
  `PATIENT_HASH_PEPPER`. Signature formula updated to no-separator
  shape (post-P11 round-1 fix). `LAST_REVIEWED` bumped to 2026-07-01.
- `docs/INVESTOR_ONEPAGER.md` — removed fabricated "current
  traction" numbers (8 clinics, $172k ARR, 38% lift, <1% FP on 240
  encounters) and the fictional founder `maya@zorva.health`.
  Marked TAM/SAM/SOM as "PLACEHOLDER — needs source." Ask
  updated from "$3.5M seed" to honest "pre-revenue, raising
  friends-and-family round to fund first 60-day pilot."

### Cold email drafts (commit `e05edbe`)

- West Springs opener rewritten — was matching the event-recap
  pattern Cameron's cold-outreach style rule bans ("I saw X has
  an active locum posting..."). Now leads with the 3 SOMB
  patterns; trigger event moved to the middle paragraph where it
  frames the timing of the offer. Applies to user_profile rule 8.

### Tests (commit `f844564`)

- `apps/portal/tests/api-errors.test.ts` — 5 tests covering status
  code, sanitized body, x-request-id header, server-side log
  contents, non-Error throws, override requestId, hint in log
  not body, concurrent unique requestIds. All 5 pass.

### Deferred / out-of-scope

- Forward x-tenant-id in middleware — requires Prisma DB-session
  rewrite (separate kanban card).
- `/technical` scrubbed-of-names claim needs next review cycle
  (more honest: "patient identifier is salted SHA-256 hashed; the
  encounter narrative is sent verbatim to the LLM under our
  zero-retention terms").
- 198 ruff errors — separate cleanup PR (`ruff --fix` would
  resolve ~120; the rest need manual review).
- INVESTOR_ONEPAGER content layout is a *spec*; the actual PDF is
  not yet produced. PDF is <250 KB target, signed with real
  cryptographic signature (DocuSign acceptable for v1).

### Verification

- 791 pytest tests still pass locally.
- All Python files parse + compile cleanly.
- Live VPS smoke test:
  - `https://zorva.ashbi.ca/` — 200 on all 13 marketing pages
  - `https://ai-billing-audit.ashbi.ca/healthz` — 200
  - `POST /api/encounters/{id}/audit` — 401 no token, 404 with
    valid token for unknown encounter (was 503 blanket-block)
  - `POST /api/email/webhook` + `/api/email/unsubscribe` —
    reachable from middleware (handler returns 503/400 from logic,
    not 307 redirect to /login)
  - `https://zorva.ashbi.ca/technical` — "salted SHA-256" present,
    no "First 12 chars", signature formula no-separator
- All 5 new api-errors tests pass.

### Swarm provenance

Re-runnable: see `research/P11-bug-sweep.md` for slice prompts
and re-spawn instructions.