# UI Review — AI Pre-Bill Audit Marketing Site

**Reviewer:** Hermes (kanban task `t_8b727d46`, default profile)
**Date:** 2026-06-17
**Branch reviewed:** `feat/billing-page` (commit `37c970b`, marketing pages already merged in via `b15ce6d`, `36e02e9`)
**Scope:** Public marketing site — root `/` (auth gate), `/pricing`, `/how-it-works`, `/security`
**Method:** Headless Chromium (Playwright) at 1440×900 and 390×844 viewports; `vision_analyze` on every full-page and above-fold capture; Lighthouse 13.3.0 for accessibility scoring.

> **Up-front path mismatch.** The task body references "the marketing app (`apps/marketing/`)" but no such directory exists. The marketing surface is the public side of the Next.js app at `apps/portal/` — the four routes `layout.tsx` calls out as "Marketing-site header. Public-only pages (`/`, `/pricing`, `/how-it-works`, `/security`)" in `apps/portal/src/app/layout.tsx`. Reviewed those four routes.

---

## 1. Top-line verdict

The marketing site is **not production-ready for paid traffic**. The most important issue is structural: the root route `/` is a sign-in card, not a landing page. Visitors who land on the home URL see a magic-link auth form with no value proposition, no hero, and no path to learn about the product. The three real marketing pages (`/pricing`, `/how-it-works`, `/security`) exist and have solid content, but **none of them has a primary call-to-action above the fold** — the only clickable "next step" in the visible viewport is the `/pricing` link in the header nav.

Lighthouse accessibility passes the 95 target on `/` (98) and `/security` (96), but **`/pricing` and `/how-it-works` both score 94** because the primary blue CTA button (`#4f8cff` background, white text) measures 3.21:1 — fails WCAG AA (4.5:1 for normal text, 3:1 for large text; 16px is not large text).

Dark mode loads with **no FOUC** (good). Header nav links on mobile are all 28px tall and the auth form CTAs are 38–42px — both fail the 44px tap-target minimum on every public page. There is no theme toggle, no currency toggle, and no `data-theme` / `<meta name="color-scheme">` declared.

---

## 2. Screenshots

All captures are in `docs/audit/screenshots/`. The pages below embed the desktop fold and the mobile fold; full-page captures are linked.

| Page | Desktop fold | Mobile fold | Full-page |
| --- | --- | --- | --- |
| `/` (home / auth) | `screenshots/home_desktop_fold.png` | `screenshots/home_mobile_fold.png` | `screenshots/home_desktop.png`, `home_mobile.png` |
| `/pricing` | `screenshots/pricing_desktop_fold.png` | `screenshots/pricing_mobile_fold.png` | `screenshots/pricing_desktop.png`, `pricing_mobile.png` |
| `/how-it-works` | `screenshots/how-it-works_desktop_fold.png` | `screenshots/how-it-works_mobile_fold.png` | `screenshots/how-it-works_desktop.png`, `how-it-works_mobile.png` |
| `/security` | `screenshots/security_desktop_fold.png` | `screenshots/security_mobile_fold.png` | `screenshots/security_desktop.png`, `security_mobile.png` |
| Dark-mode load probe | `screenshots/home_dark_load.png` | — | (settled) `screenshots/home_dark_settled.png` |

**Live site preview (where the dev server was running):** `http://localhost:3456/` on the local `feat/billing-page` checkout. The live `ai-billing-audit.ashbi.ca` was not in scope of this review (no production access from this worker).

---

## 3. Per-page findings

### 3.1 `/` — the home route is an auth gate, not a landing page

**Vision verdict.** The home page renders only: header nav (Home / Pricing / How it works / Security), a centered "Sign in" card with a magic-link email field, and the Next.js dev indicator in the corner. **No hero, no value prop, no marketing CTA, no social proof, no footer.** The header brand mark "AI Pre-Bill Audit" is the only context a visitor gets.

**Hero value-prop read in <5s — FAIL.** There is no hero. The largest text in the visible viewport is "Sign in" (28–32px), which is a form label, not a value proposition. A first-time visitor cannot determine the product's purpose in any timeframe.

