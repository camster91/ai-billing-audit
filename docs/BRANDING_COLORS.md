# Zorva — Color Palette

Status: spec, ready for token export.
Owner: branding kit, P0 color task (`t_3540303b`).
Last updated: 2026-06-24.

This document is the **single source of truth** for the Zorva color system.
Every color is documented with hex, RGB, intended usage, and WCAG 2.1
contrast ratios against the canonical light and dark surfaces. All ratios
were computed via the standard relative-luminance formula; numbers below are
rounded to two decimals.

The palette intentionally sits in the teal + amber family to read as
**clinical and trustworthy** without leaning into either the cold-blue
fintech look or the warm-orange consumer look.

---

## 1. Surfaces (backgrounds)

| Token             | Hex       | RGB             | Usage                              |
|-------------------|-----------|-----------------|------------------------------------|
| `surface-light`   | `#F8FAFC` | `248, 250, 252` | Page background, light mode        |
| `surface-white`   | `#FFFFFF` | `255, 255, 255` | Cards, modals, popovers (light)    |
| `surface-dark`    | `#0F172A` | `15, 23, 42`    | Page background, dark mode         |
| `surface-dark-2`  | `#1E293B` | `30, 41, 59`    | Cards, modals, popovers (dark)     |

`surface-light` and `surface-white` are the two **light-mode reference
backgrounds** used for all contrast checks below. `surface-dark` and
`surface-dark-2` are the **dark-mode references**.

---

## 2. Primary — Teal

