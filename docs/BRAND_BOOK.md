# Zorva — Brand Book

Status: consolidated reference. Last updated 2026-06-24.
Owner: branding kit (`zorva-branding-kit` board).

This document is the **single consolidated reference** for the Zorva brand.
It links the per-discipline specs (logo, color, typography, voice, imagery,
icons, pitch deck) and presents the at-a-glance rules that anyone producing
a new asset — a slide, a one-pager, an email, a press quote, a partner
deck — must follow.

For full per-discipline detail, see the linked source-of-truth docs. This
brand book summarizes; it does not duplicate.

---

## 1. Brand at a glance

| Attribute        | Value                                                            |
|------------------|------------------------------------------------------------------|
| Name             | Zorva                                                            |
| Category         | Pre-submit AI medical-billing auditor                            |
| Tagline          | Find the revenue your billers are leaving on the table.          |
| Origin           | `docs/BRAND_NARRATIVE.md`                                        |
| Mission          | Zorva catches what is wrong and finds what is missing.           |
| Vision           | A self-improving billing-intelligence layer for every practice.  |
| Primary market   | Alberta AHCIP primary-care clinics                               |
| Voice            | Confident, specific, never hype. See §6.                         |
| Visual register  | Calm, clinical, trustworthy. Teal + charcoal, line illustrations.|

If a new asset can't be tied back to a row in this table, it isn't on-brand
yet.

---

## 2. Logo

Source of truth: `docs/BRANDING_LOGO.md`.

- **Wordmark:** "Zorva" set in Inter 700, title-case, tracking -2%.
  Letters `orva` are charcoal `#1E293B`; the leading **Z** is teal
  `#0D9488`. The teal "Z" alone is the brand-recognition hook.
- **Logomark:** stylized **Z** in white inside a rounded-hex pill filled
  with teal `#0D9488`. Construction grid 24×24. Survives 16×16 favicon.
- **Favicon set:** SVG (light + dark, auto-switching), 16/32/48 PNG,
  32×32 ICO. Files in `apps/portal/public/`.
- **App icons:** hex-pill logomark on solid teal. iOS, Android, macOS
  sizes in `apps/portal/public/app-icons/`. Z occupies ~55% of the safe
  area so iOS squircle doesn't clip the stroke.
- **Clear space:** at least the cap-height of the "Z" on all four sides.
- **Minimum size:** 14 px (wordmark in nav), 16 px (logomark as favicon).
  Print floor: 8 mm cap-height.
- **Don't:** recolor, outline, rotate, skew, drop-shadow, or embed in
  another shape. The hex pill **is** the shape.

---

## 3. Color

Source of truth: `docs/BRANDING_COLORS.md`. Token reference: `globals.css`.

| Family     | Default token      | Hex       | Use                                       |
|------------|--------------------|-----------|-------------------------------------------|
| Primary    | `primary`          | `#0D9488` | Buttons, links, logomark fill, leading Z  |
| Primary    | `primary-dark`     | `#0F766E` | Teal **body text** on light bg (AA-body)  |
| Primary    | `primary-soft`     | `#99F6E4` | Tinted backgrounds only — never for text   |
| Secondary  | `secondary`        | `#D97706` | Review / warning CTAs (AA-large on light)  |
| Secondary  | `secondary-dark`   | `#B45309` | Amber body text on light bg                |
| Surface    | `surface-light`    | `#F8FAFC` | Page background, light mode                 |
| Surface    | `surface-white`    | `#FFFFFF` | Cards, modals (light)                       |
| Surface    | `surface-dark`     | `#0F172A` | Page background, dark mode                  |
| Surface    | `surface-dark-2`   | `#1E293B` | Cards, modals (dark)                        |
| Text       | `--color-text`     | `#334155` | Body text on light (9.90:1, AAA)           |
| Text       | `--color-text`     | `#E2E8F0` | Body text on dark (14.48:1, AAA)            |
| Success    | `success`/`-dark`  | `#059669` / `#047857` | Status: success (icons, body text)|
| Warning    | `warning`/`-soft`  | `#B45309` / `#FEF3C7` | Status: warning                   |
| Error      | `error`/`-dark`    | `#DC2626` / `#B91C1C` | Status: error                     |
| Info       | `info`/`-dark`     | `#2563EB` / `#1D4ED8` | Informational badges only          |

**Neutrals (slate-style ramp):** `neutral-50` → `neutral-900`. Use
`neutral-700` for body on light, `neutral-200` for body on dark. Never
hard-code hex; consume the CSS variable (`var(--color-text)`,
`var(--surface-light)`, etc.) or the typed export in
`apps/portal/src/lib/colors.ts`.

