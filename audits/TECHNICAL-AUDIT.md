# Zorva Marketing Site — Technical Audit

**Scope:** Public marketing surface at `https://ai-billing-audit.ashbi.ca` —
the FastAPI app (`src/ai_billing_audit/api.py`), Jinja2 templates under
`src/ai_billing_audit/templates/`, the single CSS bundle
`src/ai_billing_audit/static/dashboard.css`, the `Caddyfile`, and
`docker-compose.yml`.

**Out of scope (read-only, but not audited here):** the audit/encounter
dashboard at `/audits`, `/encounters/upload`, the JSON API surface
under `/api/*`, the Next.js portal at `zorva.ashbi.ca`, and Postgres /
worker containers. Findings below touch those only where they share a
template or a header with the marketing surface.

**Date:** 2026-07-13. **Auditor:** mavis/general (technical read-only).

---

## Executive summary

- **Marketing surface is small and tight.** ~25 marketing templates, all
  share a single `base.html`, single CSS file, and ship a single inline
  `<script>` (~200 lines) for the toast + revenue-opportunity modal.
  No external fonts, no external JS, no third-party trackers, no
  cookies set. The marketing pages are functionally
  no-JS-required — the inline script only enhances the dashboard cards.
- **Security posture is strong and well-commented** (`Caddyfile:1-50`).
  HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, and a
  CSP with `frame-ancestors 'none'` are all present. The author already
  flagged in the `Caddyfile:14-18` comment that the public edge is
  Traefik on the host, and that Traefik's own response-header
  middleware is the work item that has to apply these to end users —
  the in-stack Caddy headers are belt-and-suspenders.
- **Critical SEO gap: no `<meta name="description">`, no Open Graph, no
  Twitter Card, no `<link rel="canonical">`, no JSON-LD structured
  data on any page.** This is the single biggest "free win" in the
  audit — every page has a unique `<title>` (`base.html:6`), so the
  schema is the only thing missing.
- **No `app.mount("/static", StaticFiles(...))` call in `api.py`.**
  The import exists (`api.py:63`) but is never wired up. Every
  template references `/static/dashboard.css` and `/static/favicon.svg`
  (`base.html:7-8`), and the bearer-auth middleware whitelists the
  `/static` prefix (`api.py:1112,1169`) — implying the static dir is
  served by *something*, but `grep -nE 'mount\('` over the whole
  `src/ai_billing_audit/` tree returns only that one import. Either
  the mount is in code I missed, or the marketing site is currently
  serving 404s for CSS and favicon in production. **Verify before
  prioritising anything else.**
- **Cache-Control headers are absent on every response** (no
  `Cache-Control` / `ETag` set anywhere in `api.py` — the in-stack
  Caddy is a reverse proxy, not a cache, and FastAPI's `StaticFiles`
  returns `200` with no cache header by default). The CSS is 100 KB
  unminified, 3,434 lines, ~720 class selectors, single file. Adding
  `Cache-Control: public, max-age=31536000, immutable` on hashed
  static assets would make repeat-visit LCP a non-event.
- **No skip-to-content link, no ARIA landmarks, no `aria-current` on
  the active nav item** (`base.html:11-36`). All of these are
  cheap, one-line fixes and would materially improve WCAG 2.4.1 /
  2.4.4 / 4.1.2 compliance for the marketing funnel.

---

## 1. Performance

### 1.1 CSS

- **File:** `src/ai_billing_audit/static/dashboard.css` — 3,434 lines,
  99,263 bytes, unminified. No build step in the repo, no minified
  companion. **P1 — minify for production.**
  - Approx. 117 lines of comments / blank lines; 722 class selectors;
    many of the selectors are dashboard-specific (`.audit-card`,
    `.finding-actions`, `.detail-grid`, `.paste-form`,
    `.encounter-search`) and unused on the 25 marketing pages. A
    quick eyeball pass over `home.html`, `pricing.html`, `faq.html`,
    `about.html`, `contact.html` shows that the marketing surface
    uses a small subset: `.page`, `.container`, `.page-head`,
    `.btn`, `.muted`, `.small`, `.footer`, `.topbar`, plus the
    per-page sections (`.hero`, `.pillars`, `.pricing-card`,
    `.faq-section`, `.contact-form`, `.proof`, `.alt-path`). The
    rest of the file (~70%) is dashboard chrome.
  - **Two viable paths:** (a) minify the single bundle
    (`lightningcss` or `cssnano` as a build step) — easy, gets
    ~30% size reduction; (b) split into `marketing.css` + `app.css`
    and only load `app.css` on `/audits`, `/encounters/upload`,
    `/encounter/...` — bigger change but ~80% reduction on
    marketing pages. (a) is the P1; (b) is the P2.
  - Per the Caddyfile the in-stack proxy has no `brotli` /
    `gzip` directive, and the Traefik comment in
    `docker-compose.yml:32-50` notes compression is a host concern.
    Verify the public Traefik edge is configured with gzip /
    brotli for `text/css` and `application/javascript`. If it
    isn't, the 100 KB CSS balloons every cold-cache page load.

### 1.2 JavaScript

- **File:** `src/ai_billing_audit/static/upload.js` — 17,458 bytes,
  483 lines, unminified. **P2 — minify if the upload page hits
  real traffic, otherwise leave it.** It is **only loaded on
  `/encounters/upload`** (`templates/encounters_upload.html:150`)
  and never on the marketing surface. The marketing pages
  only pull in the inline `<script>` block in `base.html:55-269`
  (toast helper + revenue-opportunity modal).
- The inline script in `base.html:55-269` is ~200 lines, mostly
  the revenue-opportunity modal (open/close, fetch, render,
  escape). It is **not** render-blocking (it is at the bottom
  of `<body>`), has no `document.write`, no synchronous
  network calls, and uses `defer`-equivalent placement
  (script after content). It only fires for the modal trigger
  buttons; if no `.opp-row` exists, the IIFE allocates the
  modal element lookup once and never re-runs.
