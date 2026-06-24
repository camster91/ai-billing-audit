# Zorva — Internal document and slide templates

> Ready-to-use internal document and presentation templates
> (Notion + Google Docs / Slides) that follow the Zorva brand.
> Pick the file that matches your tool, duplicate it, fill in
> the placeholders, and ship.

## Brand spec (apply to every template)

All four templates use the same brand tokens. If you change
anything here, change it in the four template files too — they
are intentionally hand-kept in sync rather than auto-generated
from a single source, so the templates stay editable by humans.

### Colors

| Token             | Hex      | Where used                                            |
| ----------------- | -------- | ----------------------------------------------------- |
| `--brand-navy`    | `#0F172A` | Primary background (slides), header (docs)            |
| `--brand-navy-2`  | `#1E293B` | Section divider bands, callout boxes                  |
| `--brand-slate`   | `#334155` | Hairlines, table borders                              |
| `--brand-text`    | `#E6E9F5` | Primary text on dark surfaces                         |
| `--brand-muted`   | `#94A3B8` | Secondary text, captions                              |
| `--brand-accent`  | `#5EEAD4` | Accent — callouts, pull quotes, primary CTA            |
| `--brand-accent-2`| `#22D3EE` | Secondary accent — chart lines, "after" highlights     |
| `--brand-paper`   | `#FFFFFF` | Light-mode doc body background                       |

### Typography

- **Display / slide title:** Inter Bold 36–48 pt (slides) / 32 pt (docs)
- **Section header:** Inter SemiBold 24 pt
- **Body:** Inter Regular 14 pt (docs) / 18 pt (slides)
- **Caption:** Inter Medium 11 pt, color `--brand-muted`

### Page / slide master

- **Slide master (Google Slides + Notion):**
  - Background: `--brand-navy`
  - Top-left: Zorva logo (white, 28 px from edge)
  - Bottom-right: page number, footer URL `zorva.health`
- **Doc master (Google Docs + Notion):**
  - Page header: 0.5" tall navy band with white logo
  - Body: white background, Inter Regular 11 pt, 1.15 line height
  - Footer: page number + `zorva.health` in `--brand-muted`

### Section dividers

All four templates share the same divider treatment:

- 1 px line in `--brand-slate` between sections in docs
- Full-bleed `--brand-navy-2` band with white text title in slides

## Templates

| # | Tool         | Type           | Spec file                                                |
| - | ------------ | -------------- | -------------------------------------------------------- |
| 1 | Google Docs  | Document       | [`gdocs-doc.md`](./gdocs-doc.md)                         |
| 2 | Google Slides| Presentation   | [`gslides-slides.md`](./gslides-slides.md)               |
| 3 | Notion       | Document       | [`notion-doc.md`](./notion-doc.md)                       |
| 4 | Notion       | Presentation   | [`notion-slides.md`](./notion-slides.md)                 |

Each spec file documents:

- The structural outline (sections / slide order)
- The placeholder block (what to fill, where)
- The duplication steps for the target tool
- Brand-styling instructions specific to that tool

## Duplication cheat-sheet

- **Google Docs:** File → Make a copy → rename with the project prefix (`[Project] – [Doc title]`).
- **Google Slides:** File → Make a copy → rename. Update slide-master fonts if you change the brand spec.
- **Notion (doc):** In the sidebar, click the ··· menu next to the page → Duplicate → toggle "Duplicate to workspace" → rename.
- **Notion (slides):** Notion doesn't have a true "presentation" mode; the slides template is a Notion page with a `slides-` prefixed database that uses the toggle-heading layout. Duplicate the database, then duplicate each toggle page as a slide.

## How to extend

When you need a new template variant (e.g. a "Q3 board update" deck):

1. Pick the closest spec above (slide master for decks, doc master for written reports).
2. Copy the spec into the new variant's folder.
3. Update the section outline and placeholder copy for the new context.
4. Add the variant to this README under "Templates".
5. Commit with `docs(branding): internal <variant> template`.

Do not redefine the brand tokens in the variant — link back to
this README so the four masters remain the single source of truth.