**Fail-fast combinations** (do not use for body text):

- `primary` on white or `surface-light` (3.58–3.74:1). Use
  `primary-dark`.
- `secondary` on white (3.19:1). Use `secondary-dark`.
- `neutral-400` on `surface-light` (2.45:1). Tertiary text only.
- Any `*-soft` token against white or `surface-light` — backgrounds, not
  text colors.

**Why teal + amber:** teal reads clinical and trustworthy (and avoids the
cold-blue Stripe/Linear fintech look and the green Epic/Cerner EHR look).
Amber is the action color for "review this" without the alarm of red.

---

## 4. Typography

Source of truth: `docs/BRANDING_TYPOGRAPHY.md`. CSS variables in
`globals.css`.

| Role        | Family           | Token              | Use                                  |
|-------------|------------------|--------------------|--------------------------------------|
| Display     | Inter 600/700/800| `--type-display-*` | Marketing hero, pitch-deck cover     |
| Text        | Inter 400/500/600/700 | `--type-h1` … `--type-body` | All UI, body, headings     |
| Monospace   | JetBrains Mono   | `--type-code`      | Code, JSON, audit traces             |

**Scale (geometric, ×1.25):**

| Token                | Size / lh / weight        | Used for                  |
|----------------------|---------------------------|---------------------------|
| `--type-display-2xl` | 60 / 1.10 / 700           | Pitch-deck cover          |
| `--type-display-xl`  | 48 / 1.15 / 700           | Page hero (`h1`)           |
| `--type-display-lg`  | 36 / 1.20 / 700           | Section hero              |
| `--type-h1`          | 30 / 1.25 / 700           | Page title                |
| `--type-h2`          | 24 / 1.30 / 600           | Section title             |
| `--type-h3`          | 20 / 1.35 / 600           | Subsection                |
| `--type-h4`          | 18 / 1.40 / 600           | Card title                |
| `--type-body-lg`     | 18 / 1.50 / 400           | Lead paragraph            |
| `--type-body`        | 16 / 1.50 / 400           | Body (default)            |
| `--type-body-sm`     | 14 / 1.50 / 400           | Captions, helper text     |
| `--type-caption`     | 12 / 1.45 / 500           | Labels, table headers     |
| `--type-code`        | 14 / 1.60 / 400           | Code, JSON, audit traces  |

**Rules:**

- Always reference a `--type-*` token. Never hard-code `font-size:` in
  components.
- Inter only. Don't mix with Helvetica or system-ui.
- Use **weight 600** for emphasis. Don't use Inter italic — its italic is
  a true italic, not a slanted roman, and reads as a different voice.
- Never below 12 px. Lighthouse flags anything smaller.
- Long-form pages (`/security`, `/how-it-works`): `--lh-longform` 1.60.

---

## 5. Imagery

Source of truth: `docs/BRANDING_IMAGERY.md`.

- **v1 imagery is line illustrations**, not photos. Reasons: on-brand
  clinical feel, accessible by default, easy to localize, cheap to extend.
- 3D renders and stock photos are **rejected** for v1.
- **Style:** 1.5 px stroke (1.0 px for secondary detail), round caps &
  joins, no fills on foreground, 24 px construction grid, 2 px corner
  radius, generous curves (no sharp angles), 3-color max per
  illustration.
- **Palette:** stroke in `primary-700` `#0F766E` (or `slate-700` for
  generic, `amber-500` for warning), accent fill in `primary-200`
  `#99F6E4`, background wash `surface-light` `#F8FAFC`.
- **People:** stylized, diverse in skin tone / hair / posture, no
  recognizable faces (dots for eyes, small curve for a smile), always
  shown doing the work — never stock-photo "smiling at camera".
- **Composition:** centered, one focal point, generous whitespace.
- **v1 inventory:** 9 illustrations in `apps/portal/public/illustrations/`
  (hero, three how-it-works steps, three finding-types, empty state,
  security-shield).
- **Where illustrations are NOT used:** audit-results table (severity
  icons only), KPI tiles (numbers + sparkline icons), login / auth,
  error / 500 page. Illustrations carry narrative, not status.
- **Photography (v1.1+, case studies only):** get a written release, use
  the clinic's actual environment, no PHI in the background, a slight
  teal cast on shadows (multiply 10%) to keep it in the brand palette.
  Stored in `assets/case-studies/<clinic-slug>/` (CDN, not git).