- The inline script also uses `escapeHtml` (`base.html:92-99`)
  for every value pulled from JSON before `innerHTML`
  interpolation. **Good — XSS-safe by construction.**
- No `defer` / `async` attributes on the inline `<script>` —
  none needed; script is at end of body.
- No third-party analytics, no Google Tag Manager, no Facebook
  Pixel, no Hotjar. **Strong — none of the marketing-page
  weight comes from third-party JS.**

### 1.3 Images

- **No `<img>` tags anywhere in the marketing templates**
  (`grep -nE '<img' src/ai_billing_audit/templates/*.html`
  returns zero hits). The only raster-ish asset is the SVG
  favicon (`static/favicon.svg`, 293 bytes).
- **No `og-image.png` / `og-image.jpg` exists on disk**
  (`find . -name "og-image*"` returns nothing). The base
  template doesn't reference an og-image either. Social-card
  link previews on Slack / Twitter / LinkedIn will be blank
  cards with no image. **P0 — generate a 1200×630 PNG and
  add `<meta property="og:image" ...>` to `base.html` head.**
- The single SVG favicon is fine. No `<link rel="apple-touch-icon">`
  in `base.html:1-10`, so iOS home-screen installs will fall
  back to a screenshot — **P2** add `apple-touch-icon` if
  marketing pages are expected to be PWA-installed.

### 1.4 Font loading

- **System font stack only.** `--font-sans` =
  `-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI",
  system-ui, sans-serif` (`static/dashboard.css:69`);
  `--font-mono` = `ui-monospace, "SF Mono", "JetBrains Mono",
  Menlo, monospace` (`dashboard.css:70`).
- No `@import`, no `<link rel="preload" as="font">`, no
  `font-family` web font anywhere. **This is a strong choice
  for performance** — zero font-related network requests,
  zero FOIT, zero font-display swap shifts. Worth calling
  out as a positive.

### 1.5 Cache-Control / static-asset headers

- **No `Cache-Control` header set anywhere in `api.py`.**
  `grep -nE 'cache-control|cache-Control' src/ai_billing_audit/api.py`
  returns nothing.
- FastAPI's `StaticFiles` (if/when mounted — see §1.1 finding
  about the missing `app.mount`) returns `200` with no
  `Cache-Control` by default. The Caddy in-stack proxy does
  not add cache headers either — the `header` directives in
  `Caddyfile:43-47` set security headers, not cache.
- **P0 — verify the public Traefik edge is setting
  `Cache-Control: public, max-age=31536000, immutable` on
  `*.css`, `*.js`, `*.svg`, and the (missing) `og-image.*`.
  If it isn't, the 100 KB CSS is re-downloaded on every
  page navigation.** If the current mount is missing
  entirely, fixing that mount should be the same work
  item.
- If / when adding content-hashed filenames, the
  application side should also set
  `ETag` + `Last-Modified` so the client can revalidate
  without re-downloading. FastAPI's `StaticFiles` does
  emit `ETag` and `Last-Modified` automatically; the
  application code just needs to *not* strip them in a
  future middleware.

### 1.6 Render-blocking resources

- `base.html:7` is a single `<link rel="stylesheet" href="/static/dashboard.css">`
  placed in `<head>`. This **is** render-blocking by
  definition, but the CSS file is 100 KB — non-trivial
  critical-bytes. **P2 — once §1.1 lands and the file is
  minified and/or split, optionally inline the critical
  ~5 KB of marketing CSS and async-load the rest.**
- No `<script src="...">` in `<head>`. The inline `<script>`
  is at end of body. **Good.**

### 1.7 Page-weight estimate

Approximate transfer per cold-cache marketing visit (assuming
gzip/brotli at ~75% on the CSS, no compression on the small
HTML):

| File | Raw | After ~gzip |
|---|---|---|
| `base.html` + page | ~12 KB | ~4 KB |
| `dashboard.css` | 99 KB | ~25 KB |
| `favicon.svg` | <1 KB | <1 KB |
| **Total** | **~112 KB** | **~30 KB** |

This is **well within Core Web Vitals "good" LCP territory**
on a 4G connection (1.4 MB / 3.4 s budget per Lighthouse
defaults). The 100 KB CSS dominates — §1.1 is the lever.

### 1.8 Preconnect / dns-prefetch

- No `<link rel="preconnect">` in `base.html`. The marketing
  pages make zero third-party network calls (no analytics, no
  font CDN, no CDN), so there is nothing to preconnect to.
  **Good — nothing to add.**

---

## 2. SEO

### 2.1 `<title>` per page

- Every marketing template overrides `{% block title %}` in
  line 2 of the file. Confirmed by `grep -nE 'block title'`
  on every `templates/*.html` — all 30 templates have a unique
  title. Examples:
  - `home.html:2` → "Zorva — AI pre-bill audit for Alberta clinics"
  - `pricing.html:2` → "Pricing — Zorva"
  - `security.html:2` → "Security & compliance — Zorva"
  - `about.html:2` → "About — Zorva by Ashbi Design"
  - `case_study_detail.html:2` → `{{ cs.title }} — Zorva case study`
    (dynamic — verify the case-study list sets non-empty
    `cs.title`).
- The base default is `{% block title %}Zorva{% endblock %}`
  (`base.html:6`) so a child that forgets to override still
  emits *something* rather than an empty `<title>`. **Good.**

### 2.2 `<meta name="description">`

- **Missing on every page.** `grep -nE 'meta name='
  src/ai_billing_audit/templates/*.html` returns only
  `base.html:5` (the viewport meta). Google will
  auto-generate snippets, which is usually worse than
  nothing for conversion. **P0 — add a `description` block
  to `base.html` and override it per template.** Suggested
  defaults:
  - `home.html`: "Zorva audits every Alberta AHCIP claim
    before submission — catching missed codes, underbilled
    modifiers, and shadow-billed services. 60-day no-cost
    pilot."
  - `pricing.html`: "Three flat-fee tiers, no per-claim
    charge, no recovery share. $499 / $1,499 / $2,999+ CAD
    per month. AKS safe-harbor-aligned for US pilots."

