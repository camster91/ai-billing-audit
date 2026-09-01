# Zorva — Typography System

Status: reconciled with the implemented portal; exported-asset licensing review remains.
Owner: Cameron Ashley.
Last updated: 2026-09-01.

This document is the **single source of truth** for the Zorva type system:
an editorial display role, a functional text role, two bounded monospace roles,
and the rules for pairing them. Most sizes, weights, and line-heights are
consumed as CSS variables defined in `apps/portal/src/app/globals.css` so
components never hard-code type values.

The goals of the type system:

1. **Read clean at body size on screen** — Inter was designed for that.
2. **Hit WCAG-AA at every size we ship** — minimum 4.5:1 body, 3:1 large.
3. **Be self-hosted in the portal build** — exported assets still require a
   recorded font-source and licence check.
4. **Degrade gracefully** — system fonts if Inter fails to load.

---

## 1. Typefaces

| Role | Family | Implemented weights | Source and boundary |
| --- | --- | --- | --- |
| Marketing editorial display | Fraunces | 400, 500, 600; normal and italic | `next/font/google`; homepage headlines only |
| Product, HQ, forms, body | Inter | variable/default loading | `next/font/google`; functional default |
| Marketing evidence labels | IBM Plex Mono | 400, 500 | `next/font/google`; compact labels only |
| Code and technical traces | JetBrains Mono | default loading | `next/font/google`; real code/identifiers only |

**Why Inter remains the functional default:**

- Loaded through `next/font/google` in the repository. Upstream fonts are
  commonly distributed under SIL Open Font License terms, but the repository
  does not currently archive the licence files required for exported-asset
  provenance; verify and record them before external packaging.
- Designed for screen rendering at body sizes — no stroke contrast tricks
  that disappear at 14 px.
- Legible in the current functional UI at ordinary body sizes. WCAG contrast is
  determined by foreground/background colour and rendered size, not the font
  family; verify it in context (see `BRANDING_COLORS.md`).

**Why Fraunces and IBM Plex Mono are bounded to marketing:** Fraunces gives the
indexable homepage a distinctive editorial voice, while IBM Plex Mono labels
evidence and workflow details. Neither belongs in dense product/HQ controls or
long body copy. This channel contrast preserves recognition without reducing
functional legibility.

**Why JetBrains Mono (not Fira Code):**

- JetBrains Mono ships with programming ligatures (`=>`, `!=`) out of the
  box. Fira Code requires extra build config. JetBrains is the drop-in.
- Used **only** for code snippets on technical pages and audit-detail
  tracebacks. Never for body, headings, or nav.

---

## 2. Type scale

Geometric scale (each step ≈ 1.25× the previous). Designed so that body
(16 px) hits the WCAG-AA minimum legibility threshold, and the smallest
display step (36 px) still has a comfortable reading size.

| Token              | Size  | Line-height | Weight | Letter-spacing | Use                                      |
|--------------------|-------|-------------|--------|----------------|------------------------------------------|
| `--type-display-2xl` | 60 px | 1.10        | 700    | -0.025em       | Marketing hero, pitch-deck cover         |
| `--type-display-xl`  | 48 px | 1.15        | 700    | -0.020em       | Page hero (`h1`)                          |
| `--type-display-lg`  | 36 px | 1.20        | 700    | -0.015em       | Section hero (`h1` on dense pages)        |
| `--type-h1`          | 30 px | 1.25        | 700    | -0.010em       | Page title                                |
| `--type-h2`          | 24 px | 1.30        | 600    | -0.005em       | Section title                             |
| `--type-h3`          | 20 px | 1.35        | 600    | 0              | Subsection                                |
| `--type-h4`          | 18 px | 1.40        | 600    | 0              | Card title                                |
| `--type-body-lg`     | 18 px | 1.50        | 400    | 0              | Lead paragraph                            |
| `--type-body`        | 16 px | 1.50        | 400    | 0              | Body copy (default)                       |
| `--type-body-sm`     | 14 px | 1.50        | 400    | 0              | Captions, helper text                     |
| `--type-caption`     | 12 px | 1.45        | 500    | 0.010em        | Labels, table headers, badges             |
| `--type-code`        | 14 px | 1.60        | 400    | 0              | Code, JSON, audit traces                  |

