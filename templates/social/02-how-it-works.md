# Template 02 — How-it-works diagram

**Goal:** Show the 4-step Zorva pipeline at a glance — upload → audit
→ biller review → submit. This is the workhorse explainer template;
it's the one we A/B test most variants on.

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
│ How Zorva works                                          │  ← 40 px subhead
│                                                          │
│  ┌────┐    ┌────┐    ┌────┐    ┌────┐                   │
│  │ 1  │───▶│ 2  │───▶│ 3  │───▶│ 4  │                   │  ← 4 step tiles
│  └────┘    └────┘    └────┘    └────┘                   │
│  Upload    Audit     Biller    Submit                    │
│            (LLM)     review                              │
│                                                          │
│  short caption explaining the value                      │  ← 22 px body
│                                                          │
│ @zorvahealth  ·  zorva.health                            │
└──────────────────────────────────────────────────────────┘
```

## Layout (Twitter 1080×1350)

Same 4 tiles but stacked **2 × 2** instead of 1 × 4, so the
extra 270 px of canvas reads as breathing room rather than
stretched whitespace. Each tile is 360 × 360 px.

```
┌──────────────────────────────────────────┐
│ [logo]                                   │
│                                          │
│ How Zorva works                          │
│                                          │
│  ┌────────┐   ┌────────┐                │
│  │   1    │──▶│   2    │                │
│  │ Upload │   │ Audit  │                │
│  └────────┘   └────────┘                │
│       │           │                     │
│       ▼           ▼                     │
│  ┌────────┐   ┌────────┐                │
│  │   3    │──▶│   4    │                │
│  │ Biller │   │Submit  │                │
│  └────────┘   └────────┘                │
│                                          │
│  caption                                 │
│  @zorvahealth · zorva.health             │
└──────────────────────────────────────────┘
```

## Color usage

- Background: `--brand-navy`
- Tile surface: `--brand-navy-2`
- Tile number circle: `--brand-accent` ring + `--brand-text` digit
- Connector arrows: `--brand-muted`
- Active step (highlighted): `--brand-accent` fill on the tile surface
- Logo: white-on-navy

## Copy slots

| Slot             | Required | Example                                            |
| ---------------- | -------- | -------------------------------------------------- |
| Headline         | yes      | "How Zorva works"                                  |
| Step 1 title     | yes      | "Upload clinical note"                             |
| Step 1 sub       | yes      | "PDF, .doc, or paste"                              |
| Step 2 title     | yes      | "Audit runs (LLM)"                                 |
| Step 2 sub       | yes      | "Modifier, code, denial-risk checks"               |
| Step 3 title     | yes      | "Biller review"                                    |
| Step 3 sub       | yes      | "Accept, dismiss, or modify"                       |
| Step 4 title     | yes      | "Submit"                                           |
| Step 4 sub       | yes      | "To your EHR or clearinghouse"                     |
| Caption          | optional | "Audits in 90 seconds. Billers stay in control."    |
| Highlight step   | optional | "2" — when running an "AI-does-the-work" campaign |

## Export

- LinkedIn: `linkedin-how-it-works.png` (1080×1080)
- Twitter/X: `twitter-how-it-works.png` (1080×1350, 2×2 layout)
- Source: `linkedin-how-it-works.fig`, `twitter-how-it-works.fig`
