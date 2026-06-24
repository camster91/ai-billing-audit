# Google Slides — internal presentation template

> Specification for the Zorva internal-deck Google Slides
> template. Use this for team all-hands, board updates, sales
> enablement, partner briefings.

## Structural outline

```
SLIDE 1 — TITLE
  [logo top-left]
  ─────────────────────────────
  TITLE: {deck title — Inter Bold 48pt, white on navy}
  SUBTITLE: {one-line summary — 24pt, muted}
  ─────────────────────────────
  [footer: zorva.health]

SLIDE 2 — AGENDA
  Numbered list of the 4–6 sections to follow. Each item
  is a section header (e.g. "1. Q3 results").

SLIDE 3..N — SECTION DIVIDER
  Full-bleed --brand-navy-2 band. Section number (large,
  teal) on the left, section title (white, bold) on the right.

SLIDE — CONTENT (standard)
  Top-left logo, slide title in upper third, body content
  in lower two-thirds. Use bullets, tables, or a single
  hero chart. Never all three — pick the format that fits
  the message.

SLIDE — METRIC TILE
  Big number (display, teal) on the left, label + 1-line
  context on the right. One metric per slide. Use this for
  the "show the headline" slides.

SLIDE — BEFORE / AFTER
  Two columns. Left = before (amber accent). Right = after
  (teal accent). Same metric, different value. Same rule as
  the social-media before/after card.

SLIDE — CALLOUT
  Centered pull quote, 32pt italic, teal accent border.
  Use sparingly — one per deck max.

SLIDE — CLOSING
  Centered "Questions?" headline, footer URL, presenter
  contact info.
```

## Placeholders (per slide type)

### Title slide

| Slot       | Required | Example                                       |
| ---------- | -------- | --------------------------------------------- |
| Title      | yes      | "Q3 2026 Board update"                        |
| Subtitle   | yes      | "What we shipped, what we learned, what's next" |
| Presenter  | optional | "Cameron Ashley, Founder & CEO"               |
| Date       | yes      | "2026-09-30"                                  |

### Content slide

| Slot       | Required | Example                                          |
| ---------- | -------- | ------------------------------------------------ |
| Title      | yes      | "Three things we shipped this quarter"           |
| Body       | yes      | bullet list / table / chart                      |
| Footnote   | optional | "Source: Zorva audit log"                        |

### Metric tile

| Slot       | Required | Example                                          |
| ---------- | -------- | ------------------------------------------------ |
| Metric     | yes      | "73%"                                            |
| Label      | yes      | "fewer denials since Q1"                         |
| Context    | yes      | "Across 14 pilot clinics"                        |

## Brand styling

Apply via the slide master (View → Master) so every new slide
inherits:

| Element       | Style                                       |
| ------------- | ------------------------------------------- |
| Background    | `--brand-navy` (#0F172A)                    |
| Logo          | top-left, white, 120×32 px                  |
| Footer        | bottom-left, `--brand-muted`, `zorva.health`|
| Page number   | bottom-right, `--brand-muted`               |
| Title font    | Inter Bold, 36 pt, white                    |
| Body font     | Inter Regular, 18 pt, `--brand-text`        |
| Caption font  | Inter Medium, 11 pt, `--brand-muted`        |

**Charts:** use the secondary palette (`--brand-accent` and
`--brand-accent-2`) as the first two series. Avoid Google's
default rainbow palette — it's off-brand and the legend eats
slide real estate.

## Slide-master page setup

- Size: 16:9 widescreen (the team standard)
- Margins: 60 px safe area on every edge
- Background: solid `--brand-navy`, no gradients

## Duplication steps

1. Open the master: `templates/internal/master-gslides-deck.gslides`
   (in shared Zorva drive under `Branding/Masters/`).
2. File → Make a copy.
3. Rename: `[Project] – [Deck title] — [YYYY-MM-DD]`.
4. Update slide 1 with title / subtitle / date / presenter.
5. Update slide 2 with the agenda.
6. Replace placeholders slide-by-slide. Delete unused
   template slides — don't leave them in the final deck.
7. Re-check brand styling on the slide master before sharing.
8. Share with the audience. Comment-only access for stakeholders
   during review; edit access for collaborators.