### Line-height conventions

- **Display (h1 / hero):** 1.10–1.20. Tight, sets the visual rhythm.
- **Headings (h2 / h3 / h4):** 1.25–1.40. Slightly looser.
- **Body:** 1.50. WCAG-recommended for sustained reading.
- **Long-form / docs:** 1.60. Used for `/security` and `/how-it-works`.
- **Code:** 1.60. Matches body, but monospace so it reads as code.

### Weight conventions

- **400 regular:** body, lead paragraphs.
- **500 medium:** captions, labels, table headers — anything that needs a
  slight emphasis without being a heading.
- **600 semibold:** h2, h3, h4, button labels, link hover.
- **700 bold:** h1, display, the "Z" in the wordmark, and emphasis inside
  body (rare — prefer a heading instead).

Never use weight 800+ outside of pitch-deck display sizes. We don't ship the
800 weight by default to keep the font payload small.

---

## 3. Usage rules

| Surface                  | Family    | Token                | Notes                                   |
|--------------------------|-----------|----------------------|------------------------------------------|
| Marketing hero (`h1`)    | Fraunces  | responsive page token | One editorial hierarchy                  |
| Page title (`h1`)        | Inter     | `--type-h1`          | 30 px / 700                              |
| Section title (`h2`)     | Inter     | `--type-h2`          | 24 px / 600                              |
| Card title (`h3`/`h4`)   | Inter     | `--type-h3`/`h4`     |                                          |
| Lead paragraph           | Inter     | `--type-body-lg`     | 18 px / 400                              |
| Body paragraph           | Inter     | `--type-body`        | 16 px / 400                              |
| Button labels            | Inter     | `--type-body-sm`     | 14 px / 600, letter-spacing 0            |
| Captions / table headers | Inter     | `--type-caption`     | 12 px / 500, letter-spacing +0.01em      |
| Code                     | JetBrains Mono | `--type-code`    | 14 px / 400                              |
| Marketing eyebrow/evidence label | IBM Plex Mono | page token | 12 px minimum; short labels only |

**Forbidden:**

- Don't set font-size in components. Always go through a `--type-*` token.
- Don't introduce another family. Use Inter for functional UI, Fraunces for
  bounded marketing display, IBM Plex Mono for marketing labels, and JetBrains
  Mono for real code/technical traces.
- Don't use ALL CAPS for body. ALL CAPS is only allowed for the wordmark
  logo lockup or eyebrow labels (`--type-caption`).
- Don't italicize Inter for functional emphasis. Use weight 600. Fraunces
  italic is permitted only as a short editorial headline accent.
- Don't go below 12 px. Lighthouse flags anything smaller as a11y-fragile.

---

## 4. CSS variables — globals.css

These declarations are appended to `apps/portal/src/app/globals.css` (next to
the color vars from BRANDING_COLORS.md):

```css
:root {
  /* font families (set by next/font in layout.tsx as --font-sans / --font-mono) */
  --font-sans: var(--font-inter, ui-sans-serif, system-ui, -apple-system,
                    "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
  --font-mono: var(--font-jetbrains-mono, ui-monospace, SFMono-Regular,
                    "JetBrains Mono", Menlo, Consolas, monospace);

  /* size scale — geometric (×1.25) */
  --type-display-2xl: 60px;
  --type-display-xl:  48px;
  --type-display-lg:  36px;
  --type-h1:          30px;
  --type-h2:          24px;
  --type-h3:          20px;
  --type-h4:          18px;
  --type-body-lg:     18px;
  --type-body:        16px;
  --type-body-sm:     14px;
  --type-caption:     12px;
  --type-code:        14px;

  /* line-height tokens */
  --lh-display:  1.15;
  --lh-heading:  1.30;
  --lh-body:     1.50;
  --lh-longform: 1.60;
  --lh-code:     1.60;
}
```

The CSS classes (defined in `globals.css` alongside the vars) consume
those tokens:

```css
body {
  font-family: var(--font-sans);
  font-size: var(--type-body);
  line-height: var(--lh-body);
  color: var(--color-text);
}

h1, .h1 { font-size: var(--type-h1);          font-weight: 700; line-height: var(--lh-heading); }
h2, .h2 { font-size: var(--type-h2);          font-weight: 600; line-height: var(--lh-heading); }
h3, .h3 { font-size: var(--type-h3);          font-weight: 600; line-height: var(--lh-heading); }
h4, .h4 { font-size: var(--type-h4);          font-weight: 600; line-height: var(--lh-heading); }

.display-2xl { font-size: var(--type-display-2xl); font-weight: 700; line-height: var(--lh-display); letter-spacing: -0.025em; }
.display-xl  { font-size: var(--type-display-xl);  font-weight: 700; line-height: var(--lh-display); letter-spacing: -0.020em; }
.display-lg  { font-size: var(--type-display-lg);  font-weight: 700; line-height: var(--lh-display); letter-spacing: -0.015em; }

.body-lg { font-size: var(--type-body-lg); font-weight: 400; line-height: var(--lh-body); }
.body    { font-size: var(--type-body);    font-weight: 400; line-height: var(--lh-body); }
.body-sm { font-size: var(--type-body-sm); font-weight: 400; line-height: var(--lh-body); }
.caption { font-size: var(--type-caption); font-weight: 500; line-height: 1.45; letter-spacing: 0.010em; }

code, pre, .code {
  font-family: var(--font-mono);
  font-size: var(--type-code);
  line-height: var(--lh-code);
}
```

---

## 5. Loading — `apps/portal/src/app/layout.tsx`

The portal's `RootLayout` already loads Geist via `next/font/google`. We
add Inter and JetBrains Mono alongside it so they coexist. Inter becomes the
default `body` font; Geist is kept available on `--font-geist-sans` so any
existing component that references it doesn't break. JetBrains Mono gets a
new `--font-jetbrains-mono` variable consumed by `code`.

**Patch summary** (no functional change to existing wiring):

- Add `Inter` from `next/font/google` → variable `--font-inter`.
- Add `JetBrains_Mono` from `next/font/google` → variable
  `--font-jetbrains-mono`.
- Set `<html className={`${inter.variable} ${jetbrainsMono.variable}
  ${geistSans.variable} ${geistMono.variable}`}>`.
- Set `<body className="body">` so the new body rules take effect.

The existing `<header>` wordmark text is NOT changed here — that's the
logo task's job (BRANDING_LOGO.md).

---

## 6. Contrast verification

Body text (`--type-body`, 16 px / 400) on:

- `--color-text` (`#334155`) on `--surface-light` (`#F8FAFC`) → **9.90:1** ✓ AAA
- `--color-text` (`#E2E8F0`) on `--surface-dark` (`#0F172A`) → **14.48:1** ✓ AAA
- `--color-text-muted` (`#64748B`) on `--surface-light` → **4.55:1** ✓ AA-body

Captions (`--type-caption`, 12 px / 500) on light surface: `neutral-500` is
4.55:1 — passes AA-body for normal text but **fails** at 12 px if the
caption is non-essential. Use `neutral-600` (7.24:1) for required captions.

Headings (`--type-h1`, 30 px / 700) — large text threshold (3:1) is easily
met by `neutral-900` (17.06:1).

Full contrast matrix is in [`BRANDING_COLORS.md`](./BRANDING_COLORS.md).

---

## 7. Acceptance gates

- [ ] `layout.tsx` loads Inter via `next/font/google` and exposes
      `--font-inter` to CSS.
- [ ] `layout.tsx` loads JetBrains Mono and exposes
      `--font-jetbrains-mono`.
- [ ] `body` in `globals.css` consumes `var(--font-sans)`.
- [ ] All headings use `--type-h1` through `--type-h4` (or
      `--type-display-*` for hero).
- [ ] Lighthouse "Document doesn't use legible font sizes" passes.
- [ ] No raw `font-size:` in components (except inside `.module.css` files
      that genuinely need it — and those should reference the var, not a px
      value).

---

## 8. Out of scope

- Spacing, motion, color — handled in their own docs.
- Migrating other apps in the monorepo — this task is portal-only.
- Adding Inter italic, weight 800, or alternate scripts.
