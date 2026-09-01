# Zorva — Imagery & Illustration Style

Status: proposed direction; listed illustration assets are not implemented.
Owner: Cameron Ashley.
Last updated: 2026-09-01.

This document defines the visual language for every illustration, diagram,
and photograph used in the Zorva marketing site, the portal, the pitch
deck, and the brand book. It picks one approach (illustrations) and locks
the style — color, line weight, character treatment, do/don't — so every
new asset looks like it came from the same studio.

---

## 1. Decision: illustrations, not photos

For v1, Zorva uses **custom line illustrations** as the primary imagery.
Real photos are **not** used in the marketing site or portal. Rationale:

| Option                | Pros                              | Cons                                   | Verdict   |
|-----------------------|-----------------------------------|----------------------------------------|-----------|
| Real photos           | Fast if stock; human warmth       | Licensing risk, model release, generic look, expensive for custom | **Reject** |
| 3D render             | Trendy, modern                    | Drift away from "clinical" feel; expensive; hard to keep on-brand | **Reject** |
| Custom line illustrations | Can share the icon geometry and adapt across sizes | Need a designer/source file; accessibility still requires alt text, contrast, and content context | **Pick**  |
| Abstract gradients    | Cheap, modern                     | No narrative, no story                 | Secondary |

Line illustrations win for v1 because they:
- **Read as clinical and trustworthy** (line drawing = chart, blueprint, schematic)
- **Match the icon system** (same line weight, same viewBox conventions)
- **Are easy to localize** (no faces to redraw per market)
- **Can be made accessible** with tested contrast, appropriate alt treatment,
  and equivalent surrounding content
- **Can be extended coherently** when the construction source and production
  rules are retained

Real photography is allowed only in an approved case study or demonstration
with source/licence evidence, releases, and a no-PHI background review. No
existing recording is approved merely because an older document references it.

---

## 2. Style rules

### 2.1 Line treatment

- **Stroke:** 1.5px solid for foreground objects, 1.0px for secondary detail
- **Stroke color:** `primary-700` (`#0F766E`) by default, `slate-700` for
  non-branded illustrations, `amber-500` for "warning" illustrations
- **Line caps:** round (gives a softer, more human feel)
- **Line joins:** round
- **No fills** on the foreground — line work only, with optional flat fills
  for accent areas (1–2 per illustration, max)

### 2.2 Geometry

- **Grid:** every illustration is built on a **24px grid**, the same as
  the icon system
- **Corner radius:** 2px on rectangles, 1px on small details
- **Curves:** generous, never sharp angles (no jagged lines, no zigzag)
- **Proportions:** characters are stylized, not realistic. Heads are
  ~1/4 the body height. No facial features beyond simple dots/lines.

### 2.3 Color palette

Use the brand palette (see `docs/BRANDING_COLORS.md`). Specifically:

| Role               | Token          | Hex       | Use                                      |
|--------------------|----------------|-----------|------------------------------------------|
| Primary line       | `primary-700`  | `#0F766E` | Default stroke for branded illustrations |
| Accent fill        | `primary-200`  | `#99F6E4` | Soft fills for "data" / "chart" elements |
| Warning line       | `amber-500`    | `#F59E0B` | "What can go wrong" illustrations         |
| Background wash    | `surface-light`| `#F8FAFC` | Illustration background (no border)       |
| Neutral line       | `slate-700`    | `#334155` | Generic / non-branded illustrations       |
| Text               | `slate-900`    | `#0F172A` | Labels and callouts inside illustrations  |

**Limit to 3 colors per illustration.** If you need more, split into two
illustrations.

### 2.4 People & characters

- **Stylized**, not photoreal. Round heads, simple body shapes.
- **Diverse** in skin tone, hair, posture, accessories (glasses, hijab,
  hearing aid, etc.). One illustration per representation.
- **No faces** beyond minimal dots for eyes and a small curve for a
  smile. This avoids uncanny-valley and keeps localization simple.