**Primary CTA above the fold — PARTIAL / MISLEADING.** The visible CTA is the "Send magic link" button, which is the sign-in action, not a marketing action. A first-time visitor has no path to *learn* about the product; they're dropped directly into authentication. This is a conversion-killer for paid traffic.

**Pricing teaser visibility — N/A (no hero exists).** The only path to pricing is the nav-bar link.

**Layout / visual issues observed by vision:**
- 60–70% of the viewport above the sign-in card is empty dark space (no hero, illustration, or supporting content).
- Next.js dev-mode indicator (`N` badge) is visible — would not appear in production.
- No footer; no legal links.
- No "Sign up" / "Create account" path distinct from sign-in.

**Source files:** `apps/portal/src/app/page.tsx` (66 lines — the default `create-next-app` starter, untouched). The custom branding, the auth flow, and the `site-header` from `layout.tsx` are layered on top of the starter.

---

### 3.2 `/pricing` — solid content, but CTA contrast fails and USD is struck through

**Vision verdict.** Three pricing tiers render cleanly with clear CAD price, "Most clinics" badge on the Mid Clinic tier, and feature lists with green checkmarks. The subheading ("Flat monthly fees, volume-bracketed. Built for Canadian and US clinics that need a billing-audit engine without per-claim revenue share.") reads as a clear value proposition.

**Hero value-prop read in <5s — PASS.** Subheading is specific (audience, model, differentiator).

**Primary CTA above the fold — PASS (functional, FAIL on contrast).** Three "Start CAD plan" + three "Start USD plan" buttons all sit above the fold. Mid Clinic's "Start CAD plan" is the primary-styled button (solid `#4f8cff` fill).

**Pricing teaser visibility — N/A (this is the pricing page).** The header nav `/pricing` link is present and highlighted as current.

**Layout / visual issues:**
- **Strikethrough on USD price** (`$369`, `$1,109`, `$2,219`) reads as "old / discontinued" — almost certainly a copy/design mistake. Convention says strikethrough = sale price, unavailable, or deprecated. With CAD struck-through-equivalent logic this just looks wrong.
- **Two CTAs per tier** is a workaround for missing currency toggle. A single CTA + currency switcher above the tier grid would be cleaner and reduce decision fatigue.
- **Only Mid Clinic CTA is filled-styled** — the Small Practice and Large Practice primary CTAs render as outline buttons, which de-emphasises them. If only one tier is meant to be visually primary, the design is right; if all three are equal-priority plans, all three should be filled.
- **"Most clinics" badge** sits at the top-left of the Mid Clinic card and partially overlaps the card border.
- **Chat/profile `N` widget** in the bottom-left overlaps the footer copy (visible in the desktop full-page capture).

**Lighthouse a11y:** **94** — fails on `color-contrast` (CTA button 3.21:1, needs 4.5:1 for 14px text or 3:1 for ≥18px / ≥14px-bold). WCAG AA fail.

---

### 3.3 `/how-it-works` — clearest hero of the four, no CTA

**Vision verdict.** Strongest page of the four. Hero reads "Three steps. Your claims, checked before they go out." with a clear subheading. Three numbered cards (Connect your EHR → AI audits every claim pre-bill → Your billing team reviews) each have a custom diagram/mockup, a description, and a bulleted feature list. The visuals are well done and on-brand.

**Hero value-prop read in <5s — PASS.** Single-sentence headline is specific, audience-clear, and time-bounded ("Three steps").

**Primary CTA above the fold — FAIL.** No CTA button is visible in the desktop fold. Visitors must scroll past three full step cards before reaching the bottom-of-page CTA section. For an above-the-fold CTA target on a marketing page, this is a significant funnel leak.

**Pricing teaser visibility — PASS.** The header nav `/pricing` link is visible above the fold. There is no in-hero "See pricing" button.

**Layout / visual issues:**
- Step 2's last bullet ("NCCI conflicts — two codes that can't be…") is clipped at the desktop fold — minor, but the fold break mid-bullet feels unpolished.
- `N` chat widget overlaps content at the bottom of the page on mobile.
- The CTA section at the bottom (the one Lighthouse flagged for contrast) is reached only after ~2000px of scroll on desktop.

