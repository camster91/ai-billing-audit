# Zorva — Logo System

Status: candidate asset pack implemented; human brand approval, trademark review,
and production publication remain gated.
Owner: Cameron Ashley.
Last updated: 2026-09-01.

This document is the **single source of truth** for the Zorva logo system:
wordmark, logomark, favicon, app icons, and usage rules. Deterministic source
SVGs now live in `assets/brand/source/`; optimized delivery files and hashes are
recorded in `docs/BRAND_ASSET_MANIFEST.json`. These are review candidates, not
approved trademarks or authorization to publish.

Zorva is a pre-submit medical-billing auditor. The logo must read as **calm,
clinical, and trustworthy** — closer to a piece of healthcare software than a
consumer fintech app.

---

## 1. Brand mark overview

Three artifacts work together:

1. **Wordmark** — full "Zorva" word for headers, hero, pitch decks.
2. **Logomark** — Z-in-hex-pill, for favicons, app icons, social avatars.
3. **Lockup** — wordmark + logomark side-by-side, for nav bars and email
   signatures.

The wordmark and logomark share one typeface family (Inter / Geist) and one
palette (teal primary, charcoal accent).

---

## 2. Wordmark

### Typeface

- **Primary candidate:** Inter (regular weight 700 for wordmark).
- **Alt candidates:** Geist Sans (already loaded by the portal — zero-cost
  swap), DM Sans (700). Any of the three is acceptable; pick whichever the
  designer has the easiest time hand-tuning the "Z" stem for.
- No serifs. Zorva is a clinical product; serifs read editorial, not medical.

### Treatment

- Render "Zorva" in **title case**, never ALL CAPS in the wordmark.
- Tracking: slightly tightened (-2%) to read as a single mark, not four
  letters.
- Weight: 700 (Bold). Light/regular reads too thin at small sizes.
- Color: `#1E293B` charcoal for the letters "orva"; the leading **Z** is
  rendered in `#0D9488` teal. This single-letter accent is the brand
  recognition hook — when the wordmark is shown at a size where color is the
  only legible detail, viewers still see "teal Z" = Zorva.
- No ligatures. No swashes. No italics.

### Optional stylization (skip for v1)

- A subtle Z+check-mark treatment is allowed only if it doesn't compromise
  the legibility of "Zorva" at 14 px nav-bar size. For v1 we are NOT using
  this; the teal "Z" alone is enough.

### Clear space

Minimum clear space around the wordmark = the **cap-height of the "Z"** on
all four sides. Nothing (text, image, edge) may enter that box.

### Sizing

- Minimum legible size: **14 px** (nav bar).
- Preferred: 24 px (section headings) up to 48 px (hero).
- Print: never below 8 mm cap-height.

---

## 3. Logomark

### Recommended option: Z inside a hexagonal pill (option B)

A **rounded hexagon** (radius ≈ 1/4 of edge length) filled with the brand
teal `#0D9488`. Inside, a single-color **stylized Z** in white `#FFFFFF`,
drawn with a 2 px stroke at 24 px viewBox, snapping to pixel grid at 16/32/48.

Why this option:

- Works at **16×16** favicon. The Z is a single bold stroke; the hexagon is
  a recognizable silhouette even at favicon size.
- Scales losslessly to 1024×1024 app icon.
- Single-color path, so it can be rasterized into PNG without color
  interpolation issues.
- Hexagon evokes "verified / shield" without leaning too hard into crypto-
  coin aesthetics.

### Rejected options

- **A) Stylized Z alone (no container):** readable but weak as a favicon —
  a single letter looks like a serif drop-cap, not a brand mark.
- **C) Z + check-mark combo:** cute concept, but at 16 px the check-mark
  becomes a smudge and the Z gets crowded. Skip for v1.

### Construction grid

- ViewBox: `0 0 24 24`.
- Hexagon vertices (rounded): a 4 px corner radius rounded hex centered at
  (12, 12), edge length 9.
- Z: three strokes — top bar (2,5)→(22,5), diagonal (22,5)→(2,19), bottom
  bar (2,19)→(22,19). Stroke width 2.25, stroke-linecap square. This gives
  a chunky, geometric Z that survives 16 px.

---

## 4. Favicon set

Place under `apps/portal/public/`:

| File                      | Size    | Purpose                                |
|---------------------------|---------|----------------------------------------|
| `favicon.ico`             | 32×32   | Legacy ICO fallback                    |
| `icon.svg`                | vector  | Default SVG favicon (light mode)       |
| `icon-dark.svg`           | vector  | Dark-mode SVG favicon                  |
| `favicon-16x16.png`       | 16×16   | PNG fallback                           |
| `favicon-32x32.png`       | 32×32   | PNG fallback                           |
| `favicon-48x48.png`       | 48×48   | PNG fallback (Windows tile)            |

The two SVGs use a CSS `prefers-color-scheme` media query so the browser
auto-switches:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <style>
    .mark { fill: #0D9488; }
    .z    { fill: #FFFFFF; }
    @media (prefers-color-scheme: dark) {
      .mark { fill: #14B8A6; } /* lighter teal for dark bg */
    }
  </style>
  <rect class="mark" x="0" y="0" width="24" height="24" rx="6" />
  <!-- Z path -->
  <path class="z" d="M5 7 H19 L5 17 H19" stroke="currentColor"
        stroke-width="2.25" fill="none" stroke-linecap="square" />
</svg>
```

Dark-mode background `#14B8A6` is the lighter shade of teal so the mark
doesn't disappear into a dark address bar.

---

## 5. App icons

Place under `apps/portal/public/app-icons/`:

### iOS (PNG)

`ios-1024.png`, `ios-180.png`, `ios-167.png`, `ios-152.png`, `ios-120.png`,
`ios-87.png`, `ios-80.png`, `ios-60.png`, `ios-58.png`, `ios-40.png`,
`ios-29.png`. No transparency, no rounded corners (Apple applies the mask).

### Android (PNG + adaptive)

`android-192.png`, `android-512.png`,
`android-adaptive-foreground.png` (108×108 dp, 72×72 safe zone),
`android-adaptive-background.png` (solid teal `#0D9488`, 108×108 dp).

### macOS

`macos-16.png`, `macos-32.png`, `macos-64.png`, `macos-128.png`,
`macos-256.png`, `macos-512.png`, `macos-1024.png`.

All app icons = hex-pill logomark on solid teal background, with the Z scaled
to occupy ~55% of the icon's safe area (not the full icon — leave breathing
room around the Z so iOS's squircle mask doesn't clip the stroke).

---

## 6. Color tokens

The logo uses exactly two brand colors:

| Token              | Hex       | RGB              | Usage                                    |
|--------------------|-----------|------------------|------------------------------------------|
| `color-primary`    | `#0D9488` | `13, 148, 136`   | Logomark fill, leading "Z" in wordmark   |
| `color-primary-2`  | `#14B8A6` | `20, 184, 166`   | Dark-mode logomark fill                  |
| `color-charcoal`   | `#1E293B` | `30, 41, 59`     | "orva" letters in wordmark, body text    |
| `color-white`      | `#FFFFFF` | `255, 255, 255`  | Z stroke inside hex pill                 |

Full color system is in [`BRANDING_COLORS.md`](./BRANDING_COLORS.md). Logo
do not introduce any colors outside that palette.

---

## 7. Don'ts

- Don't recolor the wordmark with non-brand colors (no purple, no gradient).
- Don't outline the wordmark.
- Don't rotate or skew.
- Don't place on busy photographs without a solid color plate behind it.
- Don't use the logomark at less than 16 px (it becomes a smudge).
- Don't add drop shadows, glows, or bevels.
- Don't embed the logo inside another shape (circle, badge) — the hex pill
  IS the shape.

---

## 8. Acceptance gates

Before marking this done:

- [x] Wordmark and lockup source SVGs export without rasterization artifacts;
      the Inter text must be converted to approved outlines after visual sign-off.
- [x] Candidate logomark remains identifiable at 16, 32, and 48 px.
- [x] Light-field and dark-field SVG variants are versioned.
- [x] Candidate app icons cover all sizes listed above.
- [x] `apps/portal/src/app/layout.tsx` and metadata reference the mark, favicon,
      manifest, and Apple touch icon.
- [ ] Cameron approves the geometry, typography, and small-size appearance.
- [ ] Trademark/name clearance and final ownership acceptance are recorded.
- [ ] A production release is separately approved and verified.
- [x] No 404s occur in the isolated production-candidate browser journey for
      `/favicon.ico`, `/brand/*`, `/app-icons/*`, or metadata pointing at the
      new assets.

---

## 9. Out of scope

- Wordmark animations / intro motion.
- Localized wordmark variants (Arabic, CJK).
- Trademark registration paperwork.
- Figma / Sketch library export.
