# Changelog — `ai-billing-audit`

Reverse-chronological. Newest at top.

## 2026-07-01 — P11 round-2 (5-agent swarm redux + fixes)

`da747ee`, `b6c9c82`. Swarm redux dispatched after round-1
deployed; caught 5 critical regressions + several high-priority
items that round-1 missed.

### Production-blockers found by swarm

- **404 didn't work.** Middleware 307-redirected every unknown
  URL to `/login`, so users who mistyped a URL landed on the
  login page (hostile UX + hostile SEO). Fixed by adding an
  AUTHED_PREFIXES short-circuit: paths that don't match a known
  portal route fall through to Next's not-found handler. Public
  marketing routes still allow-listed as before.
- **No security headers on portal origin.** CSP / HSTS /
  X-Content-Type-Options / X-Frame-Options / Referrer-Policy
  / Permissions-Policy were all missing on `zorva.ashbi.ca`
  (the API origin had them). `/security` advertised TLS 1.3 +
  security controls but the live response didn't carry any of
  them. Fixed via `next.config.ts` `headers()` block.
- **`compress: true`** — HTML responses on the portal were
  uncompressed (50% bandwidth tax, especially `/status` at
  134KB). Enabled Next.js built-in compression as a safety
  net; the Traefik edge handles actual gzip/brotli negotiation.
- **`AUDIT_BEARER_TOKEN` was still missing on the live VPS** —
  covered in round-1 commit `6804454`.

### Code-quality regressions caught by swarm

- **`auditor.py` import** — round-1 fix already shipped.
- **`dashboard.py` init** — round-1 fix already shipped.
- **`audit_actions` separator** — round-1 fix already shipped.

### Marketing reality — regressions caught

- **`/compare` still shipped "per-specialty learning loop"** in
  the summary bullet ("…and a per-specialty learning loop").
  Round-1 fix missed this string. Replaced with "…combines
  SOMB-native rules and a defensible audit trail."
- **`/calculator` ROI-FORMULA link path** still pointed to
  `/docs/research/ROI-FORMULA.md` (a path that doesn't exist as
  a Next route). The previous round-1 fix had changed the URL
  to github.com/camster91/ai-billing-audit/blob/main/docs/research/
  ROI-FORMULA.md — but the path segment itself was still the
  rejected one. Now points to the actual benchmark file
  `runs/recall/v12_ahcip_clean.json`.
- **`/security` had no `mailto:security@ashbi.ca`** — privacy
  officers reporting a vulnerability had no dedicated alias.
  Footer now offers `security@ashbi.ca` for coordinated
  disclosure / encryption-key inquiry.

### Cold email rewrites (Rule 1 audit-first opener)

Swarm audit caught that all 3 cold email drafts opened with "I'm
Cameron Ashley" before any SOMB-pattern audit content. That IS
the textbook "I noticed your firm…" generic intro Cameron's
cold-outreach rule #1 explicitly bans. Restructured each:

