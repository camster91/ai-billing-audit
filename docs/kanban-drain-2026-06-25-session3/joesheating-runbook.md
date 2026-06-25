# joesheating — 11 ready + 11 blocked remediation runbook

**Source:** `~/projects/joesheating/REMEDIATION_AUDIT.md` (decomposed 2026-06-25).
**Domain:** joesheating.ca (WP Engine → in transition; this batch is live WP edits).
**Stack:** WordPress + Elementor Pro + Redirection plugin + Filter Everything + GA4.

All 22 joesheating tasks reduce to **4 categories** of WP edits. Total
estimated wall-time once Cam has admin open: **~2 hours**.

Each section: **task ids → exact clicks → acceptance → comment template.**

---

## Category 1 — Nav / menu reorder (3 ready, 5 min)

### Reorder global nav (Careers/Reviews/Contact under About Us)

- **Task:** `t_27ee322e` (ready stub) — `t_6e20177b` (blocked implementation)
- **Source:** Markup.io Pins 248, 249 (Ken)
- **Path:** WP Admin → Appearance → Menus → [main nav] → drag:
  ```
  About Us
    ├── Our Story
    ├── Careers        (move here from top-level)
    ├── Reviews        (move here from top-level)
    └── Contact        (move here from top-level)
  Services
  ...
  ```
- **Acceptance:** Top-level nav shows About Us → Services → ... →
  Resources → Blog. No standalone "Careers / Reviews / Contact".
- **Verify:** `curl -s https://joesheating.ca | grep -E 'menu-item-[0-9]+' | head -30`
  shows the new order.
- **Cache:** Purge WP Fastest Cache + Cloudflare after.
- **Comment template:**
  ```
  Done 2026-06-25 via Appearance > Menus > drag-reorder.
  Curl-verified new order. Cache purged.
  ```

### Fix Furnace link target (Daniella Jun 2)

- **Task:** `t_489d148d` — link goes to `/services/heating/` not `/services/heating/furnaces/`
- **Fix:** Appearance → Menus → edit "Furnace" menu item URL → set to `https://joesheating.ca/services/heating/furnaces/`
- **Acceptance:** `curl -I https://joesheating.ca/services/heating/furnaces/` returns 200.

### Add /furnace/ → /furnaces/ 301 redirect (Daniella May 26)

- **Task:** `t_984e5679`
- **Fix:** Tools → Redirection → Add new:
  - Source URL: `/furnace`
  - Target URL: `/furnaces/`
  - Type: 301
- **Acceptance:** `curl -I https://joesheating.ca/furnace` → 301 → Location: `/furnaces/`.

---

## Category 2 — Page copy fixes (4 blocked, 20 min)

### AC maintenance page location list (Daniella Jun 2)

- **Task:** `t_011fac36`
- **Fix:** Elementor → template-single-service (AC maintenance entry) →
  copy the location list widget from the furnace-maintenance version.
- **Verify:** Page renders same 9 named cities (no "Durham").

### UVP bar text rewrite (Daniella May 26)

- **Task:** `t_d1837427`
- **Fix:** Elementor → Templates → Theme Builder → Header → UVP bar widget → set text to: `50+ years in business · From heating to cooling, we're your local comfort experts.`
- **Verify:** `curl -s https://joesheating.ca | grep -i '50+ years'` returns the new text.

### Remove 'Durham' from city list (Daniella May 26)

- **Task:** `t_28ccdead`
- **Fix:** Elementor → global widget (city list) → find/replace "Durham Region" → blank for the 9 named cities.
- **Verify:** Page source no longer contains "Durham".

### /resource-centre tags not filtering (Daniella Jun 2)

- **Task:** `t_1a178670`
- **Fix:** Elementor post-widget on /resource-centre → use Filter Everything plugin shortcode `[fe-filter posts_per_page="12" post_type="post"]`. Confirm tags are populated on the 3 missing posts (Posts → Tags → ensure "Heating Tips", "Maintenance", "Energy Savings" applied).
- **Verify:** Click any tag on /resource-centre → loads filtered list.

---

## Category 3 — Image / asset fixes (4 ready + 3 blocked, 30 min)

### 5/6 blog posts missing featured images

- **Task:** `t_ad7dc471` (ready) — `t_0dbf21fa` (blocked)
- **Fix:** Media → Add New → upload 5 JPGs from old site backup
  (`/Users/biancabienaime/projects/joesheating/backups/`). Then for each:
  - Posts → All Posts → [post] → Set Featured Image → pick from Media Library
  - Posts list: filter by missing-featured, fix in bulk via Quick Edit
- **Verify:** Posts page grid shows all 6 with images.

### Storage water-heater page plan photos

- **Task:** `t_709255de` (ready) — `t_0b185484` (blocked)
- **Source:** Pin 155 (Laura)
- **Fix:** Elementor → /services/water-heaters/storage-water-heaters/ → plan widget → upload 4 plan photos (1500×1000 recommended) into Media Library, attach to widget.
- **Verify:** Page renders 4 plan photos in the gallery.

### /locations — add Google Maps photos

- **Task:** `t_db5257ef` (ready) — `t_1e55f132` (blocked)
- **Source:** Pin 203 (Laura)
- **Fix:** Elementor → /locations → add Google Maps widget → API key from
  ashbi-vault (or new key from Google Cloud Console, restrict to
  joesheating.ca domain) → enable "Places photos" toggle → add 3
  location markers.
