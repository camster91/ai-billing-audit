# tkd-polish — 21 WCAG 2.1 AA violations breakdown

**Task:** `t_76ae3146` (ready, priority 12)
**Full report:** `/tmp/UXR-A11Y-REPORT.md` (830 lines, multi-agent review)
**Already-shipped fix:** commit `41b13a7` addressed 3 ship-blocker UX bugs.

## Why this is "ready" but still big

The remaining 21 violations are M/L scope (~1-2 days). They're broken
out below by category so the next agent (or future session) can
claim this in one full-day pass, batched by fix pattern.

## Violations grouped by fix pattern

### Group A — Color contrast (5 violations)

**Pattern:** foreground/background color pairs don't meet 4.5:1 ratio
for text or 3:1 for UI components.

**Fix pattern:** Audit tokens.css for low-contrast pairs, bump the
foreground toward the WCAG-required lightness. Specifically:
- Text-on-accent: change from #444 on #f5f5f5 (3.8:1) to #2a2a2a (8.1:1)
- Disabled-button label: change from #999 on #fff (2.8:1) to #666 (5.7:1)
- Form-error text: change from #c33 on #fff (4.0:1) to #a00 (6.3:1)

**Affected files:** `src/client/index.css` (CSS variables), possibly
component overrides in `src/client/components/**/*.tsx`.

**Effort:** 2 hours (design + tokens update + visual regression sweep).

### Group B — Missing ARIA labels (6 violations)

**Pattern:** Icon buttons, form controls, and navigation landmarks lack
`aria-label` or `aria-labelledby`.

**Fix pattern:** Add `aria-label="<purpose>"` to:
- 4 icon-only buttons (close, edit, delete, drag-handle)
- 2 form inputs without visible labels (search box, quick-filter)

**Effort:** 1 hour.

### Group C — Keyboard navigation gaps (4 violations)

**Pattern:** Interactive elements not reachable by keyboard, or focus
order is wrong, or focus indicator is invisible.

**Fix pattern:**
- Add `tabIndex={0}` to the 2 custom dropdowns
- Add visible focus ring (`:focus-visible { outline: 2px solid blue; }`)
- Reorder DOM so tab order matches visual order in the bracket view

**Affort:** 3 hours (mostly bracket view testing).

### Group D — Form labels (3 violations)

**Pattern:** Form fields use placeholder as the only label.

**Fix pattern:** Add `<label htmlFor="x">` + add `aria-label` fallback.
Or use the existing Field component.

**Effort:** 1 hour.

### Group E — Heading hierarchy (2 violations)

**Pattern:** Page jumps from h1 to h3, skipping h2. Or h1 missing.

**Fix pattern:**
- Settings page: add an h2 between the title and the section panels
- Bracket view: promote the round label to h2

**Effort:** 30 min.

### Group F — Live regions missing (1 violation)

**Pattern:** Toast notifications appear without announcing to screen readers.

**Fix pattern:** Add `aria-live="polite"` to the toast container in
`src/client/components/Toast.tsx`.

**Effort:** 15 min.

## Total estimated effort

- A: 2h
- B: 1h
- C: 3h
- D: 1h
- E: 0.5h
- F: 0.25h
- **Total: ~8 hours** (1 full day)

## Suggested batch order

1. **Quick wins first** (B, D, E, F): ~3h, ships visible a11y progress
2. **Color contrast** (A): 2h
3. **Keyboard nav** (C): 3h, biggest batch

After each batch:
- Run `axe-core` against the affected pages
- Update the UXR-A11Y-REPORT.md with progress notes
- Commit per batch (e.g., `a11y: WCAG 2.1 AA batch 1 (6 violations: missing ARIA + form labels + heading hierarchy + live regions)`)

## Acceptance criteria

- [ ] axe-core: 0 violations across /, /settings, /tournament/:id, /bracket/:id
- [ ] Manual screen-reader pass (VoiceOver on macOS): all interactive elements announce correctly
- [ ] Lighthouse a11y score: 100 on /settings
- [ ] Lighthouse a11y score: ≥95 on /bracket/:id
- [ ] No regressions to existing functionality (existing E2E tests pass)
- [ ] Update UXR-A11Y-REPORT.md to "21 → 0" with timestamps

## Out of scope

- AAA-level fixes (this is AA)
- Rewriting component library
- Mobile-specific a11y (covered by separate mobile task)
- Internationalization / RTL

## Suggested future decomposition

This parent could decompose into 6 children (one per group A-F), each
~S/M size. Recommended.

## Reference

- WCAG 2.1 AA spec: https://www.w3.org/WAI/WCAG21/quickref/?currentsidebar=%23col_overview&versions=2.1&levels=aaa
- axe-core rules: https://dequeuniversity.com/rules/axe/4.7
- Lighthouse a11y audits: https://developer.chrome.com/docs/lighthouse/accessibility/