### 2.3 Open Graph / Twitter Card

- **Missing entirely.** `grep -nE 'og:|twitter:'
  src/ai_billing_audit/templates/*.html` returns nothing.
  `<base.html:1-10>` has only the `<meta charset>`,
  viewport, title, stylesheet link, and favicon.
- **P0 — add to `base.html` head:**
  ```html
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Zorva">
  <meta property="og:title" content="{% block og_title %}{{ self.title() }}{% endblock %}">
  <meta property="og:description" content="{% block og_description %}{{ self.description() }}{% endblock %}">
  <meta property="og:url" content="{{ request.url }}">
  <meta property="og:image" content="https://ai-billing-audit.ashbi.ca/static/og-image.png">
  <meta property="og:locale" content="en_CA">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{{ self.og_title() }}">
  <meta name="twitter:description" content="{{ self.og_description() }}">
  <meta name="twitter:image" content="https://ai-billing-audit.ashbi.ca/static/og-image.png">
  ```
  (and generate the `og-image.png` — see §1.3).

### 2.4 Canonical URLs

- **Missing on every page.** `grep -nE 'canonical'
  src/ai_billing_audit/templates/*.html` returns nothing.
- `home.html` and `audits` (`index.html`) both serve from `/`
  in different code paths (`api.py:1368` mounts `home.html`,
  `api.py:1382` is `/audits`); `encounter_detail` and
  `encounter_detail_plural` (`api.py:5830`) are the same
  content via two URLs. **P2 — add a canonical block to
  `base.html`** so duplicate-URL situations (the
  encounter-detail singular/plural split, the
  `?status=` filter variants on `/audits`) don't fragment
  search-equity:
  ```html
  <link rel="canonical" href="{% block canonical %}{{ request.url }}{% endblock %}">
  ```

### 2.5 Structured data (JSON-LD)

- **Missing entirely.** No `application/ld+json` script tag
  in any template.
- **P1 — add `Organization` JSON-LD to `base.html` (renders
  on every page):**
  ```html
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": "Zorva by Ashbi Design",
    "url": "https://ai-billing-audit.ashbi.ca",
    "logo": "https://ai-billing-audit.ashbi.ca/static/og-image.png",
    "description": "Pre-submit audit for Alberta AHCIP medical billing.",
    "founder": { "@type": "Person", "name": "Cameron Ashley" },
    "address": { "@type": "PostalAddress", "addressRegion": "ON", "addressCountry": "CA" },
    "contactPoint": { "@type": "ContactPoint", "email": "cameron@ashbi.ca", "contactType": "sales" }
  }
  </script>
  ```
- **P2 — add `SoftwareApplication` JSON-LD on `/pricing`**
  and `FAQPage` on `/faq`. The FAQ page in particular has
  20+ `<details>` elements (`faq.html:18-156`) that are
  almost free to convert to `FAQPage` schema — same content,
  just wrapped in `<script type="application/ld+json">`.
  Ripe for the rich-result treatment.

### 2.6 `robots.txt` and `sitemap.xml`

- `robots.txt` — present, correct.
  - `src/ai_billing_audit/robots.py:21-36` defines the
    response; `api.py:4555-4567` wires the route. Disallows
    `/api/`, `/audits`, `/encounters/`, `/encounter/`,
    `/admin`. Points to the sitemap.
- `sitemap.xml` — present, complete.
  - `src/ai_billing_audit/feeds.py:124-148` lists 25
    public marketing paths; `api.py:4536-4553` renders the
    XML. All marketing routes I traced are in the list.
  - `feeds.py:139` sets `priority=0.8` for `/`, `/pricing`,
    `/try` and `0.5` for everything else. Reasonable.
  - `lastmod` is set to "now" (`feeds.py:132`) which is
    technically wrong but harmless — Google treats
    unchanged `lastmod` as a soft signal, not a ranking
    factor. **P2** — wire `lastmod` to a per-route mtime if
    the marketing site moves to a build step.
- `rss.xml` — present, Atom 1.0.
  - `feeds.py:36-79` builds the feed; `api.py:4515-4533`
    serves it. Combines blog + changelog. **Good.**

### 2.7 `hreflang` for `en-CA`

- **Missing.** `grep -nE 'hreflang' src/ai_billing_audit/templates/*.html`
  returns nothing.
- The site is currently English-only and serves all of
  Canada + US. The Alberta AHCIP angle is Canada-specific
  (the OHIP / MSP clones are on the 2027 roadmap per
  `home.html:74`). **P2 — add `<link rel="alternate"
  hreflang="en-CA" href="...">` to `base.html`** with a
  self-referencing `en` and `en-CA` so the Google Canada
  index correctly attributes the page. US pilots (HIPAA
  template) are on-request, so `en-US` is premature.

### 2.8 Heading hierarchy

- Every template has exactly one `<h1>` (verified by
  `grep -cE '<h1[ >]' src/ai_billing_audit/templates/*.html`).
- `<h2>` is used for major sections (e.g. `home.html:51`,
  `pricing.html:64`); `<h3>` for sub-sections (e.g.
  `pricing.html:33-50` per feature). No skipped levels
  observed. **Good.**

### 2.9 Internal link hygiene

- Footer (`base.html:36-50`) links to 12 key pages
  including `/blog`, `/compare`, `/pilot`, `/legal/*`.
  Topbar (`base.html:11-29`) links to 9 key pages.
  **Internal link graph is solid** — every public page
  has at least 3 inbound links from the topbar/footer
  plus contextual links from other pages.

---

## 3. Accessibility (WCAG 2.1 AA)

### 3.1 Skip-to-content link

- **Missing.** `base.html:1-55` has no
  `<a class="skip-link" href="#main">Skip to content</a>`
  before the topbar.