**Lighthouse a11y:** **94** — same `#4f8cff` CTA contrast issue as pricing.

---

### 3.4 `/security` — credible content, missing certifications and CTA

**Vision verdict.** Hero is "How we handle your data, your claims, and your risk" with a subheading aimed at healthcare buyers. Three numbered cards visible above the fold cover data residency (AWS `ca-central-1` / `us-east-1` named explicitly), encryption (AES-256 at rest, TLS 1.3 in transit, mTLS internal), and BAA / HIC-Agent agreements. Structure is right; tone is right.

**Hero value-prop read in <5s — PARTIAL.** Headline is descriptive, not benefit-led. "How we handle your data, your claims, and your risk" tells the reader what the page *is*, not why they should care. A buyer-led reframe like "PHIPA / HIPAA compliance without the legal-review marathon" would land harder. The subheading helps.

**Primary CTA above the fold — FAIL.** No CTA in the visible viewport. The subheading mentions a "PDF one-pager for your privacy officer and procurement team" but the link is not surfaced in the hero — it's at the bottom of the page (the Lighthouse-flagged `security.pdf` CTA button).

**Pricing teaser visibility — PASS** (header nav).

**Layout / visual issues:**
- **No SOC 2 / HITRUST / ISO 27001 mention** anywhere visible. Healthcare procurement will look for these. Even "SOC 2 Type II in progress" or "self-attested against ISO 27001 Annex A controls" would be stronger than silence.
- **No customer logos / trust badges** in the visible area.
- **Audit logging section is below the fold** (it is the next numbered card after BAA) — given that audit logging is one of the most-asked questions for healthcare SaaS buyers, it's a missed opportunity to surface it higher.

**Lighthouse a11y:** **96** — passes the 95 target. Same `#4f8cff` contrast issue on the bottom CTA but it didn't drop the score (it is a 14px button which is borderline-large; large-text contrast threshold of 3:1 may have been met — Lighthouse flagged it on `pricing` and `how-it-works` for the same `3.21` value but only scored them at 94. The numerical difference in the report is the additional category weight; the underlying color-contrast fail is the same. Treat this as a real fail across all three pages where the blue button is used.)

---

## 4. Cross-cutting findings

### 4.1 No dark-mode toggle / theme infrastructure

The dev server was hit with `color_scheme: "dark"` to test whether the dark theme is a real theme or just the only theme. The result: the page renders dark correctly on first paint, and `recompute` after `reload()` shows identical background color (`rgb(10, 10, 10)`). **No FOUC observed**, no white flash, no unstyled content. That part is good.

What is missing:
- **No toggle UI** in the DOM. The only `<button>` on the home page is "Send magic link" (the auth submit).
- **No `data-theme` attribute** on `<html>` or any theme container.
- **No `<meta name="color-scheme">` tag** declared, so the browser's form-control scrollbars and inputs may render with browser-default colors in some cases.
- **The current dark palette appears to be the only palette** — there is no light-mode stylesheet. This is a design choice, not a defect, but it should be documented and intentional. The security page references "the PDF one-pager" which would conventionally be light-themed; if a light theme is ever added later, the markup should be ready for it.

**Verdict:** No FOUC; the page just is dark. There is no theme switching, no light-mode fallback.

### 4.2 Mobile horizontal scroll: clean

`document.documentElement.scrollWidth` ≤ `clientWidth` on all four pages at 390px. No horizontal scrollbar. Layouts reflow correctly.

### 4.3 Mobile tap targets: 35 fails across 4 pages

Audit JSON records 35 small tap targets at 390px. The unique failing targets are:

| Element | Size | Where | Gap |
| --- | --- | --- | --- |
| "Skip to content" link | 148×38 | All 4 pages (header) | h=38, needs ≥44 |
| "AI Pre-Bill Audit" brand mark | 118×18 | All 4 pages (header) | h=18 (way under) |
| Nav links "Home" / "Pricing" / "How it works" / "Security" (header) | 28px tall | All 4 pages | h=28, needs ≥44 |
| Footer nav links (rendered at 20px tall) | 20px tall | All 4 pages | h=20, needs ≥44 |
| "Send magic link" auth button | 260×42 | Home | h=42, needs ≥44 (1px short) |
| "Start CAD plan" / "Start USD plan" pricing buttons | 142×39 | Pricing | h=39, needs ≥44 |
| `legal@ai-billing-audit.ashbi.ca` mailto | 237×41 | Footer | h=41, needs ≥44 |

**Pattern:** the entire header is built for desktop (28px-tall links) and a few footer CTAs fall just short of 44px. The auth form's primary CTA is 1 pixel short of 44. The pricing CTAs are 5px short. The legal mailto is 3px short.

### 4.4 Header nav on mobile: cramped, no hamburger fallback

The four nav links render in a single horizontal row at 390px wide. They fit (barely) but with no breathing room. Adding even one more link (About, Contact, Login, Blog) will overflow. A hamburger menu at <640px is the standard fix and would also let the brand mark breathe.

### 4.5 Skip-link target missing (all 4 pages)

Lighthouse flagged `body > a.skip-link` with the message "No skip link target" on every page. The link points to `#main`, but no element on any of the four pages has `id="main"`. The portal pages (`/dashboard`, `/encounters`, etc.) likely do, but the marketing pages do not. Either add `id="main"` to the `<main>` element on the marketing pages, or change the skip link to point at a real anchor.

### 4.6 Blue CTA contrast is the single biggest a11y miss

`#4f8cff` background with white text measures 3.21:1. WCAG AA needs 4.5:1 for body text and 3:1 for large text (≥18px regular or ≥14px bold). The pricing CTA is 14px regular (fails both), the how-it-works CTA is 16px regular (fails 4.5:1, borderline 3:1 large-text rule). **All three marketing pages with the blue button need either a darker blue (`#2563eb` or darker) or a different treatment for body-text-size CTAs.** This is the only Lighthouse rule that has a hard numerical fix.

### 4.7 No footer legal/trust layer on home

The sign-in page at `/` has no footer at all. The other three pages have a footer with a `legal@` mailto and a copyright line. The home page being a sign-in form is structurally a problem before it is a UI problem — visitors from paid acquisition channels will land on the sign-in form and have no recourse to learn more, no link to pricing from the form, no privacy/terms links visible.

### 4.8 Next.js dev-mode `N` indicator visible in captures

The dev server's floating `N` widget is in the bottom-left of every screenshot. This is a dev-only artifact (not in production builds) and is not a real defect, but it is captured in every screenshot above. In a production build, it would not appear.

---

## 5. Lighthouse accessibility scores

Run with `lighthouse 13.3.0 --only-categories=accessibility --output=json` against `http://localhost:3456/...` on the local `feat/billing-page` checkout.

| Page | Score | Pass / fail (≥95) | Failing audits |
| --- | --- | --- | --- |
| `/` (home) | **98** | PASS | `skip-link` (target missing) |
| `/pricing` | **94** | FAIL | `color-contrast` (CTA 3.21:1), `skip-link` |
| `/how-it-works` | **94** | FAIL | `color-contrast` (CTA 3.21:1), `skip-link` |
| `/security` | **96** | PASS | `color-contrast` (bottom CTA 3.21:1, weight passes), `skip-link` |

**Headline:** two of four pages miss the 95 accessibility target. The fix is one variable (the blue button color). Raw JSON reports are in `audit/lighthouse/`.

---

## 6. Ranked fix list (by user impact)

Each item is tied to a specific finding above. Effort estimates are rough: S = <30 min, M = 1–2 hours, L = 2+ hours / design work.

### High impact (do first)

1. **[HIGH] Build a real landing page at `/`.** The home route is currently the default `create-next-app` boilerplate with a sign-in card. Replace `apps/portal/src/app/page.tsx` (66 lines) with a marketing landing page: hero with value prop + primary CTA ("Start free trial" or "Book a 15-min demo"), social proof, three-feature highlight, and a final CTA. Effort: L (this is the actual product work). Without this, paid traffic is wasted. (Finding 3.1)

