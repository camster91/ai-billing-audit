# Template 04 — Team card

**Goal:** Single-person or 2-up spotlight card. Used for
"meet the team" series, hiring posts, and conference speaker
promos. Should feel human — not a corporate headshot grid.

## Dimensions

| Platform   | Size          | Aspect |
| ---------- | ------------- | ------ |
| LinkedIn   | 1080 × 1080   | 1:1    |
| Twitter/X  | 1080 × 1350   | 4:5    |

## Layout — single-person (LinkedIn 1080×1080)

```
┌──────────────────────────────────────────────────────────┐
│ [logo]                                                   │
│                                                          │
│        ┌─────────────────────┐                           │
│        │                     │                           │
│        │      PORTRAIT       │                           │  ← 480×480 px, circular crop
│        │      (rounded)      │                           │
│        │                     │                           │
│        └─────────────────────┘                           │
│                                                          │
│        NAME                                               │  ← 56 px, bold
│        Title at Zorva                                     │  ← 28 px, muted
│                                                          │
│        One-line bio                                       │  ← 22 px, body
│        e.g. "Built billing software at Acme for 8 years."│
│                                                          │
│ @zorvahealth  ·  zorva.health                            │
└──────────────────────────────────────────────────────────┘
```

## Layout — 2-up (LinkedIn 1080×1080)

```
┌──────────────────────────────────────────────────────────┐
│ [logo]                                                   │
│                                                          │
│   ┌──────────────┐         ┌──────────────┐              │
│   │   PORTRAIT   │         │   PORTRAIT   │              │
│   │              │         │              │              │
│   └──────────────┘         └──────────────┘              │
│      NAME                   NAME                          │
│      Title                  Title                         │
│      one-liner              one-liner                     │
│                                                          │
│ @zorvahealth  ·  zorva.health                            │
└──────────────────────────────────────────────────────────┘
```

## Layout (Twitter 1080×1350)

Single-person variant uses the **same portrait crop size** but
pushes the bio block down to fill the extra vertical room. The
2-up variant adds a third row at the bottom with a quote pull:

```
┌──────────────────────────────────────────┐
│ [logo]                                   │
│                                          │
│      ┌─────────────────────────┐          │
│      │        PORTRAIT         │          │
│      │                         │          │
│      └─────────────────────────┘          │
│                                          │
│      NAME                                │
│      Title at Zorva                      │
│                                          │
│      Longer bio — up to 3 lines here     │
│      on the Twitter variant since the    │
│      taller canvas allows for it.        │
│                                          │
│      ────────────                        │
│      "Pull quote or stats line."         │  ← quote pull (twitter only)
│                                          │
│  @zorvahealth · zorva.health             │
└──────────────────────────────────────────┘
```

## Color usage

- Background: `--brand-navy`
- Portrait treatment: a `--brand-accent` (teal) glow ring (8 px)
  around the rounded rectangle — keeps the headshot on-brand
  without the dated "drop-shadow" cliché
- Name text: `--brand-text`
- Title: `--brand-muted`
- Body: `--brand-text` at 80% opacity
- Quote pull (Twitter): `--brand-accent` text on `--brand-navy-2`
- Logo: white-on-navy

## Copy slots

| Slot           | Required | Example                                          |
| -------------- | -------- | ------------------------------------------------ |
| Name           | yes      | "Cameron Ashley"                                 |
| Title          | yes      | "Founder & CEO, Zorva"                           |
| Bio (1 line)   | yes      | "Built billing at Acme for 8 years."             |
| Bio (extra)    | twitter  | "PHIPA-aware audit pipelines since 2022."        |
| Quote pull     | optional | "Denial rate went from 14% to 4% in 90 days."    |
| Pronouns       | optional | "she/her" — render after the name, muted        |

## Photography notes

- Portrait should be **chest-up**, eyes at ~40% from the top
- Natural light preferred over studio ring-light (warmer tone)
- Subject should wear **brand-friendly** colors: navy, teal,
  white, or muted earth tones. Avoid red / pure black.
- Background of the photo itself: out-of-focus clinic or
  office — never a logo wall.

## Export

- LinkedIn: `linkedin-team-{slug}.png` (1080×1080)
- Twitter/X: `twitter-team-{slug}.png` (1080×1350)
- Source: `linkedin-team-{slug}.fig`, `twitter-team-{slug}.psd`
  (layered — so future campaigns can swap portrait + bio
  without rebuilding the layout)