- **P1 — add a visually-hidden-until-focused skip link as
  the first child of `<body>`.** 1-line CSS:
  ```css
  .skip-link { position: absolute; left: -9999px; }
  .skip-link:focus { left: 1rem; top: 1rem; background: var(--color-brand); color: #fff; padding: 0.5rem 1rem; border-radius: 4px; z-index: 1000; }
  ```
  And change `<main class="page">` (`base.html:30`) to
  `<main class="page" id="main" tabindex="-1">` so the
  skip target is the actual content.

### 3.2 ARIA landmarks

- The base template has `<header class="topbar">` (line 11),
  `<nav>` (line 16, implicit), `<main class="page">`
  (line 30), and `<footer class="footer">` (line 36).
  These are *implicit* landmarks in HTML5.
- Modern screen readers (NVDA, JAWS, VoiceOver) honor
  the implicit roles, but **WCAG 4.1.2 best practice
  recommends explicit `role="banner"` / `role="navigation"`
  / `role="main"` / `role="contentinfo"` on the top-level
  wrappers** for older AT (IE11-era JAWS, TalkBack on
  older Android).
- **P2 — add the explicit roles**:
  ```html
  <header class="topbar" role="banner">
  <nav role="navigation" aria-label="Primary">
  <main class="page" role="main" id="main" tabindex="-1">
  <footer class="footer" role="contentinfo">
  ```

### 3.3 Active-nav state

- `base.html:17-25` marks the active link with
  `class="is-active"` but no `aria-current="page"`.
- **P2 — add `aria-current="page"` to the active
  link** so screen-reader users hear "current page"
  rather than just "Home" with no context. The
  pattern:
  ```html
  <a href="/" {% if request.url.path == "/" %}class="is-active" aria-current="page"{% endif %}>Home</a>
  ```

### 3.4 Color contrast

- **Primary text** (`--color-fg: #1a1f2b` on
  `--color-bg: #f7f8fa`) — contrast ratio ~14.5:1. **AAA pass.**
- **`--color-fg-muted: #5b6675`** on bg — ~5.5:1. **AA pass
  for normal text, AAA for large.** Used by `.muted` (line 115).
  Fine.
- **`--color-fg-subtle: #8a93a3`** on bg — ~2.86:1. **FAILS
  AA for normal text (4.5:1) and AA Large (3:1) as a regular
  weight.** Used by `.subtle` (line 116).
  - **P2 — bump `--color-fg-subtle` to ~#6b7280** (a 4.7:1
    ratio) so `.subtle` is at least AA-passable.
  - **Searched templates for `subtle` class — 0 hits.**
    The class is defined but unused on the marketing
    surface, so this is a *latent* bug, not a current
    one. Still worth fixing the token to make the
    design system safe-by-default.
- **Brand button** (`--color-brand: #2563eb` background,
  white text) — ~5.2:1. **AA pass.** Good.
- **Warn / flag colors** (`--color-warn: #d97706` on
  `--color-warn-soft: #fffbeb`) — ~3.5:1. AA for large text
  only. Used for status badges in dashboard chrome; not
  used on the marketing surface.
- **Skip-link colors** — N/A; the skip link doesn't exist
  yet (§3.1).

### 3.5 Form labels

- `contact.html:43-92` uses `<label class="contact-form__label">`
  wrapping each `<input>` / `<textarea>`. The label text
  is *before* the input inside the same `<label>`, which
  is the implicit-association pattern. **Good** — the label
  is associated without `for=`/`id=`, and screen readers
  will pick it up.
- `demo-request.html:71-110` — same pattern. **Good.**
- `roi.html:17-100` — let me check:
  - Confirmed via `grep -nE '<label|<input' src/ai_billing_audit/templates/roi.html` —
    every input is wrapped in a `<label class="roi-form__label">`.
    **Good.**
- `<input type="file">` in `contact.html:75-78` is in a
  `<label>` with a `<span class="muted small">` helper
  hint. The label includes the file picker, the file
  name, and the helper text — verbose, but the file
  picker is announced as "Claims file (optional — 837P,
  CSV, or FHIR) Drop your de-identified claims here…"
  which is overly long. **P3 — consider giving the
  file input a short `aria-label` and demoting the
  help text to `aria-describedby`.**