2. **[HIGH] Add primary CTAs above the fold on `/how-it-works` and `/security`.** Both pages have no above-the-fold CTA. Add a "See pricing" or "Book a demo" button to the hero. Effort: S. (Findings 3.3, 3.4)

3. **[HIGH] Fix the `#4f8cff` blue CTA contrast.** Single-variable change: darken the blue to `#2563eb` or `#1d4ed8` and re-test. This is the only Lighthouse a11y blocker and applies to pricing, how-it-works, and security pages. Effort: S. (Finding 4.6)

4. **[HIGH] Fix the skip-link target.** Add `id="main"` to the `<main>` element on every marketing page (or move the skip link to a target that exists). Effort: S. (Finding 4.5)

### Medium impact

5. **[MED] Add SOC 2 / HITRUST / ISO 27001 mention to `/security`.** Even "SOC 2 Type II in progress" is better than silence for healthcare procurement. Effort: S–M (content). (Finding 3.4)

6. **[MED] Move audit-logging section higher on `/security`.** It's currently the 4th numbered card (below the fold). Audit logging is a top-3 buyer question for healthcare SaaS. Effort: S. (Finding 3.4)

7. **[MED] Replace the strikethrough on USD prices on `/pricing`.** Strikethrough reads as "old / unavailable" and is almost certainly a copy/design mistake. Render USD at the same weight as CAD with smaller font, or show only one currency at a time via a toggle. Effort: S. (Finding 3.2)

8. **[MED] Add a real currency toggle on `/pricing`.** Two CTAs per tier is a workaround. A single "Start plan" CTA + a CAD/USD switcher above the tier grid is cleaner. Effort: M. (Finding 3.2)

9. **[MED] Add a mobile hamburger menu.** Current header crams four links into 390px with no breathing room. Hamburger at <640px. Effort: M. (Finding 4.4)

10. **[MED] Bring CTA button heights to ≥44px on mobile.** Auth "Send magic link" 42→44, pricing "Start * plan" 39→44, footer mailto 41→44. Two-line text changes in each `*.module.css`. Effort: S per file. (Finding 4.3)

11. **[MED] Add footer to the home/sign-in page.** Match the other three pages' footer (legal mailto + copyright). Effort: S. (Finding 4.7)

### Low impact

12. **[LOW] Add `<meta name="color-scheme" content="dark">` to the layout.** Makes the browser render scrollbars and form controls in dark-mode-correct colors and helps with native autofill. Effort: S. (Finding 4.1)

13. **[LOW] Increase the line-height / spacing in `/pricing` feature lists.** Mobile vision flagged the spacing as tight. Effort: S. (Finding 3.2 mobile notes)

14. **[LOW] Document the dark-only design choice.** If the design is intentionally dark-only, state that in `apps/portal/AGENTS.md` or the README so future contributors don't add a light theme by accident. Effort: S. (Finding 4.1)

15. **[LOW] Restyle the "Most clinics" badge on the Mid Clinic card** so it doesn't overlap the card border. Effort: S. (Finding 3.2)

16. **[LOW] Audit what the `N` chat widget is and decide if it ships.** It's in every screenshot. If it's intentional, label it and add an `aria-label`. If it's a debug widget, gate it behind a flag. Effort: S. (Finding 4.8)

---

## 7. Artifacts

All raw artifacts are under `docs/audit/`:

```
docs/audit/
  ui_audit.py                        # Playwright capture script (re-runnable)
  audit.json                         # 24KB — full structured report (CTAs, tap targets, dark-mode probe)
  screenshots/                       # 18 PNGs (full + fold × 4 pages × 2 viewports + 2 dark-mode probes)
  lighthouse/
    home.json                        # 98
    pricing.json                     # 94
    how-it-works.json                # 94
    security.json                    # 96
```

To re-run: from `apps/portal/`, start the dev server (`pnpm dev`) and run `python3 docs/audit/ui_audit.py` against `http://localhost:3456/`. Lighthouse scores re-derive with `lighthouse <url> --only-categories=accessibility --output=json --output-path=<file> --chrome-flags="--headless=new --no-sandbox" --quiet`.
