# Notion — internal document template

> Specification for the Zorva internal-doc Notion template.
> Use this for living documents: project plans, OKR trackers,
> weekly notes. Anything that gets edited collaboratively
> over weeks/months, not a one-shot write-and-share.

## Structural outline

```
🟦 [Page header — Zorva logo callout block, navy background]

H1: {Document title}

Callout block (teal background):
  📌 {One-line TL;DR — bold the takeaway}

─────────────────────────────────────────────
H2: Summary
  Paragraph block. Bold key sentences.

H2: Status
  Table block:
    | Item        | Owner   | Status      | Last updated  |
    |-------------|---------|-------------|---------------|
    | {thing 1}   | {name}  | 🟢 / 🟡 / 🔴 | {YYYY-MM-DD}   |
    | {thing 2}   | {name}  | 🟢 / 🟡 / 🔴 | {YYYY-MM-DD}   |

H2: Background
  Paragraph + nested toggles for deep dives.

H2: Plan
  H3 numbered list of steps. Each step is a toggle that
  contains the detailed sub-plan.

H2: Open questions
  Bulleted list. Each item is a toggle with the discussion
  thread inside.

H2: Links
  Bullet list of related docs, Figma boards, Slack channels,
  Linear projects.

─────────────────────────────────────────────
[Footer — callout block, muted]
  Last reviewed: {YYYY-MM-DD}  ·  Owner: {name}
```

## Placeholders

| Slot             | Required | Example                                  |
| ---------------- | -------- | ---------------------------------------- |
| Title            | yes      | "Pacific Dental pilot — kickoff"         |
| TL;DR            | yes      | "12 clinics, 90-day pilot, $48k ARR floor" |
| Last reviewed    | yes      | "2026-09-30"                             |
| Owner            | yes      | "Cameron Ashley"                         |
| Background link  | optional | Figma board URL                          |
| Slack channel    | optional | `#pacific-dental`                        |

## Brand styling

Notion has limited styling vs Google Docs — most of the
brand-styling lives in **block-level choices**, not font
choices. Use these:

| Element       | Notion implementation                                  |
| ------------- | ------------------------------------------------------ |
| Page title    | H1, no special color (Notion controls)                 |
| TL;DR callout | Callout block, teal background (`#5EEAD4`), black text |
| Section H2    | Heading 2, no special color                            |
| Status table  | Notion table block, plain style. Use emoji status.     |
| Brand accent  | Use teal only for callouts and pull quotes             |
| Logo          | Page cover image — `templates/internal/notion-cover.png` (Zorva logo, navy) |
| Body          | Default Notion font (closest to Inter on the platform) |

**Page icon:** 🟦 (or the Zorva mark if Notion supports
custom emoji for your workspace).

## Notion-specific quirks

- **Toggles are your friend.** Notion pages get long fast;
  use toggles for everything below the H2. Keep the top of
  the page scannable.
- **Linked databases > tables-of-contents** for living docs.
  Embed a database of related items rather than a static list.
- **Date fields:** always ISO `YYYY-MM-DD`. Notion's date
  picker will format on display, but the underlying field
  should always be ISO.
- **Templates inside databases:** this Notion template is
  intended as a top-level page; if you need a database
  template (one row = one doc), duplicate this page into
  a database's template slot.

## Duplication steps

1. Navigate to the master page: `Branding/Masters/Notion doc`
   in the Zorva workspace.
2. Click the ··· menu (top-right) → Duplicate → toggle
   **"Duplicate to workspace"** if your view is shared.
3. Rename: `[Project] – [Doc title]`.
4. Update the title, TL;DR callout, status table.
5. Replace background section with the project's context.
6. Move the page into the relevant parent (e.g. under
   `Projects/Pacific Dental/`).
7. Pin it to the team's sidebar if it's a recurring reference.