- `<select name="emr">` in `demo-request.html:92-104` —
  the wrapping `<label>` has "EMR / billing system" as
  the visible label; the options are verbose
  ("TELUS PS Suite", "OSCAR Pro", "Accuro (QHR)", "Med
  Access (TELUS)"). **Good** — the verbose parenthesised
  values are visible text, not aria-labels, so they don't
  clutter the AT experience.
- `required` is set on the truly required fields
  (`contact.html:46,52,58,64`, `demo-request.html:74,79,84`).
  HTML5 `required` works without JS. **Good.**

### 3.6 Focus styles

- `dashboard.css:559-561` — `.audit-card__opportunity-btn:focus-visible`
  has a 2px solid brand outline. Good for that one button.
- `dashboard.css:952-958` — `.paste-form input:focus` sets
  `outline: none` and replaces with `box-shadow: 0 0 0 3px var(--color-brand-soft)`.
  Visible, but the contrast of `--color-brand-soft: #eff5ff`
  (very light blue) against the white input is **marginal
  (~1.3:1)** — fails WCAG 2.4.7 (Focus Visible) which
  requires a 3:1 contrast between focused and unfocused
  states. The outline-replacement has a brand-colored
  border too (`border-color: var(--color-brand)`), so the
  *combined* visual change is enough in practice, but
  the spec is satisfied via border-color rather than the
  box-shadow. **P3 — bump the box-shadow to a darker
  blue or keep the 2px outline instead of `outline: none`.**
- **No global `:focus-visible` rule for `a`, `button`, `input`**
  outside the three selectors above. Default browser
  outlines are suppressed by `* { box-sizing: border-box; }`
  indirectly through not being overridden — actually, the
  default outline is *still on* because no rule resets it
  globally. So the default browser focus ring is the
  fallback. **Acceptable** but inconsistent — Chrome /
  Safari / Firefox each draw different rings.
- **P1 — add a global `:focus-visible` rule** for
  consistent focus styling:
  ```css
  a:focus-visible, button:focus-visible, input:focus-visible,
  select:focus-visible, textarea:focus-visible, summary:focus-visible {
    outline: 2px solid var(--color-brand);
    outline-offset: 2px;
  }
  ```

### 3.7 Alt text on images

- **No `<img>` tags in any marketing template** (verified
  via `grep -nE '<img' src/ai_billing_audit/templates/*.html`).
  No `alt`-related WCAG findings. **N/A.**

### 3.8 Heading hierarchy per page

- Every marketing template has exactly one `<h1>`
  (verified — §2.8). The `<h2>` is used for major
  sections, `<h3>` for sub-sections. **Good.**

### 3.9 `prefers-reduced-motion`

- `dashboard.css:424,650,845,904` defines
  `transition` rules (no `@keyframes` animations).
  The transitions are all 0.1s–0.2s colour/opacity
  fades — not seizure-inducing.
- **No `@media (prefers-reduced-motion: reduce)` block**
  in the CSS. **P3 — add:**
  ```css
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { transition: none !important; animation: none !important; }
  }
  ```
  Cheap to add, satisfies WCAG 2.3.3 (Animation from
  Interactions) for users who set the OS preference.

### 3.10 Other WCAG-relevant observations

- **Touch targets ≥44px** — `dashboard.css:1235,1253,1443,1468`
  set `min-height: 44px` inside `@media (max-width: 768px)`.
  The topbar nav links (`base.html:17-25`) inherit
  default button sizing which on mobile may be <44px.
  **P3 — verify the topbar nav hit areas on mobile**;
  the comments in `dashboard.css:1200-1280` document
  the mobile-first tap-target intent but the topbar
  is not in scope of those rules.
- **`<details>`/`<summary>` for FAQ** (`faq.html:18-156`)
  — native HTML disclosure widget, keyboard-accessible
  by default. **Good.**
- **Toast container** (`base.html:53`) has
  `role="status" aria-live="polite"` — correct.
- **Modals** (`_revenue_opportunity_modal.html:18-20`,
  `_bulk_confirm_modal.html:29-31`) have
  `role="dialog" aria-modal="true" aria-labelledby="..."`.
  Focus is moved into the modal on open
  (`base.html:135`), Escape closes
  (`base.html:78-80`). **Good** — this is the
  dashboard modal, not the marketing surface, but the
  pattern is correct.

---

## 4. Security

### 4.1 Security headers

All five core headers are set in the in-stack Caddy
(`Caddyfile:43-47`):

```caddy
header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
header X-Content-Type-Options "nosniff"
header X-Frame-Options "DENY"
header Referrer-Policy "strict-origin-when-cross-origin"
header Content-Security-Policy "default-src 'self'; img-src 'self' data:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' https://api.minimax.chat; frame-ancestors 'none'"
```

- **HSTS** — 2-year max-age + `includeSubDomains` + `preload`.
  Strong; this site should be on the HSTS preload list.
  **P3 — verify the site is submitted to hstspreload.org.**
  The `preload` directive is meaningless without that
  submission.
- **`X-Frame-Options: DENY`** is set *and* the CSP has
  `frame-ancestors 'none'`. `frame-ancestors` is the
  modern equivalent and supersedes `X-Frame-Options`
  in browsers that honor CSP — having both is
  belt-and-suspenders. **Good.**
- **CSP** — the `'unsafe-inline'` on both `script-src`
  and `style-src` is the main weakness. The rationale
  in the `Caddyfile:20-32` comment is honest: templates
  render inline `<script>` (`base.html`, `encounter_detail*`)
  and inline `<style>` / Jinja-rendered style attrs.
  - **P2 — adopt a nonce-based CSP** instead of
    `'unsafe-inline'`. The FastAPI app would emit a
    per-request nonce, pass it to Jinja2 via a global
    (`templates.env.globals["csp_nonce"] = ...`),
    and base.html would render
    `<script nonce="{{ csp_nonce }}">...</script>`.
    Then the CSP becomes
    `script-src 'self' 'nonce-{{ csp_nonce }}'`. Inline
    style still needs `'unsafe-inline'` until each
    `style="..."` is moved to a class (the
    `contact.html:99`, `index.html:191` and others
    — see §4.5). For a marketing site that doesn't
    take user input, `'unsafe-inline'` on style is
    a *much* smaller risk than on script.
- **No `Permissions-Policy` header.** Browsers ship
  geolocation / camera / microphone / payment APIs
  that a marketing site has no business invoking.
  **P2 — add to the Caddy header block:**
  `header Permissions-Policy "geolocation=(), camera=(), microphone=(), payment=()"`
- **No `Cross-Origin-Opener-Policy` /
  `Cross-Origin-Embedder-Policy` /
  `Cross-Origin-Resource-Policy`.** Not strictly required
  for a marketing surface; would matter if / when the
  marketing page embeds the dashboard in an iframe. The
  current design doesn't, so **P3 — leave for now**.
- **CORS** — `api.py:1067-1077` sets up CORS via
  `CORSMiddleware` with `allow_origin_regex=r"^https://([a-z0-9-]+\.)?ashbi\.ca$"`,
  `allow_methods=["GET", "POST", "OPTIONS"]`,
  `allow_headers=["Content-Type", "X-User-Id",
  "X-User-Role"]`, `allow_credentials=False`. The regex
  is anchored on both ends. **Good** — the `ashbi.ca`
  wildcard catches `zorva.ashbi.ca` for cross-origin
  fetches. `allow_credentials=False` is correct for
  the no-cookie, no-bearer pattern the portal uses.
- **`X-Powered-By`** — not explicitly set. Uvicorn's
  default is `server: uvicorn`. **P3** — strip it:
  add `header -Server` (Caddy 2.7+) or set
  `server_header = ""` in the uvicorn CLI.

### 4.2 The Traefik public-edge gap

- The `Caddyfile:11-19` comment is explicit: **"the
  headers are applied on the INTERNAL hop only. For the
  headers to reach end-users, Traefik's own
  response-header middleware must be configured on the
  host (separate work item — tracked as a follow-up
  note in the kanban comment)."**
- This is a **P0** until verified — if the host Traefik
  router at `/opt/traefik/dynamic/routers.yml` does not
  already include a `responseHeaders` middleware that
  re-applies HSTS / CSP / X-Frame-Options / X-Content-Type-Options
  / Referrer-Policy, the public visitors at
  `https://ai-billing-audit.ashbi.ca` get **none** of
  these headers. The Caddy in the stack only sees
  Traefik→Caddy traffic on the loopback.
- **P0 — verify `cat /opt/traefik/dynamic/routers.yml
  | grep -A20 'ai-billing-audit'`** on the VPS and
  confirm the `responseHeaders` middleware is wired
  for the `ai-billing-audit.ashbi.ca` router. If it
  isn't, this is the single highest-impact fix in the
  entire audit.

### 4.3 Cookies

- **No cookies set anywhere.** `grep -nE 'Set-Cookie|cookie'
  src/ai_billing_audit/api.py` returns two matches and
  both are in comments / docstrings. The
  `_bearer_auth` middleware (`api.py:1118-1234`) uses
  `Authorization: Bearer` headers exclusively, never
  cookies.
- Therefore PHIPA / HIA "consent banner" requirements
  do **not** apply — there is no non-essential
  cookie to consent to, no analytics tracking, no
  third-party data sharing on the marketing site.
  The site is **cookie-free**, which is materially
  better for both compliance and Core Web Vitals.
  **Strong posture — nothing to add.**
- For full HIA / PIPEDA coverage, the legal posture
  is documented at `legal_privacy.html` (the
  `PIPEDA Statement A` / `HIA Information Manager
  Agreement` text — I did not read the full body,
  but the template exists and is wired into the
  nav).

### 4.4 Inline event handlers / inline scripts

- **Zero `onclick=`, `onerror=`, `onload=`,
  `onmouseover=`** in any marketing template
  (`grep -cE 'onclick|onerror|onload|onmouseover'
  src/ai_billing_audit/templates/*.html` returns 0
  for every file). **Good** — all event handling
  is via `addEventListener` in the inline script
  block at `base.html:55-269`.
- The inline script at `base.html:55-269` uses
  `escapeHtml` (`base.html:92-99`) before
  `innerHTML` interpolation of any JSON-derived
  string. **Good — XSS-safe.**
- `setAttribute("href", ...)` and `textContent =`
  are used wherever possible (`base.html:131, 138-140`),
  avoiding `innerHTML` for untrusted data. **Good.**
- No `eval`, no `new Function`, no `document.write`,
  no `setTimeout(string, ...)`. **Good.**
- The CSP `script-src 'self' 'unsafe-inline'` allows
  the inline block. The nonced-CSP refactor (§4.1)
  would harden this further.

### 4.5 Inline styles

- The marketing templates have a handful of `style="..."`
  attributes:
  - `case_studies.html:4` —
    `<main class="container" style="max-width: 880px;">`
  - `case_study_detail.html:4` —
    `<main class="container" style="max-width: 760px;">`
  - `contact.html:4` — `<main class="container" style="max-width: 640px;">`
  - `contact.html:99` — `style="margin-top: var(--space-4);"`
  - `legal_privacy.html:4`, `legal_terms.html:4`,
    `roi.html:4` — `<main class="container" style="max-width: 760px/880px;">`
  - `index.html:191` —
    `<span class="bar-fill" style="width: {{ '%.1f' % _pct }}%">`
    (server-rendered percentage — *user-controllable
    through the value of `_pct`*)
  - `encounters_upload.html:21,32,43,55,94,121` —
    dashboard pages, not marketing
- The **server-rendered `style="width: {{ ... }}%"`
  in `index.html:191` is the only one that takes a
  Jinja variable**. If `_pct` is ever attacker-
  controlled and the value includes a `"` (closing
  the attribute), this becomes HTML-injectable. From
  the variable name (`_pct`) and the format
  (`%.1f`), the code restricts this to a float, so
  the practical XSS surface is zero — but the
  pattern is a footgun for future edits. **P3 —
  sanitise via a custom Jinja filter or a CSS
  custom-property (`style="--pct: {{ _pct }}"`)**
  to keep template variables out of style attrs.
- **P3 — move the static `max-width` and `margin-top`
  styles to CSS classes.** One class per layout
  variant (`container--narrow`, `container--reading`,
  `mt-4`) keeps templates clean and removes the
  need for `'unsafe-inline'` on `style-src` (§4.1).

### 4.6 Trusted Types / nonce

- **No Trusted Types policy, no nonce.** Per §4.1,
  the CSP allows `'unsafe-inline'` for both script
  and style. **P2** — see §4.1 for the migration
  plan. A `require-trusted-types-for 'script'`
  directive is the *most* aggressive hardening
  and probably overkill for a marketing surface
  with no third-party JS.

### 4.7 Other security findings

- **No mixed content risk** — every `<a href="/...">` is
  relative; the only absolute URLs in marketing
  templates are `mailto:` and the parent-studio
  link to `https://ashbi.ca` (`about.html:89`),
  which is HTTPS. **Good.**
- **No `target="_blank"` without `rel="noopener"`.**
  None of the external links open in a new tab.
  **Good.**
- **Form action is same-origin** —
  `contact.html:43` and `demo-request.html:71` both
  POST to `/contact`. **Good.**
- **File-upload accept-list is sensible** —
  `accept=".837,.edi,.txt,.csv,.json,.xml,.fhir,.zip"`
  on `contact.html:77`. The `accept` attribute is a
  UX hint, not a security control (the server must
  re-validate), and the FastAPI route does re-validate.
  **Good.**
- **Rate limit on `/contact` and `/api/encounters/upload`**
  — `api.py:1262-1310` implements an in-process
  per-IP limiter at 10 req/min, with a fallback
  comment that the public Traefik edge also has
  a rate-limit middleware. The implementation
  evicts timestamps correctly (`api.py:1289-1294`)
  and emits a 429 with `Retry-After: 60`. **Good.**
  The comment at `api.py:1264-1273` correctly
  documents that the limit is `N_WORKERS * 10/min`
  if scaled past one uvicorn worker — not a current
  issue but a P3 if the deployment ever scales out.
- **No CSRF token on `/contact` POST.** Forms
  without auth don't need CSRF tokens (the bearer
  middleware doesn't gate `/contact`), and the
  rate-limit + form-content checks are the
  practical defense. The current setup is fine
  for a public contact form; if the form ever
  becomes authenticated, add a CSRF token. **N/A now.**

---

## 5. Cross-cutting observations

### 5.1 The missing `/static` mount

- `api.py:63` imports `from fastapi.staticfiles import StaticFiles`,
  but a `grep -nE 'app\.mount' src/ai_billing_audit/`
  returns only the import line. There is no
  `app.mount("/static", StaticFiles(directory="..."))` call.
- `base.html:7-8` references `/static/dashboard.css` and
  `/static/favicon.svg`, and `api.py:1112,1169` whitelists
  `/static*` in the bearer middleware.
- Either:
  - The mount exists in a file I didn't read (a sibling
    module imported by `create_app()` after the visible
    7,000 lines); **OR**
  - The site is currently serving 404s for the CSS and
    favicon in production, in which case the marketing
    pages render with **zero** styling and the
    home-page hero (`<h1>Find the revenue your billers
    are leaving on the table.</h1>` etc.) is the only
    visible content.