- **Accessibility:** every illustration gets an `alt` text (short,
  descriptive) plus body copy that explains the "why". Decorative
  illustrations get `alt=""` and `role="presentation"`. Color is never
  the only carrier of meaning.

---

## 6. Voice

Source of truth: `docs/VOICE.md` and `docs/BRAND_NARRATIVE.md`.

**One line:** Zorva is **confident and specific**. We earn trust by naming
the number, citing the source, and showing our limits — not by reaching
for the superlative. The brand is allowed to be quiet; it is not allowed
to be vague.

**Audience:** clinic billing leads, privacy / compliance officers, and
practice managers. All three are professional, time-poor, and skeptical
of vendor language. Speak the way a senior colleague would speak across a
desk.

**Tone by context:**

| Surface                           | Tone                              |
|-----------------------------------|-----------------------------------|
| Marketing pages (hero, pricing)   | Specific, benefit-led, never hype |
| Technical pages (security, model) | Precise, transparent, never hand-wavy |
| Product UI (audit cards)          | Concise, actionable, never vague  |
| Emails (digest, welcome, follow-up)| Warm, helpful, never pushy       |

**Anchor phrases (ship verbatim when relevant):**

- "catches 6–7 of 10 real billing errors before submission"
- "data stays in a Canadian data centre, region confirmed in the BAA"
- "the biller reviews every finding before the claim goes out"
- "see `docs/security` for the full compliance posture"

**Banned phrases (overclaim / SaaS-fluffy / unverified):**

- "catches all billing errors"
- "saves you thousands"
- "industry-leading accuracy"
- "your data is 100% secure"
- "AI does the billing for you"
- "battle-tested on millions of claims"
- "free trial"
- "works everywhere"
- "HIPAA-certified" *(not true on our current hosting)*
- "self-improving AI"

**Vocabulary — use:** SOMB, AHCIP, F1 / precision / recall (with the
actual number), appeal, Modifier-25, undercode, validation set (with size,
e.g. "10-encounter AHCIP validation set"), BAA, pre-submit.

**Vocabulary — avoid:** "real-time monitoring", "real-time audit",
"guarantees", "up to", "robust", "enterprise-grade", "cutting-edge".

---

## 7. Icons

Source of truth: `docs/BRANDING_ICONS.md`.

- Standardize on **`lucide-react`** (MIT, line-style, ~1,500 icons,
  tree-shakeable, React-native). heroicons and phosphor-react are
  rejected for v1.
- All icons live under `apps/portal/src/components/icons/`: `index.tsx`
  (barrel), `findings.tsx`, `actions.tsx`, `sections.tsx`, `states.tsx`.
- Hard rules: no wildcard re-exports; one component per file; default
  props `size={20}` `strokeWidth={1.5}`; color via `currentColor`.
- Consumers import only from the barrel — never directly from
  `lucide-react`.
- v1 inventory: **38 icons** (32 portal + 6 marketing-only). See the
  source doc for the full table. Anything not in that list shouldn't
  ship in v1.
- Sizing & color: 16 px inline with body (`text-slate-600`); 20 px
  button icon; 24 px section header (`text-primary-700`); 48 px
  empty-state illustration; 96 px hero illustration (`text-primary-500`).
- Severity colors apply **only** to the four severity icons
  (low/medium/high/critical). Other icons stay neutral.

---

## 8. Layout & motion principles

Spinning out of the per-discipline docs, these rules apply whenever a new
surface is built:

- **Spacing scale:** Tailwind default (4 px base). Cards pad 24 px;
  between-section spacing 48–64 px; page max-width 1200 px.
- **Radius:** 6 px on cards, 4 px on inputs/buttons, 9999 px on
  pill-shaped chips.
- **Shadows:** never use a darker-than-`slate-200` shadow on light
  surfaces; depth comes from borders, not from drops. Dark mode: no
  shadows at all — use `surface-dark-2` for elevation.
- **Motion:** transitions ≤ 150 ms. Easing: `cubic-bezier(0.4, 0, 0.2, 1)`.
  No motion on first paint, no motion on background gradients, no
  parallax. Respect `prefers-reduced-motion: reduce` and disable
  non-essential motion.
- **Icon + label alignment:** icon sits 8 px to the left of the label
  baseline; never center-align icon + label pairs.

---

## 9. Asset inventory

