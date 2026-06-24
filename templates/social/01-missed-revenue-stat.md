# Template 01 — Missed-revenue stat card

**Goal:** Surface one big "missed revenue" number to stop the scroll.
This is the highest-performing template on LinkedIn — the stat does
the talking; the rest is brand framing.

## Dimensions

| Platform   | Size          | Aspect |
| ---------- | ------------- | ------ |
| LinkedIn   | 1080 × 1080   | 1:1    |
| Twitter/X  | 1080 × 1350   | 4:5    |

The Twitter variant uses the same vertical layout; extra canvas
height is absorbed by increasing the **breathing room** around the
stat — never the stat itself. The stat number stays exactly the
same pixel size on both canvases.

## Layout (LinkedIn 1080×1080)

```
┌──────────────────────────────────────────────────────────┐
│ [logo]                                                   │  ← 60 px gutter, top-left
│                                                          │
│                                                          │
│       LABEL — small, muted, all-caps                     │  ← y=320, 22 px
│                                                          │
│       $2.4M                                              │  ← y=400, 220 px display
│       missed in Q3                                       │  ← y=640, 56 px subhead
│                                                          │
│       One sentence of context —                          │
│       what we found, where, who                          │  ← y=760, 28 px body
│                                                          │
│                                                          │
│                                                          │
│ @zorvahealth  ·  zorva.health                            │  ← 60 px gutter, bottom-left
└──────────────────────────────────────────────────────────┘
```

## Color usage

- Background: `--brand-navy`
- Stat number: `--brand-accent` (#5EEAD4)
- Label / subhead: `--brand-text`
- Context sentence: `--brand-muted`
- Logo: white-on-navy (default)

## Copy slots

| Slot           | Required | Example                                              |
| -------------- | -------- | ---------------------------------------------------- |
| Label          | yes      | "Missed revenue — Q3 2026"                           |
| Stat number    | yes      | "$2.4M"                                              |
| Stat qualifier | yes      | "across 14 clinics on Pacific Northwest"             |
| Context body   | yes      | "Modifier-25 underpayments detected pre-bill."       |
| Footer handle   | yes      | "@zorvahealth"                                       |
| Footer URL      | yes      | "zorva.health"                                       |
| Stat source    | optional | "Source: Zorva audit log, 14 tenants, 90 days."      |

## Variants

- **`--accent`** (default): teal number on navy. Best for organic posts.
- **`--warm`**: amber (`--brand-warn`) number on navy. Best for "alert"-style
  posts — escalations, regulatory updates.
- **`--inverse`**: navy number on `--brand-text` background. Best for
  Twitter where dark images are down-ranked.

## Export

- LinkedIn: `linkedin-missed-revenue.png` (1080×1080, sRGB, no profile)
- Twitter/X: `twitter-missed-revenue.png` (1080×1350, sRGB, no profile)
- Source: `linkedin-missed-revenue.fig` + `twitter-missed-revenue.fig`
