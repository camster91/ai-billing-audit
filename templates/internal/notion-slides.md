# Notion — internal presentation template

> Specification for the Zorva internal-deck Notion template.
> Notion doesn't have a true "presentation" mode — instead,
> this template uses a **slide-shaped page** (one toggle per
> slide) that the presenter reveals top-to-bottom during
> the meeting. Use for low-stakes internal decks where the
> cost of opening Google Slides feels disproportionate.

## Structural outline

The page is a single Notion page with one **toggle heading per
slide**. Each toggle's body is the slide's content.

```
🟦 [Page cover — Zorva logo]

H1: {Deck title}

Callout (teal): 📌 One-line summary of the deck

─────────────────────────────────────────────
▸ Slide 1 — Title                                  [toggle]
    H2: {deck title}
    paragraph: presenter, date
    paragraph: subtitle / TL;DR

▸ Slide 2 — Agenda                                 [toggle]
    numbered_list: section titles

▸ Slide 3 — {Section divider}                      [toggle]
    H2: {section number + name}
    callout (navy): {one-paragraph framing}

▸ Slide 4 — {Content}                              [toggle]
    H2: {slide title}
    body: bullets / table / image

▸ Slide 5 — {Metric tile}                          [toggle]
    H2: big-number placeholder
    paragraph: label + context

▸ Slide 6 — {Before / After}                       [toggle]
    H2: slide title
    two-column layout via 2-col table block

▸ Slide 7 — Q&A                                    [toggle]
    H2: Questions?
    paragraph: presenter contact
```

## Placeholders

| Slot            | Required | Example                                  |
| --------------- | -------- | ---------------------------------------- |
| Deck title      | yes      | "Q3 2026 All-hands"                      |
| TL;DR           | yes      | "What we shipped, what we learned"       |
| Slide 1 title   | yes      | "Q3 2026 All-hands"                      |
| Slide 1 presenter| yes     | "Cameron Ashley"                         |
| Slide 1 date    | yes      | "2026-09-30"                             |
| Slide 4 title   | yes      | "Three things we shipped this quarter"   |
| Slide 5 metric  | yes      | "73%"                                    |
| Slide 5 label   | yes      | "fewer denials since Q1"                 |

## Brand styling

| Element       | Notion implementation                              |
| ------------- | -------------------------------------------------- |
| Page cover    | `notion-cover.png` (navy, Zorva logo white)        |
| Page icon     | 🟦 (or custom Zorva emoji if available)            |
| Slide titles  | H2 inside the toggle. Default Notion font.         |
| Accent color  | Teal callout blocks (`#5EEAD4`) — sparingly       |
| Section divider | Toggle title in a callout block, navy background  |
| Footer        | The last toggle (Slide 7 — Q&A) holds footer info  |

**Type:** Notion uses the system font on each platform. The
team's brand face is Inter, but Notion will substitute the
closest platform default (SF Pro on Mac, Segoe UI on Windows).
This is acceptable for internal use; for external-facing decks,
use the Google Slides master instead.

## Notion presentation runtime

When presenting this template:

1. Open the page in full-screen mode (`Cmd/Ctrl + \\` then `F`).
2. Click into each toggle to reveal the slide.
3. Use `Cmd/Ctrl + ↑/↓` to navigate toggles without a mouse.
4. The callouts at the top of each toggle act as visual
   section dividers — keep them tight (one sentence).

## When NOT to use this template

- **External-facing decks** (board, investors, partners) —
  use the Google Slides master. Notion's font rendering is
  not polished enough for external audiences.
- **Decks with >12 slides** — toggle-by-toggle navigation
  becomes unwieldy past a dozen. Switch to Google Slides.
- **Decks that need heavy animation / media** — Notion
  embeds work but Google Slides handles video, GIFs, and
  transitions more gracefully.

## Duplication steps

1. Navigate to `Branding/Masters/Notion slides` in the
   Zorva workspace.
2. ··· menu → Duplicate → toggle "Duplicate to workspace".
3. Rename: `[Project] – [Deck title]`.
4. Walk through each toggle. Replace placeholders with the
   deck's content. Delete toggles you don't need; don't
   leave placeholder toggles in the final deck.
5. Reorder toggles by dragging (the "Section divider" toggles
   should sit between content toggles, not at the bottom).
6. Pin to the team's sidebar if it's a recurring reference.
