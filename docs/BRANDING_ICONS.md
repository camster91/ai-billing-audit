# Zorva — Icon System

Status: spec, ready for implementation.
Owner: branding kit, P5 icon-set task (`t_9b007f8d`).
Last updated: 2026-06-24.

This document is the single source of truth for the Zorva icon system. It
defines which library we use, how icons are organized in the portal code,
the full inventory of icons needed for v1, and the rules for adding new
ones later. All icons are **line-style** (1.5px stroke, 24x24 viewBox) to
match the rest of the visual system.

---

## 1. Library choice — lucide-react

We standardize on **`lucide-react`** for v1. Rationale:

- **Free, MIT-licensed**, maintained, ~1,500 icons.
- **Stroke-style** matches our wordmark / logomark weight and our
  Tailwind "outline" UI language.
- **Tree-shakeable** — each icon is a named import. No SVG asset bloat in
  the bundle.
- **React-native** — no extra wrapper or runtime; size, color, className
  work via props.
- **Categorized** so the audit/claims/encounter vocabulary is already
  largely covered (Stethoscope, FileText, ShieldAlert, etc.).

Alternatives considered and **rejected**:

| Option         | Why not for v1                                  |
|----------------|-------------------------------------------------|
| heroicons      | Smaller set; no "stethoscope" or "clipboard-list" |
| phosphor-react | Heavier; two-tone style breaks our line-only rule |
| Custom SVG     | 3–5× the design work; no marginal brand gain     |

---

## 2. Code organization

All icons are imported and re-exported from a single module:

```
apps/portal/src/components/icons/
  index.tsx        # barrel re-export (named only, no wildcards)
  findings.tsx     # severity + finding-type icons
  actions.tsx      # accept / dismiss / modify / rerun / flag
  sections.tsx     # nav: claims / encounters / dashboard / audit / etc.
  states.tsx       # loading / empty / error / success
```

**Hard rules** for the icons module:

1. **No wildcard re-exports.** Each file lists every icon it exposes by
   name. This keeps tree-shaking intact and the dependency graph auditable.
2. **One component per file = one named export.** Don't bundle multiple
   icons into one file under a "group" name.
3. **Default props** are `size={20}` and `strokeWidth={1.5}` to match the
   rest of the UI. Consumers can override per call site.
4. **Color** comes from `currentColor` so the icon inherits the parent's
   text color (e.g. `text-amber-600` on the wrapper changes the stroke).

The barrel `index.tsx` re-exports all of the above. Pages import icons
**only** from this barrel, never directly from `lucide-react`.

```tsx
// ✅ correct
import { IconAccept, IconHigh } from "@/components/icons";

// ❌ forbidden — leaks the underlying library
import { Check, AlertTriangle } from "lucide-react";
```

---

## 3. Full inventory (v1 = 38 icons)

The categories below define the **complete v1 set**. Anything not in this
list should not appear in the UI in v1.

### 3.1 Findings (8 icons)

Severity + finding-type glyphs for the audit results panel.

| Icon name         | lucide source       | Used for                       |
|-------------------|---------------------|--------------------------------|
| `IconInfo`        | `Info`              | Informational note (no action) |
| `IconLow`         | `CircleDot`         | Severity: LOW                  |
| `IconMedium`      | `AlertCircle`       | Severity: MEDIUM               |
| `IconHigh`        | `AlertTriangle`     | Severity: HIGH                 |
| `IconCritical`    | `OctagonAlert`      | Severity: CRITICAL / denial-risk |
| `IconMissing`     | `CircleSlash`       | Missing-dx / missing-procedure |
| `IconModifier`    | `GitBranch`         | Modifier-25 / modifier issues  |
| `IconUndercode`   | `ArrowUpRight`      | Undercode opportunity          |

### 3.2 Actions (7 icons)

Buttons the biller clicks on a finding.

| Icon name       | lucide source | Used for                  |
|-----------------|---------------|---------------------------|
| `IconAccept`    | `Check`       | Accept finding as-is      |
| `IconDismiss`   | `X`           | Dismiss finding           |
| `IconModify`    | `Pencil`      | Modify the claim manually |
| `IconRerun`     | `RotateCcw`   | Re-run audit on this claim |
| `IconFlag`      | `Flag`        | Flag for follow-up        |
| `IconAppeal`    | `Scale`       | Generate appeal letter    |
| `IconExport`    | `Download`    | Export finding to CSV/PDF |

### 3.3 Sections (8 icons)

Primary nav and section headers.