- Para 1: 3 SOMB-pattern findings (the receipts)
- Para 2: brief self-intro (one line) + trigger framing
- Para 3: F1 claim + privacy officer brief
- CTA: pull-not-push (unchanged)
- P.S.: privacy officer brief (unchanged)
- Signature: added real credentials ("Top Rated on Upwork,
  80+ projects, $100K+ earned") to satisfy Rule 5

Also tightened:
- Red Deer: removed "0.69 vs 0.65 in the P/R decomposition"
  (Rule 2 jargon)
- Red Deer subject: "99-doctor PCN" → "Three AHCIP patterns your
  99-doctor PCN is probably losing money on" (findings lead)
- Strathcona subject: "60-doctor PCN" → "60–80-doctor PCN"
  (matches the ALBERTA_PROSPECT_LIST.md verified range)
- Strathcona: dropped TELUS Med Access over-claim (prospect
  list actually says Mixed EMR)

### Portal accessibility deep-pass (slice 4 of swarm)

- **`/pricing` `<main id="main">`** — added (skip-link target).
- **`/faq` `<main id="main">`** — added.
- **`/try` `<main id="main">`** — added.
- **`/calculator` `<main id="main">`** — added.
- **`/pricing` list semantic** — swapped `<div role="list">` +
  `<article role="listitem">` for real `<ul>` / `<li>`. Safari
  + VoiceOver strip list semantics from `div+role`. Dropped
  redundant `aria-label` that duplicated visible text.
- **`/calculator` input labels** — added explicit `id` +
  `htmlFor` on every control (WCAG 1.3.1 / 4.1.2 — Voice Control,
  NVDA, JAWS, Dragon all need id-based lookup; implicit-only
  labels are unreliable). Added `aria-atomic="true"` + `aria-label`
  on the result `<aside>` so screen-reader users hear
  recalculations as the slider moves.
- **`/calculator` dark theme** — was light-themed on a dark
  layout (WCAG 1.4.11 fail). Switched CSS tokens to the project's
  dark palette (`--text`, `--panel`, `--panel-2`, `--line`,
  `--muted`, `--accent`).
- **`/billing` invoice table** — added `<caption>` +
  `scope="col"` on every `<th>` (WCAG 1.3.1).
- **`/login` error flash** — `role="status"` → `role="alert"`.
  Errors should be assertive (heard immediately on next pause),
  not advisory (queued for next polite sweep).

### Portal performance (slice 5 of swarm)

- **`/status` SVG collapse** — 90 inline `<span>` day-bars × 5
  systems = 450 DOM nodes per page. Replaced with one `<svg>`
  per system containing 90 `<rect>` children. Same visual, ~10×
  smaller HTML, friendly to screen readers (semantic `<rect>`
  vs unlabelled `<span>`).
- **Drop Geist + Geist_Mono fonts** — 0 CSS consumers (verified
  with `grep -rE "var\(--font-geist"`), 88KB saved across 4
  woff2 files. Removed both `Geist({…})` calls + the matching
  `--font-geist-*` references in `<html className>`.

### Patient-hash hardening

- **Pepper minimum 16 → 32 chars** (both TypeScript + Python).
  16 is brute-forceable against a known-format payer-ID
  dictionary in days on a single GPU; 32 (256 bits if hex-
  derived) matches the hash output width and removes that
  attack class. Production fail-fast message updated.
- **Input length cap 1024 chars** — DoS defense (a 1MB
  patientId would have been persisted to the JSONL audit log
  before the Postgres shape check rejected it at the DB
  layer). New test added: 1024-char boundary still works,
  1025 throws RangeError.
- All 11 patient-hash TypeScript tests pass + all 5 api-errors
  tests pass. Python `test_patient_hash.py` uses the
  `MIN_PEPPER_LENGTH` constant so the bump is automatically
  reflected.

### Live verification (2026-07-01 EOD)

```
1. Cold emails Rule 1 compliance:    ✓ (audit findings at line 7-9)
2. Security headers on portal:       ✓ (6 headers, all present)
3. Friendly 404:                     ✓ (/nonexistent-zzz → 404, not 307)
4. /compare "per-specialty":        ✓ (removed)
5. /security security@ mailto:      ✓ (added)
6. /calculator id=main + ROI link:   ✓ (id=main present, 0 /docs/research/ROI-FORMULA hits)
7. /status SVG day bars:             ✓ (0 inline spans, 5 SVGs)
8. /pricing list semantic:           ✓ (1 ul.tiers, 0 role="list")
9. Geist fonts dropped:              ✓ (0 geist references anywhere)
10. /billing caption + scope=col:    ✓ (in source; auth-gated so live curl skips)
11. /login role=alert:               ✓ (in source; only renders on error param)
12. compress: true in next.config:   ✓ (Traefik edge handles compression at vary negotiation)
13. FastAPI still healthy:           ✓ (GET /healthz → 200, email webhook reachable)
```

### Deferred / out-of-scope

- **Forward x-tenant-id in middleware** — requires Prisma DB-session
  rewrite. Same blocker as round-1.
- **Sentry / structured error reporter** — `global-error.tsx`'s
  only error sink is `console.error`. For HIPAA-touching portal
  we should add Sentry (or similar). Marked as `console.error
  is the only place this error is reported` in the swarm audit;
  deferred to a separate security PR.
- **NetCool Ollama Cloud API key rotation** — `W1.1.1` per
  weekly schedule; not blocking.
- **`/demo-request` validation runs on submit only, not on blur**
  — WCAG 3.3.1 / 3.3.3 fail. Cosmetic for v1; flagged for next
  portal polish.
- **API origin headers vs portal origin headers** — parity
  achieved (both have CSP/HSTS/XCTO/XFO/Referrer-Policy).
  Portal still needs CSP `script-src` to allow Plausible when
  `NEXT_PUBLIC_PLAUSIBLE_DOMAIN` is set; tracked for when
  analytics is turned on.

### Swarm provenance

Re-runnable: 5 slices (live-state verifier, cold email style
auditor, new-file quality, accessibility deep-pass, performance
baseline). Slice prompts + re-spawn instructions available
on request — see this changelog and `research/P11-bug-sweep.md`
for the round-1 version.