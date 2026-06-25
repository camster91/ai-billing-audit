<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

<!-- BEGIN:zorva-design-system -->
# Zorva design conventions

## Dark-only design choice

The Zorva marketing site and portal use a **dark-only** color scheme. This
is intentional and load-bearing — do not add a light/dark toggle, do not
add a system-preference media query, do not introduce light-mode tokens.

Rationale (see kanban `t_480d6349`):

- The marketing copy leans on a "lab/console" metaphor (audit logs, hash
  chains, region pinning). A light theme would dilute it.
- The portal surfaces dense tables (encounters, findings, audit trail)
  that read more clearly on a dark background.
- Maintaining one color story avoids the "looks correct on one machine,
  broken on another" failure mode.

Implementation hooks:

- `<meta name="color-scheme" content="dark" />` is rendered in
  `src/app/layout.tsx` so the UA picks the dark form for form controls
  and scrollbars on first paint (kanban `t_9bf46d09`).
- The brand palette is in `src/app/globals.css` under `:root`. No light
  token block exists by design.
- New pages inherit the dark tokens automatically — there is no
  per-page opt-in needed, and no per-page opt-out allowed.
<!-- END:zorva-design-system -->
