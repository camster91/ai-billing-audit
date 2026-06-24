# Zorva — Social media template specs

> 5 reusable social cards for Zorva, designed for both
> **LinkedIn** (1080×1080, square) and **Twitter/X** (1080×1350, 4:5).
>
> This directory holds the **template specs** (per-card design
> contract: dimensions, color tokens, copy slots, layout grid).
> The actual PNGs and editable source files (Figma export, PSD/AI)
> are produced downstream from these specs. The specs are the
> source of truth — they let any designer pick up the system and
> generate consistent assets for a new campaign without re-deriving
> the rules.

## Design system (shared across all 5 templates)

These tokens are the contract. Every card pulls from the same
palette, type scale, and grid so the set reads as a family.

### Color tokens

| Token             | Hex      | Role                                            |
| ----------------- | -------- | ----------------------------------------------- |
| `--brand-navy`    | `#0F172A` | Background (dark mode default)                 |
| `--brand-navy-2`  | `#1E293B` | Surface (tiles, cards within the card)         |
| `--brand-slate`   | `#334155` | Hairlines, table borders                       |
| `--brand-text`    | `#E6E9F5` | Primary text                                    |
| `--brand-muted`   | `#94A3B8` | Secondary text, captions, axis labels          |
| `--brand-accent`  | `#5EEAD4` | Primary accent — stats, chart lines, CTA fill  |
| `--brand-accent-2`| `#22D3EE` | Secondary accent — comparisons, "after" fills  |
| `--brand-warn`    | `#FBBF24` | Tertiary accent — emphasis, before/after "before" |

### Type scale

- **Display (stat cards, headlines):** 72–96 px, weight 700, tracking -0.02em
- **Subhead:** 32–40 px, weight 600
- **Body:** 22–28 px, weight 400
- **Caption / axis:** 16–20 px, weight 500, color `--brand-muted`

All cards use the same stack: `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`. (For Figma source files, the team's brand face is **Inter** at the weights above.)

### Grid

- **Safe area:** 60 px gutter on every edge (LinkedIn and Twitter)
- **Column:** 12-col grid, 24 px gutter
- **Logo lockup:** top-left, 28 px from the safe area on the linked/twitter canvas
- **Footer:** bottom-left, 20 px from the safe area — handle `@zorvahealth`, link `zorva.health`

### Logo placement

The Zorva mark sits top-left in every card. White-on-navy by default;
on light backgrounds swap to navy-on-white via the `logo--inverse`
modifier. Sized to 120×32 px regardless of canvas.

### Filename convention

`{platform}-{card-slug}.png` — platform is `linkedin` or `twitter`.
Source files: `{platform}-{card-slug}.fig` (or `.psd`/`.ai`).

---

## Templates

The five template specs follow. Each spec is a self-contained file:

| # | Card type           | Spec file                                                            |
| - | ------------------- | -------------------------------------------------------------------- |
| 1 | Missed-revenue stat | [`01-missed-revenue-stat.md`](./01-missed-revenue-stat.md)           |
| 2 | How-it-works        | [`02-how-it-works.md`](./02-how-it-works.md)                         |
| 3 | Before/After        | [`03-before-after.md`](./03-before-after.md)                         |
| 4 | Team                | [`04-team.md`](./04-team.md)                                         |
| 5 | CTA                 | [`05-cta.md`](./05-cta.md)                                           |

Each spec lists dimensions, layout grid, copy slots, color usage,
and the contract the designer must hit so the cards stay on-brand.
