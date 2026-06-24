# Template 05 — CTA card

**Goal:** Drive a single action — book a demo, start a pilot, read
the case study. The CTA card is the workhorse for paid social and
email-blast footers. Visual hierarchy is uncompromising: **one
button, one URL**.

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
│                                                          │
│                                                          │
│            HEADLINE                                       │  ← 64 px display
│            e.g. "See your missed revenue."               │
│                                                          │
│            supporting subhead                             │  ← 28 px, muted
│            e.g. "Free 14-day pilot. No EHR install."     │
│                                                          │
│            ┌──────────────────────────┐                  │
│            │      BOOK A DEMO  →       │                  │  ← CTA button
│            └──────────────────────────┘                  │  ← accent fill
│                                                          │
│            or scan the QR                                 │  ← optional, twitter only
│                                                          │
│ @zorvahealth  ·  zorva.health                            │
└──────────────────────────────────────────────────────────┘
```

## Layout (Twitter 1080×1350)

Same layout, but the extra 270 px of canvas is dedicated to a
**secondary CTA stack** so the card can support campaigns with two
linked actions (e.g., "Book a demo" + "Read the case study").

```
┌──────────────────────────────────────────┐
│ [logo]                                   │
│                                          │
│  HEADLINE                                 │
│  supporting subhead                       │
│                                          │
│  ┌────────────────────────────────┐      │
│  │   PRIMARY CTA       →          │      │  ← accent fill
│  └────────────────────────────────┘      │
│                                          │
│  ┌────────────────────────────────┐      │
│  │   SECONDARY CTA     →          │      │  ← outline only
│  └────────────────────────────────┘      │
│                                          │
│  ┌─────────┐                              │
│  │   QR    │   Scan to open on phone      │  ← QR for offline→online
│  └─────────┘                              │
│                                          │
│  @zorvahealth · zorva.health             │
└──────────────────────────────────────────┘
```

## Color usage

- Background: `--brand-navy`
- Headline: `--brand-text`
- Subhead: `--brand-muted`
- **Primary** CTA button: `--brand-accent` fill, `--brand-navy` text
- **Secondary** CTA button: 2 px `--brand-accent` outline, `--brand-text` text
- QR code: black-on-white (contrast for scanners — never invert)
- Logo: white-on-navy

## Copy slots

| Slot                | Required | Example                                                  |
| ------------------- | -------- | -------------------------------------------------------- |
| Headline            | yes      | "See your missed revenue."                               |
| Subhead             | yes      | "Free 14-day pilot. No EHR install."                     |
| Primary CTA label   | yes      | "Book a demo"                                            |
| Primary CTA URL     | yes      | `zorva.health/demo`                                      |
| Secondary CTA label | twitter  | "Read the case study"                                    |
| Secondary CTA URL   | twitter  | `zorva.health/case-studies/pacific-dental`               |
| QR target URL       | optional | `zorva.health/pilot` — short, no UTM needed for QR     |
| Footnote            | optional | "PHIPA & PIPEDA compliant. SOC 2 Type II in progress."   |

## Variants

- **`--primary-only`**: LinkedIn default. One button. Cleaner.
- **`--primary-and-secondary`**: Twitter default. Two stacked
  buttons. Primary on top (filled), secondary below (outline).
- **`--qr`**: Use when the card will appear in print / OOH
  contexts (trade show booths, conference signage). Adds the QR
  block.

## Export

- LinkedIn: `linkedin-cta.png` (1080×1080)
- Twitter/X: `twitter-cta.png` (1080×1350)
- Source: `linkedin-cta.fig`, `twitter-cta.fig`
- Variants: `-primary-only`, `-primary-and-secondary`, `-qr`
  suffixes on the filename when used