| Asset type          | Path                                          | Owner         |
|---------------------|-----------------------------------------------|---------------|
| Wordmark SVG        | `apps/portal/public/wordmark.svg`             | branding kit  |
| Logomark SVG        | `apps/portal/public/icon.svg`                 | branding kit  |
| Favicons (PNG/ICO)  | `apps/portal/public/favicon-*`                | branding kit  |
| App icons           | `apps/portal/public/app-icons/`               | branding kit  |
| Illustrations       | `apps/portal/public/illustrations/`           | branding kit  |
| Email signatures    | `docs/BRANDING_PITCH_DECK.md` §email + html   | branding kit  |
| Social templates    | `apps/portal/public/social/` (LinkedIn, X)    | branding kit  |
| Pitch deck          | `slides/zorva-pitch-deck.*` (10-slide template) | branding kit |
| Exhibitor kit       | `assets/exhibitor/` (booth, banner, one-pager)| branding kit  |
| Case study template | `docs/CASE_STUDY_TEMPLATE.md`                 | branding kit  |

If a new asset class is added (e.g. a webinar lower-third), add a row
here and a source-of-truth doc in `docs/BRANDING_*.md`.

---

## 10. Don't-do list (one-pager)

A condensed version of the per-discipline don'ts for quick reference:

- **Logo:** don't recolor, outline, rotate, drop-shadow, or embed in
  another shape.
- **Color:** don't use `primary` or `secondary` for body text on light
  surfaces. Don't use `*-soft` as text color. Don't introduce a new
  hex.
- **Typography:** don't hard-code `font-size:`. Don't use Inter italic
  for emphasis. Don't go below 12 px.
- **Imagery:** don't use photos on the marketing site or portal. Don't
  fill illustrations with gradients. Don't use more than 3 colors per
  illustration.
- **Voice:** don't ship the banned phrases (see §6). Don't use
  urgency language in emails. Don't quantify a claim without a source.
- **Icons:** don't import from `lucide-react` directly — go through the
  barrel. Don't add an icon that's not in the v1 inventory.
- **Layout:** don't drop-shadow on light surfaces. Don't animate
  background gradients. Don't ignore `prefers-reduced-motion`.

---

## 11. Per-discipline source-of-truth index

Every section above links to a source-of-truth doc. New assets must
follow the source doc, not this summary. If the source and this summary
disagree, the source wins — file an issue to update this book.

| Topic              | Source of truth                                  |
|--------------------|--------------------------------------------------|
| Logo               | `docs/BRANDING_LOGO.md`                          |
| Color              | `docs/BRANDING_COLORS.md`                        |
| Typography         | `docs/BRANDING_TYPOGRAPHY.md`                    |
| Imagery            | `docs/BRANDING_IMAGERY.md`                       |
| Voice              | `docs/VOICE.md`                                  |
| Brand narrative    | `docs/BRAND_NARRATIVE.md`                        |
| Icons              | `docs/BRANDING_ICONS.md`                         |
| Pitch deck         | `docs/BRANDING_PITCH_DECK.md`                    |
| Social templates   | (specs in `docs/BRANDING_PITCH_DECK.md` §social) |
| Email templates    | `docs/BRANDING_PITCH_DECK.md` §email            |
| Email signature    | (template referenced from pitch-deck doc)        |
| Exhibitor kit      | `docs/BRANDING_PITCH_DECK.md` §exhibitor         |
| Case study template| `docs/CASE_STUDY_TEMPLATE.md`                    |
| Internal templates | (template spec referenced from pitch-deck doc)   |
| Glossary terms     | `docs/GLOSSARY.md` (terms we use)                |

---

## 12. Acceptance checklist for a new on-brand asset

Before publishing a new Zorva asset (slide, page, email, doc, illustration,
video, etc.), walk this checklist:

- [ ] The asset is tied to a row in §1 (brand at a glance).
- [ ] The logo is sized correctly with clear space (§2).
- [ ] All colors come from `globals.css` tokens — no raw hex (§3).
- [ ] Body text meets WCAG-AA contrast against its background.
- [ ] Typography goes through `--type-*` tokens — no hard-coded `font-size:`
      (§4).
- [ ] If it contains imagery, it follows the line-illustration rules
      (§5). No photos on the marketing site or portal.
- [ ] Copy is in Zorva voice — specific, sourced, no banned phrases (§6).
- [ ] Icons come from the v1 inventory and are imported from the barrel
      (§7).
- [ ] Motion (if any) is ≤ 150 ms, eased, and respects
      `prefers-reduced-motion` (§8).
- [ ] The asset is reachable from §9 if it represents a new asset class.
- [ ] The don't-do list (§10) is checked off clean.