- **Always shown doing the work** — typing, reviewing, pointing at a
  screen — never stock-photo "smiling at camera".

### 2.5 Composition

- **Centered, not corner-weighted.** A small illustration sits in the
  middle of a generous padding box (24px on each side minimum).
- **One focal point.** Each illustration has one clear "thing happening"
  — a biller reading a claim, a chart trending up, a shield over a folder.
- **Whitespace is part of the design.** Don't fill the canvas.

---

## 3. Proposed asset inventory (not implemented)

| #  | File name                                | Used in                         | Size      |
|----|------------------------------------------|---------------------------------|-----------|
| 1  | `hero-review-context.svg`                | Marketing home hero             | 720×480   |
| 2  | `how-it-works-1-bring.svg`               | How-it-works step 1             | 240×240   |
| 3  | `how-it-works-2-review.svg`              | How-it-works step 2             | 240×240   |
| 4  | `how-it-works-3-decide.svg`              | How-it-works step 3             | 240×240   |
| 5  | `review-item-source.svg`                 | Review-context explanation      | 320×200   |
| 6  | `review-item-context.svg`                | Review-context explanation      | 320×200   |
| 7  | `review-decision.svg`                    | Human-decision explanation      | 320×200   |
| 8  | `empty-state-no-reviews.svg`             | Portal empty state              | 240×200   |
| 9  | `privacy-review-boundary.svg`            | Trust/onboarding explanation    | 480×320   |

The repository currently has no `apps/portal/public/illustrations/` directory,
so these filenames are a proposed backlog, not an asset inventory. A future
implementation must record the source file, creator, licence/ownership basis,
alt text, export hash, and actual consumer before changing this section to
implemented.

---

## 4. Where illustrations are NOT used

To keep the brand consistent, illustrations are explicitly **not** used in:

- The audit results table (severity icons only — see `docs/BRANDING_ICONS.md`)
- The dashboard KPI tiles (numbers + sparkline icons only)
- The login / auth screens (cleaner, more trustworthy with no imagery)
- The error / 500 page (a single `IconError` from the icon system is enough)

The rule: **illustrations carry narrative, not status**. If a screen is
communicating state (loading, error, success), use an icon, not an
illustration.

---

## 5. Photography (for case studies only)

When we add a real-photo case study in v1.1+:

- **Get written release** from everyone in the frame. Filed in
  `assets/case-studies/releases/`.
- **Use the clinic's environment** — front desk, charting room, hallway —
  not staged stock.
- **No identifiable patient information** in the background (paper
  charts, whiteboards with names, etc.).
- **Color treatment:** a slight teal cast on shadows (multiply layer at
  10%) to keep the photo in the brand palette without making it look
  filtered.
- **Aspect ratio:** 16:9 for the hero crop, 4:3 for inline.

Case study photos are stored in `assets/case-studies/<clinic-slug>/` and
served via the CDN, never committed to git.

---

## 6. Accessibility & alt text

- Every illustration has a **text alternative** in the surrounding
  content, not just an `alt=""`. The `alt` attribute is short and
  descriptive; the body text explains the "why".
- Decorative illustrations (purely for visual rhythm) get
  `alt=""` and `role="presentation"`.
- Color is never the only carrier of meaning. The illustration's
  composition + label must work in grayscale (test by desaturating the
  Figma artboard).

---

## 7. Acceptance checklist

When this task is "done":

- [ ] `apps/portal/public/illustrations/` exists with the 9 illustrations
      listed in **§3** (or placeholders with the same filenames).
- [ ] All illustrations follow **§2** (line weight, color, composition).
- [ ] Each illustration has an `alt` text in the Figma export notes.
- [ ] No photo placeholders remain in the marketing site v1 build.
- [ ] Source, creator, licence/ownership basis, alt text, export hash, and
      actual consumer are recorded for every produced asset.