| Icon name          | lucide source        | Used for          |
|--------------------|----------------------|-------------------|
| `IconClaims`       | `Receipt`            | Claims list       |
| `IconEncounters`   | `ClipboardList`      | Encounters        |
| `IconDashboard`    | `LayoutDashboard`    | Home dashboard    |
| `IconAudit`        | `SearchCheck`        | Audit pipeline    |
| `IconReports`      | `BarChart3`          | Reports           |
| `IconSettings`     | `Settings`           | Settings          |
| `IconClinic`       | `Building2`          | Clinic profile    |
| `IconBilling`      | `Wallet`             | Billing & plan    |

### 3.4 States (4 icons)

Loading, empty, error, success — for every list and panel.

| Icon name        | lucide source    | Used for         |
|------------------|------------------|------------------|
| `IconLoading`    | `LoaderCircle`   | Spinner (animate-spin) |
| `IconEmpty`      | `Inbox`          | Empty-state illustration |
| `IconError`      | `OctagonX`       | Error state      |
| `IconSuccess`    | `CircleCheckBig` | Success state    |

### 3.5 Domain / branding (5 icons)

A handful of specialty icons that appear across the marketing site and the
portal landing.

| Icon name             | lucide source | Used for                       |
|-----------------------|---------------|--------------------------------|
| `IconStethoscope`     | `Stethoscope` | Hero / "how it works"          |
| `IconShieldCheck`     | `ShieldCheck` | Security / trust badges        |
| `IconLock`            | `Lock`        | Encryption messaging           |
| `IconBolt`            | `Zap`         | "Fast" / performance claims    |
| `IconLogo`            | custom SVG\*  | The Z logomark, exported as a component |

\* `IconLogo` is **not** from lucide — it's the official Zorva logomark
stored in `apps/portal/src/components/icons/logo.svg` and re-exported
with the same default-prop rules as the other icons.

### 3.6 Optional marketing-only (6 icons)

Used in the public marketing site only. Not in the portal.

| Icon name           | lucide source | Used for                  |
|---------------------|---------------|---------------------------|
| `IconPlay`          | `Play`        | Demo video play button    |
| `IconArrowRight`    | `ArrowRight`  | CTAs, "Learn more"        |
| `IconCheckCircle`   | `CircleCheck` | "What's included" checkmarks |
| `IconExternalLink`  | `ExternalLink`| Outbound links            |
| `IconMail`          | `Mail`        | "Contact" CTA             |
| `IconCalendar`      | `CalendarDays`| "Book a call" CTA         |

**Grand total: 38 icons** (32 portal + 6 marketing).

---

## 4. Sizing & color rules

| Context                 | Size | Stroke | Color (default)    |
|-------------------------|------|--------|---------------------|
| Inline with body text   | 16   | 1.5    | `text-slate-600`    |
| Button icon (default)   | 20   | 1.5    | `currentColor`      |
| Section header          | 24   | 1.5    | `text-primary-700`  |
| Empty-state illustration| 48   | 1.25   | `text-slate-300`    |
| Hero illustration        | 96   | 1.0    | `text-primary-500`  |

**Color rules:**

- An icon's color is `currentColor` by default — wrap it in a span/div
  with a Tailwind text-color class to control it.
- Severity colors **only** apply to the four severity icons (low /
  medium / high / critical). Other icons stay neutral.
- Never fill an icon with the brand primary at full opacity on a primary
  background — the stroke disappears.

---

## 5. Adding a new icon (v1.1+ process)

Once v1 ships, follow this process to add a new icon:

1. Search `lucide-react` first. If it exists and matches the meaning, use it.
2. If no match, propose a custom SVG following the same stroke + viewBox
   conventions. Add it to a new file under `components/icons/`.
3. Update the inventory table in **§3** of this doc with the new icon,
   the lucide source, and the intended use.
4. Run the portal build to confirm tree-shaking and bundle size.

Custom icons must pass the same accessibility rules as the rest of the UI
(see `docs/A11Y_REPORT.md`): decorative icons get `aria-hidden`, semantic
icons get a label.

---

## 6. Acceptance checklist

When the task is "done":

- [ ] `lucide-react` in `apps/portal/package.json` dependencies.
- [ ] `apps/portal/src/components/icons/` exists with `index.tsx`,
      `findings.tsx`, `actions.tsx`, `sections.tsx`, `states.tsx`.
- [ ] All 38 icons in **§3** are exported by name (no wildcards).
- [ ] No `lucide-react` imports outside `components/icons/`.
- [ ] Portal builds without errors and the production bundle is < 250 KB
      gzipped (the icon module itself < 30 KB).
- [ ] This document is updated if any new icon is added during the PR.