- **P0 — verify the static mount is in fact wired
  up.** If it is, document it in the audit and move
  on. If it isn't, this is the single highest-impact
  bug in the audit.

### 5.2 Inline-script comment

- The inline `<script>` in `base.html:55-269` is ~200
  lines. Per §4.1 the safer pattern is a nonce-based
  CSP. As a smaller fix, the script could be moved to
  `/static/app.js` and loaded with `<script src="/static/app.js" defer>`.
  Then the CSP drops to `script-src 'self'` and there's
  no `'unsafe-inline'` exposure at all. **P2** —
  same effort as the nonce refactor but simpler.

### 5.3 `/audits` route in the sitemap

- `feeds.py:148` lists `/audits` in `PUBLIC_MARKETING_PATHS`,
  but `robots.py:30` disallows `/audits`. The
  sitemap entry is at best redundant — search engines
  that respect robots.txt will skip the URL in the
  sitemap anyway, and the sitemap doesn't add
  discovery value for a route we don't want indexed.
  **P3** — drop `/audits` from the sitemap list for
  internal consistency. (The route is auth-gated in
  practice, so even with no robots disallow it
  wouldn't be meaningfully indexable.)

---

## 6. Prioritized fix list

### P0 — block today

1. **Verify Traefik's public-edge response headers.** The
   `Caddyfile:11-19` comment is explicit: the in-stack
   Caddy headers don't reach end users unless the host
   Traefik also applies them. If
   `/opt/traefik/dynamic/routers.yml` does not include a
   `responseHeaders` middleware on the
   `ai-billing-audit.ashbi.ca` router, the site is
   shipping without HSTS / CSP / X-Frame-Options /
   X-Content-Type-Options / Referrer-Policy today. *(§4.2)*
2. **Verify the static-files mount exists in
   `api.py`.** `from fastapi.staticfiles import StaticFiles`
   is imported (`api.py:63`) but `app.mount("/static", ...)`
   is never called in the visible code. Every marketing
   page references `/static/dashboard.css` and
   `/static/favicon.svg`; if the mount is missing, the
   marketing surface renders unstyled. *(§5.1)*
3. **Add `<meta name="description">` per page** (with
   `base.html` default + per-template override). Zero
   description meta on any page right now
   (`base.html:1-10` only has charset / viewport /
   title / stylesheet / favicon). *(§2.2)*
4. **Add Open Graph + Twitter Card meta** to
   `base.html`, with a per-template override. Currently
   zero OG / Twitter tags. *(§2.3)*
5. **Generate and reference an `og-image.png`** (1200×630
   px) at `/static/og-image.png` and wire it into the OG
   meta. Currently no OG image exists on disk. *(§1.3, §2.3)*

### P1 — this week

6. **Add a global `:focus-visible` rule** to
   `dashboard.css` (a / button / input / select /
   textarea / summary → 2px brand outline at 2px offset).
   Currently focus rings are inconsistent across the
   site. *(§3.6)*
7. **Add a skip-to-content link** as the first child of
   `<body>` in `base.html`, with the visually-hidden-
   until-focused pattern. Currently absent. *(§3.1)*
8. **Minify `dashboard.css`** (100 KB → ~30 KB
   pre-compression) and add long-cache
   `Cache-Control: public, max-age=31536000, immutable`
   on the public Traefik edge. The file is single-pass
   unminified today, no build step. *(§1.1, §1.5)*
9. **Add `Organization` JSON-LD** to `base.html` (renders
   on every page; one-time win for the Knowledge
   Graph). *(§2.5)*

### P2 — next sprint

10. **Add `hreflang="en-CA"` to `base.html`** (and the
    en fallback for completeness). *(§2.7)*
11. **Add `<link rel="canonical">` to `base.html`** with
    per-template override. *(§2.4)*
12. **Refactor the inline `<script>` in `base.html:55-269`
    to `/static/app.js`** loaded with `defer`, and drop
    `'unsafe-inline'` from `script-src` in the CSP.
    *(§4.1, §5.2)*
13. **Add `FAQPage` JSON-LD** on `/faq` (the 20+ existing
    `<details>` items are 80% of the way there). *(§2.5)*
14. **Add `SoftwareApplication` JSON-LD** on `/pricing`.
    *(§2.5)*
15. **Add `Permissions-Policy` header** in the Caddyfile
    (`geolocation=(), camera=(), microphone=(),
    payment=()`). *(§4.1)*
16. **Move static `style="max-width: ..."` /
    `style="margin-top: ..."` attrs to CSS classes** so
    the CSP can drop `'unsafe-inline'` from `style-src`
    too. *(§4.5)*
17. **Add explicit ARIA landmark roles** on the top-level
    `<header>` / `<nav>` / `<main>` / `<footer>` in
    `base.html`. *(§3.2)*
18. **Add `aria-current="page"`** to the active topbar
    link in `base.html`. *(§3.3)*
19. **Bump `--color-fg-subtle` from `#8a93a3` to
    `#6b7280`** (4.7:1 on the bg) so the `.subtle` class
    is AA-safe even though it's not currently used on
    marketing pages. *(§3.4)*
20. **Split `dashboard.css` into `marketing.css` +
    `app.css`** so the marketing surface only ships its
    ~20% of the styles. Larger refactor; only after
    §1.1's minification is in place. *(§1.1)*

### P3 — backlog

21. Add `<link rel="apple-touch-icon">` to `base.html`
    for iOS home-screen installs. *(§1.3)*
22. Submit `ai-billing-audit.ashbi.ca` to hstspreload.org
    so the `preload` directive is meaningful. *(§4.1)*
23. Add `@media (prefers-reduced-motion: reduce)` block
    to `dashboard.css` to satisfy WCAG 2.3.3. *(§3.9)*
24. Wire the `<input type="file">` in `contact.html` to
    a short `aria-label` + `aria-describedby` for the
    helper text. *(§3.5)*
25. Sanitise the `style="width: {{ '%.1f' % _pct }}%"`
    in `index.html:191` via a CSS custom property so
    untrusted data never lands in a `style` attribute.
    *(§4.5)*
26. Strip `X-Powered-By: uvicorn` (or `Server: uvicorn`)
    from the response via `header -Server` in Caddy or
    `server_header = ""` in uvicorn. *(§4.1)*
27. Drop `/audits` from `feeds.PUBLIC_MARKETING_PATHS`
    since `robots.py` disallows it. *(§5.3)*
28. Bump the focus-ring box-shadow in the
    `.paste-form input:focus` rule to a darker
    `--color-brand-soft` (or revert to `outline: 2px
    solid brand`) to pass WCAG 2.4.7 3:1 contrast
    cleanly. *(§3.6)*
29. Verify the topbar nav hit areas are ≥44px on mobile
    viewports; the existing 44px rule (`dashboard.css:1235`)
    is in the `@media (max-width: 768px)` block but
    doesn't explicitly target `.topbar nav a`. *(§3.10)*
30. If the deployment ever scales past one uvicorn
    worker, the in-process rate limiter
    (`api.py:1262-1310`) becomes
    `N_WORKERS * 10/min` per IP — move to Redis when
    that day comes (already documented in the
    inline comment at `api.py:1272-1273`). *(§4.7)*

---

## 7. What's already done well

- **No third-party trackers / fonts / analytics** on
  any marketing page. The home page is ~10 KB of
  HTML, ~100 KB of CSS, no JS, no images. That's
  exceptional for a 2026 SaaS marketing site.
- **HSTS 2-year + preload** is set (subject to the
  Traefik-public-edge verification in §4.2).
- **`X-Frame-Options: DENY` + CSP `frame-ancestors 'none'`**
  for clickjacking — belt and suspenders.
- **CORS regex is anchored on both ends** and the
  `ashbi.ca` wildcard covers the `zorva.ashbi.ca`
  portal without redeploying.
- **Every marketing template has exactly one `<h1>`**
  and a clean h2/h3 hierarchy. *(§2.8, §3.8)*
- **No inline event handlers anywhere** in any
  template — all event handling is `addEventListener`.
  *(§4.4)*
- **The inline `<script>` escapes every JSON-derived
  string** before `innerHTML` interpolation.
  *(§4.4)*
- **No cookies are set** on the marketing surface,
  so the PHIPA-cookie-consent requirement is
  moot. *(§4.3)*
- **System font stack only** — zero font-related
  network requests, zero FOIT. *(§1.4)*
- **Forms are properly labelled** (every input wrapped
  in a `<label>`), `required` is set, no `for=` /
  `id=` mismatches possible. *(§3.5)*
- **Native `<details>` for the FAQ** — keyboard-
  accessible, no JS, no ARIA required. *(§3.10)*
- **The `robots.txt` and `sitemap.xml` are complete
  and consistent** with the bearer-auth public-read
  whitelist. *(§2.6)*
- **Every marketing template has a unique `<title>`**,
  all of which include the brand name and a
  page-specific differentiator. *(§2.1)*
- **Internal link graph is solid** — every public
  page has ≥3 inbound links from the topbar/footer
  plus contextual links. *(§2.9)*
- **Touch targets are ≥44px on mobile** in
  dashboard chrome; the inline comments document the
  WCAG 2.5.5 reasoning. *(§3.10)*

---

## 8. Summary scorecard

| Area | Score | Top finding |
|---|---|---|
| Performance | B+ | 100 KB unminified CSS dominates page weight; minify + long-cache |
| SEO | C+ | Zero `description`, `og:*`, `twitter:*`, `canonical`, JSON-LD |
| Accessibility | B | No skip link, no global focus-visible, no ARIA landmarks |
| Security | A− (pending Traefik verify) | Headers set in Caddy but not verified on public edge |

The marketing surface is small, internally consistent, and
honest about its own trade-offs (`Caddyfile:14-18` and the
`'unsafe-inline'` rationale at `Caddyfile:20-32`). The
fixes are mostly *additive* — the P0s are quick to ship
and the P1s follow naturally.