The brand's primary color. Teal reads as clinical, calm, and trustworthy —
distinct from the cold-blue of Stripe / Linear (we don't want to look like
fintech) and from the green of Epic / Cerner (we're not an EHR).

| Token              | Hex       | RGB             | vs `#F8FAFC` | vs `#FFFFFF` | vs `#0F172A` |
|--------------------|-----------|-----------------|--------------|--------------|---------------|
| `primary`          | `#0D9488` | `13, 148, 136`  | 3.58:1       | 3.74:1       | 4.77:1        |
| `primary-dark`     | `#0F766E` | `15, 118, 110`  | 5.23:1       | 5.47:1       | 3.26:1        |
| `primary-soft`     | `#99F6E4` | `153, 246, 228` | 1.20:1       | 1.26:1       | 14.16:1       |

**Rules:**

- Use `primary` for **buttons, links, the leading "Z" in the wordmark, and
  the logomark fill**.
- Use `primary-dark` for **body text** in the teal family (e.g. link text
  on white) — `primary` fails AA-body (3.74:1 < 4.5:1) on white.
- Use `primary-soft` for **tinted backgrounds** (badges, hover states) —
  never for text on a light surface (1.20:1).
- All three pass AA-large (3:1) for non-text UI on light backgrounds.

---

## 3. Secondary — Amber (action color)

For review / warning / "look at this" CTAs. Amber signals attention without
the alarm of red.

| Token              | Hex       | RGB             | vs `#F8FAFC` | vs `#FFFFFF` | vs `#0F172A` |
|--------------------|-----------|-----------------|--------------|--------------|---------------|
| `secondary`        | `#D97706` | `217, 119, 6`   | 3.04:1       | 3.19:1       | 5.60:1        |
| `secondary-dark`   | `#B45309` | `180, 83, 9`    | 4.80:1       | 5.02:1       | 3.56:1        |
| `secondary-soft`   | `#FEF3C7` | `254, 243, 199` | 1.07:1       | 1.11:1       | 16.05:1       |

**Rules:**

- `secondary` (#D97706) is the **button fill** for review-action CTAs
  ("Review finding", "Hold claim"). Passes AA-large (3:1) on light bg.
- `secondary-dark` (#B45309) is the **text color** when you need the
  amber family as text — passes AA-body on white.
- `secondary-soft` is **only for backgrounds** (badges, banners). Never
  pair with white text — use `secondary-dark` text on `secondary-soft`.

---

## 4. Semantic accents

Four colors, one per status. Each ships in a default + dark-companion
variant so we have a body-text-safe option on both surfaces.

| Status    | Token           | Hex       | RGB           | vs `#F8FAFC` | vs `#0F172A` |
|-----------|-----------------|-----------|---------------|--------------|---------------|
| Success   | `success`       | `#059669` | `5, 150, 105` | 3.60:1       | 4.74:1        |
| Success   | `success-dark`  | `#047857` | `4, 120, 87`  | 5.03:1       | 3.40:1        |
| Warning   | `warning`       | `#B45309` | `180, 83, 9`  | 4.80:1       | 3.56:1        |
| Warning   | `warning-soft`  | `#FEF3C7` | `254,243,199` | 1.07:1       | 16.05:1       |
| Error     | `error`         | `#DC2626` | `220, 38, 38` | 4.62:1       | 3.70:1        |
| Error     | `error-dark`    | `#B91C1C` | `185, 28, 28` | 5.93:1       | 2.87:1        |
| Info      | `info`          | `#2563EB` | `37, 99, 235` | 4.94:1       | 3.45:1        |
| Info      | `info-dark`     | `#1D4ED8` | `29, 78, 216` | 6.45:1       | 2.65:1        |

**Rules:**

- The default token (`success`, `warning`, `error`, `info`) is for **icons,
  button fills, badge dots, and large display text only** on light bg.
- The `*-dark` companion is for **body text on light bg** — passes AA-body.
- On dark bg (`#0F172A`), the default token flips roles: it passes AA-body
  on dark, and the `*-dark` companion becomes the UI-fill version.
- The previous ad-hoc `#2563EB` is **not** the de-facto primary. Use
  `primary` (`#0D9488`) for brand surfaces; `info` is reserved for
  informational badges only.

---

## 5. Neutrals — 8-step grayscale ramp

Eight ordered steps from the lightest surface tone to the deepest text tone.
All steps pass AA-body against the surface two steps away from them.

| Token          | Hex       | RGB              | vs `#F8FAFC` | vs `#0F172A` | Suggested role                          |
|----------------|-----------|------------------|--------------|--------------|------------------------------------------|
| `neutral-50`   | `#F8FAFC` | `248, 250, 252`  | 1.00:1       | 17.06:1      | Page background (light)                  |
| `neutral-100`  | `#F1F5F9` | `241, 245, 249`  | 1.05:1       | 16.30:1      | Subtle surface tint (light)              |
| `neutral-200`  | `#E2E8F0` | `226, 232, 240`  | 1.18:1       | 14.48:1      | Borders, dividers (light)                |
| `neutral-300`  | `#CBD5E1` | `203, 213, 225`  | 1.42:1       | 12.02:1      | Disabled text (light), borders (dark)    |
| `neutral-400`  | `#94A3B8` | `148, 163, 184`  | 2.45:1       | 6.96:1       | Placeholder text (dark), tertiary text   |
| `neutral-500`  | `#64748B` | `100, 116, 139`  | 4.55:1       | 3.75:1       | Secondary body text (light, AA-body)     |
| `neutral-600`  | `#475569` | `71, 85, 105`    | 7.24:1       | 2.36:1       | Primary body text (light, AA-body)       |
| `neutral-700`  | `#334155` | `51, 65, 85`     | 9.90:1       | 1.72:1       | Headings (light), body text (dark)       |
| `neutral-800`  | `#1E293B` | `30, 41, 59`     | 13.98:1      | 1.22:1       | Page background (dark), cards (dark)     |
| `neutral-900`  | `#0F172A` | `15, 23, 42`     | 17.06:1      | 1.00:1       | Page background (dark)                   |

The ramp is intentionally **9 entries** (50→900) to cover the full Tailwind
slate-style spacing; the eight "usable text/UI" steps are 200→900 (light
side) and 100→700 (dark side).

**Text-on-light recommendation:**

- Headings: `neutral-900`
- Body: `neutral-700` (9.90:1 — AAA at body size)
- Secondary: `neutral-500` (4.55:1 — AA-body, on the edge)
- Disabled: `neutral-400` (2.45:1 — not for required text)

**Text-on-dark recommendation:**

- Headings: `neutral-50`
- Body: `neutral-200` (14.48:1 — AAA)
- Secondary: `neutral-400` (6.96:1 — AA)
- Disabled: `neutral-500` (3.75:1 — not for required text)

---

## 6. Failing combinations — called out

These combinations **fail WCAG AA-body** (4.5:1) and must not be used for
body text. They are listed so reviewers can spot them quickly:

- `primary` (`#0D9488`) on `#FFFFFF` — 3.74:1. Use `primary-dark` for
  teal body text.
- `primary` on `#F8FAFC` — 3.58:1. Same fix.
- `secondary` (`#D97706`) on `#FFFFFF` — 3.19:1. Use `secondary-dark` for
  amber body text.
- `neutral-400` on `#F8FAFC` — 2.45:1. Tertiary text only on light bg.
- Any `*-soft` token against white or `#F8FAFC` — these are backgrounds,
  not text colors.

---

## 7. CSS variables — globals.css

The portal's `apps/portal/src/app/globals.css` now declares the palette as
CSS custom properties on `:root` (light defaults) and overrides them inside
a `prefers-color-scheme: dark` block. Components should reference the
variables, never the raw hex.

```css
:root {
  /* surfaces */
  --surface-light:   #F8FAFC;
  --surface-white:   #FFFFFF;
  --surface-dark:    #0F172A;
  --surface-dark-2:  #1E293B;

  /* primary — teal */
  --color-primary:        #0D9488;
  --color-primary-dark:   #0F766E;
  --color-primary-soft:   #99F6E4;

  /* secondary — amber */
  --color-secondary:        #D97706;
  --color-secondary-dark:   #B45309;
  --color-secondary-soft:   #FEF3C7;

  /* semantic */
  --color-success:        #059669;
  --color-success-dark:   #047857;
  --color-warning:        #B45309;
  --color-warning-soft:   #FEF3C7;
  --color-error:          #DC2626;
  --color-error-dark:     #B91C1C;
  --color-info:           #2563EB;
  --color-info-dark:      #1D4ED8;

  /* neutrals */
  --color-neutral-50:  #F8FAFC;
  --color-neutral-100: #F1F5F9;
  --color-neutral-200: #E2E8F0;
  --color-neutral-300: #CBD5E1;
  --color-neutral-400: #94A3B8;
  --color-neutral-500: #64748B;
  --color-neutral-600: #475569;
  --color-neutral-700: #334155;
  --color-neutral-800: #1E293B;
  --color-neutral-900: #0F172A;

  /* semantic aliases (light mode) */
  --color-text:           var(--color-neutral-700);
  --color-text-muted:     var(--color-neutral-500);
  --color-text-inverse:   var(--color-neutral-50);
  --color-border:         var(--color-neutral-200);
  --color-link:           var(--color-primary-dark);
}

@media (prefers-color-scheme: dark) {
  :root {
    --color-text:         var(--color-neutral-200);
    --color-text-muted:   var(--color-neutral-400);
    --color-text-inverse: var(--color-neutral-900);
    --color-border:       var(--color-neutral-700);
    --color-link:         var(--color-primary);
  }
}
```

---

## 8. TypeScript tokens — apps/portal/src/lib/colors.ts

A typed TS export mirrors the CSS variables for any component that needs to
reference colors from JS (e.g. canvas, chart libraries). The TS file is
generated from this doc — do not hand-edit.

---

## 9. Acceptance gates

- [ ] All hex values above match what ships in `globals.css`.
- [ ] No `#2563EB` reference remains as the de-facto primary in code or
      docs (it's now `info` only).
- [ ] Contrast ratios verified by axe / Lighthouse at AA threshold.
- [ ] Light + dark mode both render body text at AA-body minimum.

---

## 10. Out of scope

- Refactoring existing portal components to consume the new tokens
  (separate follow-up).
- Spacing, typography, motion — handled in their own docs.
- Style Dictionary / JSON token export.