- **Verify:** Page renders interactive map with photo markers.

### Burnham / Vanee / Heat n Glo brand logos

- **Task:** `t_da8d9519` (ready) — `t_b7546773` (blocked)
- **Source:** Pin 44 (Todd)
- **Fix:** Download SVG logos from each manufacturer's media kit:
  - Burnham: https://www.burnham.com/media (login required — request from Todd)
  - Vanee: https://www.vanee.com/resources (public)
  - Heat n Glo: https://www.heatnglo.com/media-kit (public)
- Upload to Media Library → Elementor brand list widget on /services/heating/furnaces/ → add 3 missing entries.
- **Verify:** Brand list shows 4 brands (Burnham, Vanee, Heat n Glo, + existing 1).

---

## Category 4 — External-service integration (5 ready + 5 blocked, 45 min)

### Create /projects/ archive page

- **Task:** `t_3f65a6c7` (ready) — `t_795c3f3f` (blocked)
- **Fix:**
  1. Pages → Add New → "Projects Archive" → Elementor canvas
  2. Add Posts widget → source = `project` CPT, layout = grid, posts per page = 12
  3. Publish
  4. Appearance → Menus → add "Projects" → link to /projects/
- **Verify:** `curl -s https://joesheating.ca/projects/ | grep '<article'` shows 13 entries.

### Setup JH Reporting → GA4 dashboard

- **Task:** `t_20c8aca5` (ready) — `t_63d8b5b9` (blocked)
- **Source:** Asana 19e893c83a4953bc (overdue Jun 1)
- **Fix:**
  1. https://analytics.google.com → JH Reporting property
  2. Admin → Property access management → add Ken, Daniella, Todd as Editors
  3. Admin → Data streams → confirm Web stream joesheating.ca active
  4. Custom reports → create 3 starter reports (sessions by source, conversions by service page, form submissions by location)
  5. Share dashboard URL with team via Slack #jh-reporting
- **Verify:** 3 reports visible to Ken's GA account.

### Debug 3 unnamed JS exceptions on /contact-us/

- **Task:** `t_1ea7f768` (ready) — `t_726aaed9` (blocked)
- **Fix:** Chrome DevTools → Sources → Event Listener Breakpoints → exceptions → reload /contact-us/. The 3 callsites need their throw sites rewritten to log the actual error. Likely candidates:
  - Form validation (jQuery validate library's silent fail)
  - reCAPTCHA callback (when grecaptcha fails to load on slow networks)
  - Elementor popup on scroll (when IntersectionObserver fires before DOM ready)
- **Verify:** Console clean on /contact-us/ reload × 3.

### Fix /offers page (savings %, chart, info)

- **Task:** `t_ae5e1dc2` (ready) — `t_6f2652b6` (blocked)
- **Source:** Pins 101, 104, 105, 106, 107
- **Fix:** Elementor → /offers → correct savings % to current promo (15% off install, was 25% — verify with Daniella), replace chart widget config with accurate data (Q2 numbers from sales team), add the missing info accordion section (financing terms).
- **Verify:** Page matches the Markup.io spec.

### Update /services/heating/furnaces — brand list

- **Task:** `t_a92b4a73` (ready) — `t_101c8888` (blocked)
- **Source:** Pins 51, 61, 153
- **Fix:** Elementor template-single-service → brand list → add Lennox, Carrier (existing was incomplete). Order: Goodman, Lennox, Carrier, + brand-list from Cat 3 logos.
- **Verify:** Page renders 4 brand logos with correct labels.

### Resolve 'Durham Region' keyword across 5 heating pages

- **Task:** `t_639aabe9` (ready) — `t_5e3fdd12` (blocked)
- **Source:** Pins 51, 54, 55, 61, 62, 63 (Todd)
- **Fix:** Elementor → bulk find/replace across these pages:
  - /services/heating/furnaces/
  - /services/heating/heat-pumps/
  - /services/heating/fireplaces/
  - /services/heating/water-heaters/
  - /locations/
  - Replace "Durham Region" with the explicit 9-city list (Ajax, Pickering, Whitby, Oshawa, Clarington, Scugog, Uxbridge, Brock, Scarbrough) — or strip entirely per Daniella's preference.
- **Verify:** `curl -s https://joesheating.ca/services/heating/ | grep -i durham` returns nothing.

---

## Closing checklist

After all 22 tasks done:
- [ ] WP Fastest Cache → Purge All
- [ ] Cloudflare cache purge (if proxied)
- [ ] Lighthouse re-run on /, /services/heating/furnaces/, /contact-us/
- [ ] 5 random Markup.io pins from each Pin source set → confirmed done
- [ ] Slack #joesheating → "Remediation sprint done, 22/22, [date]"

## Dependencies (verify before starting)

- [ ] WP admin login works (Daniella can reset)
- [ ] Elementor Pro license active
- [ ] Redirection plugin installed (for /furnace/ → /furnaces/)
- [ ] Filter Everything plugin installed (for /resource-centre)
- [ ] GA4 admin access (Ken)
- [ ] Old site backup accessible at `/Users/biancabienaime/projects/joesheating/backups/`
- [ ] Brand logo source URLs (Todd to confirm)