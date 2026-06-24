# Template 03 — Before / After comparison

**Goal:** Two columns. "Without Zorva" on the left, "With Zorva" on
the right. The visual contrast sells the value prop in a single
glance — no reading required.

## Dimensions

| Platform   | Size          | Aspect |
| ---------- | ------------- | ------ |
| LinkedIn   | 1080 × 1080   | 1:1    |
| Twitter/X  | 1080 × 1350   | 4:5    |

## Layout (LinkedIn 1080×1080)

```
┌──────────────────────────────────────────────────────────┐
│ [logo]                                                   │
│                                                          │
│  Billing audit, before and after                         │  ← subhead, centered
│                                                          │
│  ┌─────────────────┐    ┌─────────────────┐              │
│  │   BEFORE        │    │   AFTER         │              │
│  │   ──────────    │    │   ──────────    │              │  ← column dividers
│  │   $48 / claim   │    │   $4 / claim    │              │
│  │   3-day lag     │    │   90-sec audit  │              │
│  │   12% denial    │    │   4% denial     │              │
│  │   Manual QA     │    │   LLM + biller  │              │
│  └─────────────────┘    └─────────────────┘              │
│                                                          │
│  (footer attribution)                                     │
│ @zorvahealth  ·  zorva.health                            │
└──────────────────────────────────────────────────────────┘
```

## Layout (Twitter 1080×1350)

Same two-column layout. The extra canvas height goes into **a
third row at the bottom** that holds the value-prop headline so the
comparison reads as a mini-case-study, not just two columns of stats:

```
┌──────────────────────────────────────────┐
│ [logo]                                   │
│                                          │
│  Billing audit, before and after         │
│                                          │
│  ┌────────────────┐  ┌────────────────┐  │
│  │ BEFORE         │  │ AFTER          │  │
│  │ ────────       │  │ ────────       │  │
│  │ $48/claim      │  │ $4/claim       │  │
│  │ 3-day lag      │  │ 90-sec audit   │  │
│  │ 12% denial     │  │ 4% denial      │  │
│  │ Manual QA      │  │ LLM + biller   │  │
│  └────────────────┘  └────────────────┘  │
│                                          │
│  ─────────────────────────────────────   │
│  73% fewer denials. 90% cheaper.         │  ← result banner
│                                          │
│  @zorvahealth · zorva.health             │
└──────────────────────────────────────────┘
```

## Color usage

- Background: `--brand-navy`
- **Before** column surface: `--brand-navy-2` (recessive)
- **Before** column dividers / values: `--brand-warn` (amber — caution)
- **After** column surface: `--brand-navy-2` (recessive — same)
- **After** column dividers / values: `--brand-accent` (teal — success)
- Result banner (Twitter only): `--brand-accent` text on `--brand-navy-2`
- Logo: white-on-navy

## Copy slots

| Slot              | Required | Example                                                |
| ----------------- | -------- | ------------------------------------------------------ |
| Headline          | yes      | "Billing audit, before and after"                      |
| Before label      | yes      | "Without Zorva"                                        |
| After label       | yes      | "With Zorva"                                           |
| Before row 1..N   | yes (≥1) | "$48 / claim"                                          |
| After row 1..N    | yes (≥1) | "$4 / claim"                                           |
| Row pairings       | yes      | Must align 1:1; same metric, different value           |
| Result banner     | twitter  | "73% fewer denials. 90% cheaper."                      |
| Source line       | optional | "Source: 12 Zorva pilot clinics, Q1–Q2 2026."          |

## Variants

- **Vertical (default):** two side-by-side columns. Best for
  LinkedIn feed where the card is competing with text-heavy posts.
- **Stacked:** one column above the other, full-width. Use when the
  before/after story has more than 4 rows.

## Export

- LinkedIn: `linkedin-before-after.png` (1080×1080)
- Twitter/X: `twitter-before-after.png` (1080×1350)
- Source: `linkedin-before-after.fig`, `twitter-before-after.fig`
