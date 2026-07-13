# Zorva marketing site — completeness audit

**Site:** https://ai-billing-audit.ashbi.ca
**Repo:** /Users/biancabienaime/projects/ai-billing-audit
**Scope:** public marketing surface (everything in `src/ai_billing_audit/templates/` + the public routes in `src/ai_billing_audit/api.py`)
**Audit date:** 2026-07-13 (matches the v0.5.0 release line in `/changelog`)

A real Alberta physician or PCN operations lead lands on this site from a search, a referral, or a cold email. Every gap in this report is a friction point between "I clicked the link" and "I trust this enough to send 100 real claims." Prioritized fix list at the bottom.

---

## Executive summary

- **No custom error pages.** The site has zero `@app.exception_handler` decorators and no catch-all route (`grep -E "exception_handler|path:path" api.py` returns nothing). A typo in any URL returns FastAPI's plain-text `"Not Found"` body and the default 500 page on unhandled errors — both brand-inconsistent and a Trust & Security deal-breaker for an HIA / PIPEDA audience.
- **Every blog-post link in the page body is a 404.** `templates/blog.html` (lines 18, 33, 48, 63) links to `/blog/why-we-built-zorva`, `/blog/18-ahcip-rules`, `/blog/why-flat-fee`, `/blog/why-alberta-first`. None of those routes exist (`grep "/blog/" api.py` returns only `/blog` itself at line 4431). `BLOG_POSTS` data is defined in `feeds.py:18` and feeds `/rss.xml`, but no detail route or `blog_post.html` template exists. The RSS feed sends subscribers to dead links.
- **No `/changelog/{version}` or `/glossary/{term}` detail pages either.** Changelog uses `#v0-5-0` anchor links (which work in-page but can't be shared as a URL); glossary uses `<details>` accordions (no deep links at all). Case-studies is the *only* list-with-detail pattern that's actually wired up (`api.py:4683` + `case_study_detail.html`).
- **Lead capture works for the contact form, but nothing else.** `/contact` (POST at `api.py:4570`) writes to the audit trail and stages an optional claims file to `/app/logs/contact_uploads/` (`contact.py:_stage_contact_upload`). No actual email is sent — sales has to read the log. `/demo-request` (GET only at `api.py:4412`) and `/pilot` (GET only at `api.py:4421`) both render pages whose forms post to `/contact`. No newsletter signup, no Calendly/Cal.com, no lead-magnet PDF, no exit-intent, no "Book a call" button in the topbar.
- **Almost no social proof visible on the surface.** Two anonymous pull-quotes live on `/press` (lines 86-94) attributed to "Billing lead, Alberta family-medicine clinic" and "PCN operations director, central Alberta." No customer logos anywhere in `static/`. No trust badges (SOC 2 / ISO 27001 / PHIPA / HIA). The `/press` page explicitly states "We do not currently have any third-party coverage" (line 109) and the fact sheet lists "2 Alberta clinics in 60-day pilot" (line 67). A prospect who lands on `/` and tries to find "who else uses this" will reach the press page and find nothing.
- **Zero marketing-asset files beyond `favicon.svg`.** `static/` contains exactly three files: `dashboard.css`, `favicon.svg`, `upload.js`. Missing: `og-image.png`, `favicon.ico`, `apple-touch-icon`, `manifest.json`, any logo PNG/SVG, any trust-badge image, any case-study hero image, any social-card. There are no `<meta property="og:*">` or `<meta name="twitter:*">` tags in any template — a link to the site on Slack / LinkedIn / iMessage renders as a blank card.
- **Zero analytics and zero UTM tracking.** No Plausible / Fathom / GA / Matomo / PostHog script in any template or in `static/`. No `utm_*` query parameters anywhere. The only tracking tag in the codebase is one `?source=case_study` on the case-study detail page (`case_study_detail.html:86`). The site can't answer "which page drove the contact form submission" or "where did this prospect come from."
- **Topbar has no CTA.** `base.html:11-29` is a brand-mark + 9 text links + a tenant-pill. No "Get started" / "Book a demo" / "Try free" button. Every conversion depends on the visitor scrolling to a per-page CTA section.
- **`/for/family-medicine` is well-customized** — it names the 7 highest-yield rules for family-medicine specifically, has a worked example, and a per-finding dollar breakdown. This is the strongest single page on the site from a vertical-SEO perspective.

---

## 1. Error pages

**Status: ❌ MISSING ENTIRELY**

Searched `api.py` for `exception_handler`, `maintenance`, `catch_all`, `path:path` — zero matches. The only references to 404 in the entire codebase are the 20+ `raise HTTPException(status_code=404, ...)` calls inside API endpoints (e.g. `api.py:1869`, `1877`, `1976`, `2058`, `2063`, `2096`, `3051`, `3141`, `3197`, `3465`, `3504`, `3528`). All of these are returned as JSON `{"detail": "..."}` to API consumers — no human-facing 404 page is ever rendered.

- **No 404 handler** — any URL not matched by a route returns FastAPI's default `"Not Found"` plain-text body. `GET /pricing/` (trailing slash), `GET /blog/why-we-built-zorva` (see §2), `GET /anything-typoed` all hit the default.
- **No 500 handler** — unhandled exceptions return FastAPI's default JSON 500 body, with a stack trace in dev mode (a privacy problem in itself for an HIA posture page that promises "no leaks").
- **No 503 / maintenance-mode route** — no `@app.get("/maintenance")`, no flag-gated fallback. If the auditor is down, the marketing site has no graceful "we're back in 30 minutes" page.
- **No branded error templates** — `templates/` does not contain `404.html`, `500.html`, `503.html`, or `error.html`. The `base.html` extends pattern is wired up (every public page uses it), so a `404.html` template would just need an `@app.exception_handler(404)` decorator to start working.

**Impact for a prospect:** high. A physician clicking an outdated link from a 2025 referral email lands on a generic error. A PCN operations director copying a case-study URL to forward internally lands on a generic error. Both are trust events.

---

## 2. Per-page deep links

**Status: 1 of 4 list pages has a working detail route.**

| List page | List data | Detail route | Detail template | Per-item deep links work? |
|---|---|---|---|---|
| `/blog` | ✓ `feeds.py:18` (`BLOG_POSTS`, 4 posts) | ❌ NONE | ❌ NONE (`blog_post.html` doesn't exist) | **No — all 4 post links 404** |
| `/case-studies` | ✓ `case_studies.py:63+` (`CASE_STUDIES`, 3 entries) | ✓ `api.py:4683` (`/case-studies/{slug}`) | ✓ `case_study_detail.html` | **Yes** |
| `/changelog` | ✓ `feeds.py:66` (`CHANGELOG_RELEASES`, 5 releases) | ❌ NONE | ❌ NONE | Anchor links only (`#v0-5-0`), no sharable URLs |
| `/glossary` | ✓ `templates/glossary.html` (20 `<details>` blocks, hard-coded) | ❌ NONE | ❌ NONE | No links at all — `<details>` accordions |
| `/for/family-medicine` | ✓ single page, well-customized | n/a | n/a | n/a |

### Detail-route gaps to fix

1. **`/blog/{slug}` — 4 broken links, highest-priority fix.**
   - `templates/blog.html:18` → `<a href="/blog/why-we-built-zorva">`
   - `templates/blog.html:33` → `<a href="/blog/18-ahcip-rules">`
   - `templates/blog.html:48` → `<a href="/blog/why-flat-fee">`
   - `templates/blog.html:63` → `<a href="/blog/why-alberta-first">`
   - All four slugs match `BLOG_POSTS[*].id` in `feeds.py`. The data is already in-memory; the missing pieces are a route handler in `api.py` and a `blog_post.html` template. The RSS feed (`feeds.py:build_atom_feed`) and the sitemap (`feeds.py:build_sitemap`) already point at `/blog/{slug}` — both currently send subscribers/crawlers to a 404.
2. **`/changelog/{version}` — 5 anchors that can't be shared.**
   - `feeds.py:79-86` (and similar) set `url_path` to `/changelog#v0-5-0`. To support per-release permalinks: add `CHANGELOG_DETAIL = {entry["id"]: entry for entry in CHANGELOG_RELEASES}` in `feeds.py`, register `@app.get("/changelog/{version}", ...)` in `api.py` (mirror the `case_study_detail` handler at line 4683), and add `changelog_release.html` extending `base.html`.
3. **`/glossary/{term}` — 20 terms with no URLs at all.**
   - `templates/glossary.html` is a flat list of `<details>` elements. To support per-term pages: extract each term into a `GLOSSARY = [{"term": "AHCIP", "slug": "ahcip", "definition": "..."}, ...]` list (mirror the `CASE_STUDIES` pattern in `case_studies.py`), register `/glossary/{term}` in `api.py`, and add `glossary_term.html` for the detail view. SEO upside: 20 long-tail landing pages for "what is CMGP," "what is HIA IMA," etc.
4. **Case studies is the model to copy.** `api.py:4683` and `case_study_detail.html` are clean. Reuse the same pattern for blog + changelog + glossary.

---

## 3. Lead capture

**Status: 1 of 5 expected channels works; 0 of 4 alternative channels exist.**

### 3.1 /contact form — ✓ works (file-stage, no email)

- **Route:** `api.py:4570` (`@app.get("/contact")` + `@app.post("/contact")`)
- **Form fields:** name, clinic, email, monthly_claims, message, optional `claims` file (837P/CSV/FHIR/ZIP/JSON/XML). `templates/contact.html` lines 41-66 + `demo-request.html:84-128`.
- **What it actually does:** `contact.py:_append_contact_event()` writes a `contact_request` row to the **audit trail** (`audit_actions.append`), with the email SHA-256-hashed. If a file is attached, `contact.py:_stage_contact_upload()` writes it to `/app/logs/contact_uploads/{sha12}-{uuid}-{filename}` with a manifest. **No email is sent to anyone.** Sales has to read the audit log to see new submissions.
- **The swarm-audit comment in `api.py:4581-4587` is candid:** "the form accepts an optional `claims` file... The file is staged to `/app/logs/contact_uploads/`... the actual audit runs once an operator pulls it through the shadow-audit pipeline. (Live auto-run from /contact is a follow-up card — the file stage + operator handoff matches the rest of the privacy posture.)"
- **Gap:** no Slack notification, no email-to-sales alert, no Postgres write for the sales team. The privacy-officer-friendly audit-trail write is fine, but a single missed audit-log tail = a missed prospect.

### 3.2 /demo-request form — works, but only by piggy-backing on /contact

- **Route:** `api.py:4412` is **GET only** — no POST handler. The form in `templates/demo-request.html:84` posts to `action="/contact"`, so the submission does land in the audit trail (under the `contact_request` action). It works, but the URL the user sees in the address bar is `/contact` (no demo-specific routing) and there's no way to tell from the audit log whether the request came from `/demo-request`, `/contact`, `/pilot`, or the case-study CTA.
- **Gap:** no `@app.post("/demo-request")` route, no demo-specific audit-trail `action="demo_request"`. A real lead-source breakdown isn't possible.

### 3.3 /pilot form — works the same way

- `api.py:4421` is GET only. The "Request a pilot" button in the page header (`templates/pilot.html:18`) and the closing CTA (`pilot.html:171`) both link to `/contact`. Same audit-trail entry, same lack of source attribution.

### 3.4 Newsletter signup — ❌ does not exist

- `grep -E "subscribe|newsletter|email.list|email.signup" templates/*.html` returns zero matches. The blog CTA in `templates/blog.html:80-86` only offers "RSS · Atom" or "/contact" — no email-list opt-in.
- The `feeds.py:148-150` `PUBLIC_MARKETING_PATHS` doesn't include a newsletter route because there isn't one. /rss.xml is the only "subscribe" mechanism.

### 3.5 "Book a call" / Calendly / Cal.com — ❌ does not exist

- `grep -E "calendly|cal\.com|hubspot|salesforce|book.*call" templates/*.html` returns zero matches. Every sales call is funneled through the contact form, which routes to a contact form not a calendar. For an Alberta physician's office, this is a friction point — they want to book the 30 minutes directly, not fill out a form and wait for an email.

### 3.6 Exit-intent / lead magnet — ❌ does not exist

- No `exit-intent.js`, no "Get the free AHCIP audit checklist PDF" CTA, no pop-up. `static/` has only `dashboard.css`, `favicon.svg`, `upload.js`. The only free-resource offers are the case studies themselves.

### 3.7 Topbar / global "Get started" CTA — ❌ does not exist

- `templates/base.html:11-29` is a brand mark + 9 text nav links + a tenant-pill. No "Get started" / "Book demo" / "Try free" button. Every conversion requires the visitor to scroll into a per-page CTA section. Compare to typical SaaS topbars (which have a primary CTA on the right edge).

### 3.8 Footer CTA strip — partial

- `base.html:31-44` is a text-only footer with no CTA. **However**, 15 of the 24 templates include their own `<aside class="*-cta">` section just above the footer (e.g. `home.html` has 6 CTA elements, `pricing.html` has `.pricing-cta`, `security.html` has `.security-cta`, `pilot.html` has `.pilot-cta`, etc.). So a per-page CTA does exist on most pages, but there's no global always-visible CTA strip for the 8-9 pages that lack one.
- Pages with no `<aside class="cta-...">` block: `about.html`, `case_studies.html`, `case_study_detail.html` (has its own cta block — counted), `try.html`, `what-zorva-finds.html`, `compare.html`, `careers.html` (has one), `legal_privacy.html`, `legal_terms.html`, `index.html` (the legacy /audits dashboard). Of these, the legal pages and the legacy dashboard are fine without — but `about.html`, `try.html`, `what-zorva-finds.html`, `compare.html` should have one.

---

## 4. Social proof

**Status: 0 customer logos. 0 named testimonials. 0 trust badges. 0 press mentions. Customer count (2 clinics) only on /press.**

### 4.1 Customer logos — ❌ does not exist

- `static/` has no `logos/` directory. `grep -E "<img" templates/*.html` returns zero matches. The `/for/family-medicine` page names "5–20-physician family-medicine practice" and "3,000–5,000 AHCIP claims per month" but doesn't name a single real clinic. A prospect scrolling the home page cannot find "who else uses this."

### 4.2 Testimonials — 2 anonymous quotes, /press only

- `templates/press.html:86-94` contains two blockquotes attributed to "Billing lead, Alberta family-medicine clinic (2026-Q2 pilot)" and "PCN operations director, central Alberta (2026-Q2 pilot)." Both are anonymized to the level of "no usable social proof" — no clinic name, no logo, no headshot, no LinkedIn link. They are not surfaced on `/`, `/pricing`, `/for/family-medicine`, or anywhere else a prospect actually scrolls.
- **Gap:** no real testimonial anywhere in the buyer-journey pages. A PCN ops director comparing Zorva to Dr. Bill will not see a single named customer reference.

### 4.3 Case study metrics — ✓ present, well-quantified

- `case_studies.py:63-105` (and similar) have per-finding dollar impact for all 3 case studies. The "what-zorva-finds" page (`templates/what-zorva-finds.html`) and `/for/family-medicine` each list per-finding dollar amounts (~$45 / $50 / $85). Home page (`home.html:108-127`) shows a "What we caught in the latest pilot" block with 3 specific findings and dollar amounts. This is the strongest social proof on the site — keep it.

### 4.4 Trust badges — ❌ does not exist

- `grep -E "soc.?2|iso.?27001|phipa|hipaa" templates/*.html` shows the frameworks are **named in text** on `/security` (lines 138-152) — HIA active, PIPEDA active, SOC 2 "on certification roadmap (not currently held)", ISO 27001 "on certification roadmap (not currently held)." But there are **no badge images** anywhere — no "SOC 2" / "ISO 27001" / "HIA aligned" / "PIPEDA compliant" PNG/SVG badges in `static/`, and no `<img>` tags referencing any third-party badge CDN.
- **Gap:** the HIA + PIPEDA + PHIPA + HIPAA posture is real (see `security.html:138-152` and `trust.html` subprocessors), but it reads as a table, not as a row of trusted-by badges. A privacy officer scanning the home page sees none of it.

### 4.5 Awards / press mentions — ❌ does not exist

- `templates/press.html:108-110` explicitly says: "We do not currently have any third-party coverage. This page exists so that when a journalist reaches out, we have a kit ready to send." No "As seen in" row, no press logos, no "Featured by" widget.

### 4.6 Customer count / province coverage — ❌ does not exist

- `press.html:67` lists "2 Alberta clinics in 60-day pilot (as of 2026-07-13)" in the fact sheet. That's the only place a real number appears. No "Used by X clinics across Y provinces" stat on the home page or pricing page. The about page says "currently in pilot with two Alberta clinics" — buried in a paragraph.

---

## 5. Marketing assets

**Status: 1 of 5 expected assets present. 0 OG / Twitter / PWA metadata.**

`ls static/`:
- `dashboard.css` (99 KB) — single stylesheet for the dashboard
- `favicon.svg` (293 bytes) — referenced by `base.html:8`
- `upload.js` (17 KB) — client-side upload portal logic

That's it. No images, no social cards, no icons, no manifest.

| Asset | Expected location | Status |
|---|---|---|
| `og-image.png` (1200×630) | `static/og-image.png` | ❌ Missing — no OG / Twitter meta tags anywhere either |
| `favicon.ico` | `static/favicon.ico` | ❌ Missing (only `favicon.svg` referenced) |
| `apple-touch-icon.png` (180×180) | `static/apple-touch-icon.png` | ❌ Missing |
| `manifest.json` (PWA) | `static/manifest.json` | ❌ Missing |
| `robots.txt` | served at `/robots.txt` | ✓ Present (`api.py:4555`, source in `robots.py`) |
| `sitemap.xml` | served at `/sitemap.xml` | ✓ Present (`api.py:4536`, source in `feeds.py`) |
| `rss.xml` | served at `/rss.xml` | ✓ Present (`api.py:4515`, source in `feeds.py`) |

### OG / Twitter / Apple meta tags — ❌ missing

- `grep -rE "og:|twitter:|apple-touch|manifest\.json|favicon\.ico" templates/ api.py` returns zero matches. `base.html:1-10` is a minimal `<head>`: charset, viewport, title, stylesheet, favicon.svg. That's it.
- **Impact:** every link to the site on Slack / LinkedIn / iMessage / Twitter renders as a blank card with no preview image, no description, no title. For an Alberta-clinic audience that's sharing links internally, this is a missed "professional brand" signal.

### robots.txt — ✓ good

- `robots.py:14-23`: allows everything, disallows `/api/`, `/audits`, `/encounters/`, `/encounter/`, `/admin`. Sitemap reference correct. No major gaps.

---

## 6. Conversion infrastructure

**Status: 0 analytics. 0 UTM tracking. 0 topbar CTA. Per-page CTA present on most pages.**

### 6.1 Analytics — ❌ does not exist

- `grep -E "plausible|fathom|googletagmanager|google-analytics|matomo|posthog|amplitude|mixpanel|segment|hotjar|gtag" templates/*.html static/*.js api.py` returns zero matches for any analytics script.
- The `src/ai_billing_audit/analytics.py` module is **not** web analytics — it's a Python-side "top missed-revenue patterns" data analyzer (line 3: "Aggregates audit data (list of records or a path to a JSONL)"). No request logging, no visitor counts, no funnel data.
- The site has no way to answer: "How many people visited /pricing this week?" "Where did the last contact form submission come from?" "Which blog post drove the demo-request?"
- **For an HIA posture this is defensible** (no third-party tracking, no cookies, no fingerprinting) — but it should be a conscious choice, and the obvious privacy-respecting option (Plausible self-hosted, Fathom, or a server-side nginx log analyzer) is currently absent.

### 6.2 UTM tracking — ❌ does not exist

- `grep -E "utm_source|utm_medium|utm_campaign" -r` returns zero matches. The only tracking tag in the entire codebase is `?source=case_study` at `templates/case_study_detail.html:86` and the "Send 100 claims" CTA at `home.html:46` (no source tag).
- Even the most basic "where did this prospect come from" is not instrumented.

### 6.3 Topbar CTA — ❌ does not exist

- `templates/base.html:11-29` is brand + 9 text links + tenant-pill. No "Get started" / "Book a demo" / "Try free" button. Every conversion requires the visitor to scroll into a per-page CTA section. The `/audits` link is the closest thing to a topbar action — but that's the dashboard for existing users, not a marketing CTA.

### 6.4 Footer CTA strip — partial (see §3.8)

- 15 of 24 templates have their own per-page CTA section above the footer. 4 buyer-journey pages (about, try, what-zorva-finds, compare) lack one. The `base.html` `<footer>` block (`base.html:31-44`) is text-only with no CTA.

---

## 7. Content depth

**Status: 4 of 4 list pages have real content. Family-medicine vertical page is well-customized. No demo video anywhere.**

### 7.1 /blog — ✓ 4 posts, real (June–July 2026)

- `feeds.py:18-58` lists 4 posts: "Why we built Zorva (and not a billing service)" (2026-07-13), "The 18 AHCIP rules in v12" (2026-07-08), "Why we charge flat-fee, not per-claim" (2026-07-01), "Why Alberta first" (2026-06-22). All have real titles, real summaries, real publish dates. The matching `<article>` blocks in `templates/blog.html:14-72` are hand-written and specific. RSS feed at `/rss.xml` works.
- **Gap:** the 4 posts are all "build notes" and "go-to-market" — none is a "how to" / educational / SEO-targeting piece. No post targeting "how to fix modifier-25" / "how to recover from an AHCIP 80G denial" / "how to choose an AHCIP billing software" — the long-tail queries an Alberta biller actually searches. **All 4 post URLs are 404 (see §2).**

### 7.2 /case-studies — ✓ 3 case studies, real

- `case_studies.py:63+` defines 3 case studies, one per difficulty band (easy / medium / hard), each tied to a real `encounter_id` from `data/val.json`. Each has clinical scenario, claim summary, findings list, "what the biller would have done without Zorva," and dollar impact. Templates + detail route are wired up (the one list-with-detail pattern that works). This is the strongest content on the site.

### 7.3 /changelog — ✓ 5 releases, real

- `feeds.py:66-117` lists 5 releases from v0.1.0 (2026-02-15) through v0.5.0 (2026-07-04). All match the hand-written `<article>` blocks in `templates/changelog.html:21-115`. Specific feature lists, specific dates. RSS feed includes them.
- **Gap:** per-release permalinks (see §2).

### 7.4 /glossary — ✓ 20 terms, real

- `templates/glossary.html:21-208` defines 20 `<details>` accordions covering AHCIP, AWV, CMGP, CPT, E/M, FHIR, GR, HIA, HIPAA, H-Link, HMV, IMA, LLM, MUE, NCCI, PCN, PHIPA, PIPEDA, SOMB, SFTP, 837P (that's 21, actually). All specific to Alberta / AHCIP / HIA. This is genuinely useful for a non-Alberta biller doing a literature review.
- **Gap:** no per-term URLs, no anchor IDs — every term is just a `<details>` in one giant page. (See §2.)

### 7.5 /for/family-medicine — ✓ well-customized

- `templates/for/family-medicine.html` is the strongest single page on the site. It names the 7 highest-yield rules for family-medicine practices specifically (modifier-25, CMGP, referring NPI, lab coverage, after-hours premium, preventive opportunity, duplicate service), has a worked example with 3 findings + dollar amounts, and a "what this is worth on the biller's desk" section with 800–1,500 findings/month estimates and $30K–$80K recoverable. This is the kind of page that converts an Alberta family-medicine biller who's been Googling "how much revenue is my clinic losing to AHCIP denials."

### 7.6 Demo video — ❌ does not exist

- `grep -E "asciinema|loom|youtube|vimeo|mp4|webm" templates/*.html` returns zero matches. No demo video, no Loom embed, no YouTube walkthrough. The `/try` page is text-only with the 3 findings inline.
- **Gap:** for a 30-minute walkthrough request, a 90-second Loom of "here's what Zorva looks like on a real AHCIP sample claim" would convert significantly better than the current text page.

---

## Prioritized fix list

### P0 — fixes that change whether the site works

- **P0.1 — Build a branded 404 page.** Add `@app.exception_handler(404)` to `api.py` + `templates/404.html` extending `base.html`. Same FastAPI default for 500 with `@app.exception_handler(Exception)`. Without this, every typo and every broken link is a brand-inconsistent blank page. *One afternoon of work, zero data dependencies.*
- **P0.2 — Wire up `/blog/{slug}` detail routes.** 4 broken inbound links in the live RSS feed and on `/blog` itself. Add the route to `api.py` (copy the `case_study_detail` pattern at line 4683), add `blog_post.html` extending `base.html`, render the matching `BLOG_POSTS` entry from `feeds.py`. *Half a day — the data is already in-memory.*
- **P0.3 — Add an og-image + OpenGraph / Twitter Card meta tags.** Drop a `static/og-image.png` (1200×630, Zorva brand) and add `<meta property="og:image">`, `<meta property="og:title">`, `<meta property="og:description">`, `<meta name="twitter:card" content="summary_large_image">` to `base.html`. Currently every Slack / LinkedIn / iMessage share of the site is a blank card. *One hour of design + 15 minutes of template edits.*
- **P0.4 — Wire a notification for the contact form.** Add an email-to-sales (or Slack webhook) on `_append_contact_event` in `contact.py`. Currently the only way a sales rep learns about a new submission is to read the audit-trail log. Missed logs = missed prospects. *Half a day; could be a Slack webhook that just dumps the row.*
- **P0.5 — Add a topbar CTA.** One button on the right edge of `base.html` ("Book a 30-min walkthrough" → `/demo-request`, or "Try the sample" → `/try`). Every other SaaS marketing site has one. *Five minutes of HTML, two minutes of CSS.*

### P1 — gaps that hurt conversion but the site still works

- **P1.1 — Build `/changelog/{version}` and `/glossary/{term}` detail pages.** Same pattern as P0.2 — 5 changelog releases and 20 glossary terms become sharable URLs + SEO landing pages. *One day total.*
- **P1.2 — Surface 2 real testimonials on the buyer-journey pages.** The anonymous quotes on `/press` are not visible on `/`, `/pricing`, `/for/family-medicine`. Convert them to a 2-3 quote carousel on the home page with the clinic size + the dollar figure the auditor found. *Half a day; you have the source material.*
- **P1.3 — Add a "Book a call" Calendly or Cal.com link in `/demo-request` and the topbar.** Alberta clinic managers want to schedule the 30 minutes directly, not fill out a contact form and wait. *15 minutes if the Calendly URL exists, half a day if you need to set it up.*
- **P1.4 — Add `apple-touch-icon.png` and `manifest.json`.** A PWA-grade topbar feel (custom iOS home-screen icon, "Add to Home Screen" support). *One hour.*
- **P1.5 — Add a privacy-respecting analytics script.** Plausible self-hosted (no cookies, no fingerprinting, HIA-friendly) or a server-side nginx log analyzer. Currently no way to answer "how many prospects saw /pricing this month." *Half a day for Plausible + a self-hostable docker image.*
- **P1.6 — Add UTM-tagged CTAs across all outbound buttons.** Topbar CTA, every "Send 100 claims" button, every "Book a walkthrough" button. Currently only 1 of ~30 CTAs has a source tag. *One hour.*

### P2 — nice-to-haves that round out the picture

- **P2.1 — Trust badges on `/security` and the home page.** Even text-only badges (HIA aligned / PIPEDA compliant / SOC 2 roadmap / ISO 27001 roadmap) in an `<img>` row would make the security posture more visible. *One hour for SVG versions, half a day if commissioned from a designer.*
- **P2.2 — A 90-second demo video on `/try` and `/home`.** A Loom of "here's what Zorva looks like on a real AHCIP encounter" embedded above the text findings. *Half a day to record + edit + embed.*
- **P2.3 — Newsletter signup form in the blog CTA + footer.** A simple email field + "Subscribe" button → mailto: or a Substack / Buttondown / Listmonk endpoint. Currently the only "subscribe" is RSS. *One day including provider setup.*
- **P2.4 — Per-page CTA blocks on the 4 pages that lack one.** `about.html`, `try.html`, `what-zorva-finds.html`, `compare.html` should each have a closing CTA pointing to `/contact` or `/demo-request`. *One hour.*
- **P2.5 — "Used by N clinics in M provinces" stat on the home page** (and `/press` should drive this). When the number is 2, the stat is "In pilot with 2 Alberta clinics" — not the strongest social proof, but it's the honest number and it shows the company has any customers at all. *One hour.*
- **P2.6 — A "free AHCIP audit checklist PDF" lead magnet.** Capture email on the home page, deliver a 1-pager "18 AHCIP rules every Alberta biller should know." Captures emails from prospects not ready to send 100 claims. *One day including PDF design.*
- **P2.7 — Customer logos once the second or third pilot signs.** Not actionable today (only 2 customers), but plan the layout: a row of 4-5 logos on `/`, `/for/family-medicine`, and `/pricing`. *When the time comes.*

---

## Summary by category

| Category | Status | Headline gap |
|---|---|---|
| 1. Error pages | ❌ Missing | No 404/500/503 handler; FastAPI default plain text |
| 2. Per-page deep links | ⚠️ 1/4 working | Blog 100% broken; changelog + glossary no per-item URLs |
| 3. Lead capture | ⚠️ Partial | /contact works (file stage, no email); no newsletter, no Calendly, no topbar CTA |
| 4. Social proof | ❌ Missing | 0 logos, 0 named testimonials, 0 trust badges, 0 press mentions; 2 anonymous quotes on /press only |
| 5. Marketing assets | ❌ Missing | 0 OG/Twitter/Apple/PWA assets; only `favicon.svg` |
| 6. Conversion infrastructure | ❌ Missing | 0 analytics, 0 UTM tracking, 0 topbar CTA; partial footer CTA |
| 7. Content depth | ✓ Strong | Real blog/case-studies/changelog/glossary; family-medicine page is excellent; no demo video |
