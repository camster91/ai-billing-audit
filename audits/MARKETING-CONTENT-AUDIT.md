# Zorva Marketing Site — Content & Trust Audit

**Audited:** 2026-07-13
**Scope:** 28 marketing routes + base layout, `src/ai_billing_audit/templates/`
**Audience lens:** Alberta AHCIP physician, PCN central-office admin, clinic privacy officer
**Verdict:** The product story is unusually specific and well-positioned for an Alberta-first pre-submit auditor, but the **site leaks trust signals**, has **at least three verbatim contradictions** between pages, ships a **placeholder tenant name in the public topbar**, and **most marketing pages are unreachable from the topbar nav**. Fix the P0s before the first paying pilot signs.

---

## Executive summary

- **The placeholder "Acme Family Practice" tenant pill is rendered on every public marketing page** (base.html:27, fed by `TENANT_NAME` env default in api.py:856). Every Alberta physician sees a fake clinic name in the topbar of a healthcare SaaS site. Critical.
- **Pilot duration is 60 days on six pages and 90 days on two pages** (home.html:91, pilot.html:7 vs contact.html:12, legal_terms.html:19, 23). **Pricing tier thresholds are 5× apart between pricing.html and the legal terms / ROI calculator** (pricing.html:43–63 says 1,000/3,000/3,000+ audits; legal_terms.html:38–40 and roi.html:91–93 say 200/2,000/2,000+ claims). Either copy is a billing dispute waiting to happen.
- **The only public case studies are US-CPT, not AHCIP.** case_studies.py references 99213/99214/99396/93000/80061/93306/R00.2/E11.65, with prose like "the payer would treat the second service as bundled" — but home.html, about.html, and pricing.html all lead with "Alberta-first, 18 AHCIP rules." The strongest conversion asset (worked examples) contradicts the positioning.
- **All four blog-post links are 404s.** blog.html:18, 32, 45, 60 link to /blog/why-we-built-zorva, /blog/18-ahcip-rules, /blog/why-flat-fee, /blog/why-alberta-first — but api.py only defines `/blog` (api.py:4431). Every blog post link is broken; the only content is the teaser.
- **19 marketing pages are not in the topbar.** Topbar has 9 items (base.html:17–25); footer has 12. About, Blog, Careers, Changelog, Compare, Demo-Request, Glossary, Pilot, Press, ROI, Status, Trust, What-Zorva-Finds, and /for/family-medicine are footer-only — effectively invisible to a prospect who lands on the home page.
- **No /404, /500, /503 branded pages. No og-image.png. No skip-to-content. No cookie consent. No newsletter signup. No Calendly.** All standard hygiene missing.
- **No actual named customer testimonials anywhere.** press.html:101–118 has two quotes attributed to "Billing lead, Alberta family-medicine clinic" and "PCN operations director, central Alberta" with no clinic name, no first name, no photo. privacy officers and PCN admins will look for "Acme Family Medicine Clinic" or "Calgary Foothills PCN" — they won't find one.
- **status.html is dishonest.** status.html:17 claims "Updated on every page load by hitting the production /healthz endpoint" and shows "Last checked: just now" (line 25) and "All systems operational" (line 22). The route (api.py:4505) just renders the template with no healthz call. A privacy officer will click /healthz and see hardcoded lies on a public status page.

---

## Per-page findings

| Page | Headline strength | Primary CTA | Trust signals | Body copy | Verdict |
|---|---|---|---|---|---|
| **home.html** | Strong. "Find the revenue your billers are leaving on the table." (line 18) — concrete dollar pain, "your" not "the industry's." | Two clear CTAs: "Try Zorva on a sample claim" (line 26) and "Send 100 claims, get a 1-page audit" (line 27). Strong "no signup, no contract" (line 31). | "Built by Cameron Ashley" + Upwork badge (line 38). No customer logos, no clinic name. The "19-encounter audit" claim (line 116) doesn't match the 3 case studies actually on the site. | Pillar copy is specific and bulletproof: rule names (CMGP, modifier-25), GR references, dollar amounts. One of the better pages. | Strong. Fix the 19-encounter claim and add one named customer. |
| **about.html** | "About Zorva" (line 7) — fine but generic. Subhead (line 10) says "Toronto studio" — geographic conflict with Alberta-first positioning. | One CTA: "Get in touch" (line 13) | Cameron bio (line 49) is honest about being a one-person founder; company facts (line 79) is concrete (Ontario Inc., 2021, self-funded). | Story (line 19) is specific — names Dr. Bill / Petal / Accuro / TELUS PS Suite / OSCAR Pro (line 21) and the actual gap. F1=0.690 claim (line 30) needs a citation or it'll undermine trust. | Good. Trim Toronto references; add a real customer or pilot partner. |
| **blog.html** | "Blog" (line 8) | Single "RSS · Atom" link (line 14). | None. | Post teasers are excellent. **All four post links 404** (lines 18, 32, 45, 60) because no `/blog/{slug}` route exists. The page advertises 4 posts it can't show. | Critical bug. Either ship a per-slug route or strip the links. |
| **careers.html** | "Careers" — fine. | "Apply directly" mailto (line 14). | Two real, well-scoped roles with CAD salary ranges and "what you'll do / what you need" structure. | Specific (FastAPI, litellm, instructor, HIA IMA, hash-chained audit trail, AHCIP SOMB). One of the more credibility-building pages. | Strong. Genuinely useful copy. |
| **changelog.html** | "Changelog" — fine. | "View on GitHub" (line 14). | Release list is detailed and shows real engineering (v0.5.0 fixed `re` import bug at line 60 — names the actual bug, not a vague "stability fix"). | Honest and specific. "First Alberta prospect list (12 clinics)" (line 32) — proves there's an actual go-to-market in motion. | Strong. The most credibility-building page after security.html. Add a per-release deep-link anchor target so RSS clicks land on the version. |
| **compare.html** | "Zorva vs the alternatives" (line 7). Subhead (line 10) names every named competitor explicitly. | "Send 100 claims, get a 1-page audit" (line 15). | Names Dr. Bill, PetalMD, CodaMetrix, AKASA, SmarterDx by name (lines 10, 109). Comparison table is honest about gaps (no managed submission, OHIP 2027). | Side-by-side (line 41) is the kind of table PCN admins will screenshot. "When Zorva is not the right fit" (line 113) is unusually honest. | Strong. One of the better pages. |
| **contact.html** | "Send 100 claims, get a 1-page audit" (line 8) — strong, specific, low-commitment. | Form is the CTA. | Trust bar: SHA-256 reference, deletion-on-email commitment, IMA-before-data-moves. | **Copy error at line 72:** placeholder text reads "We're a 6-physician family practice in Toronto. Currently 6% of our claims get denied." Zorva is Alberta-first. This is a copy-paste leftover from an Ontario draft. Drop the placeholder or change Toronto → Calgary/Edmonton. Also: 90-day pilot (line 12) contradicts 60-day everywhere else. | Good bones, but the Toronto placeholder is a real risk — a privacy officer will read it and wonder. |
| **demo-request.html** | "Book a 30-minute walkthrough" (line 8) — fine, but "book" implies Calendly. There is no Calendly. The form posts to **/contact, not /demo-request** (line 68). | Form posts to /contact. | EMR dropdown (line 80) names TELUS PS Suite, OSCAR Pro, Accuro, Med Access, Epic, Other — credibility-building. | Honest: "We do a live walkthrough on a call, then run the auditor on the sample you bring." (line 11) Sets expectations. | Decent. Wire the form to a `/demo-request` endpoint that records the request type, or add a one-line note saying "this routes to the same form as /contact." |
| **faq.html** | "Frequently asked questions" — generic. | "For the privacy officer →" (line 14) | Strong — sections grouped by role: privacy officer, billing lead, clinic manager, IT contact (line 21). | Specific, names real things (PATIENT_HASH_PEPPER, patient-hash:v1, temperature 0, seed pinned, model version pinned). One of the strongest pages. | Strong. Leave alone. |
| **for/family-medicine.html** | "Zorva for family medicine" (line 8) — vertical-specific. | "Open the sample claim" (line 13). | Names 7 specific rules with dollar amounts. Worked example (line 124) is concrete. | Specific. "A 5–10-physician family-medicine practice submitting 3,000–5,000 AHCIP claims per month will see roughly 800–1,500 findings per month from the auditor." (line 89) — this is the kind of number a clinic manager will latch onto. | Strong. One of the highest-converting pages. |
| **glossary.html** | "Glossary" — fine. | "How Zorva works →" (line 14). | 20 terms with definitions, all Alberta-flavored. | Specific (GR 1.4, GR 4.4, GR 3.3, AHCIP 80G, 31, 37A, etc.). Privacy officer can hand this to a new hire. | Strong. The kind of artifact a PCN admin will bookmark. |
| **how-it-works.html** | "How Zorva works" — fine. | "Open the sample claim" (line 13). | Lists the 18 AHCIP rules grouped by severity (line 67). Determinism contract (line 96) is a key differentiator. | Audit chain SHA-256 formula (line 130) — unprecedented transparency for a marketing page. | Strong. The privacy officer's first stop. |
| **pilot.html** | "60-day no-cost pilot" (line 7) — clear. | "Request a pilot" (line 14). | Week-by-week timeline (line 35). "What we get" (line 73) is rare honesty: testimonial ask with a soft out ("if you're not, no ask"). | Strong. But the duration is 60 here and 90 in contact.html + legal_terms.html — pick one. | Strong. Reconcile pilot duration. |
| **press.html** | "Press" — fine. | "Email press@ashbi.ca" (line 15). | Boilerplate in 3 lengths (line 22, 27, 38). Fact sheet (line 55) is the kind of asset a journalist will copy. **No third-party coverage** (line 99) — honest. | Two testimonials at line 101, 109 — both attributed to roles only, no clinic name, no last name. The "billing lead" quote ("Zorva caught four patterns… the audit paid for itself in the first week") is the strongest social proof on the site. But it has zero attribution. | Good skeleton, weak attribution. Either get written permission from the named pilot and add the clinic name, or strip the quotes. |
| **pricing.html** | "Pricing" — fine. Subhead (line 10) says flat fee + AKS safe-harbor + IMA in executed agreement. | "Send 100 claims first" (line 14). | 3-tier card grid (line 17). Each tier is a real spec, not "Contact us for pricing." | **Volume thresholds are 1,000/3,000/3,000+ audits (line 43, 47, 63) but legal_terms.html:38 says 200/200-2,000/2,000+ and roi.html:91 says 200/2,000/2,000+.** Five-fold discrepancy. **A privacy officer who reads both pages will flag this as a billing trap.** | Critical — reconcile pricing tiers. |
| **roi.html** | "ROI calculator" — fine. | The form is the CTA. | Default inputs are 1,000 claims / 7.5% denial / $190 avg (line 35, 44, 53) — reasonable defaults. | Plan tier dropdown (line 90) labels are "Starter/Growth/Scale" but pricing.html:17 labels them "Solo/Practice/Network." **Two different naming schemes for the same tiers.** | Fix tier names. |
| **security.html** | "Security & compliance" (line 7) — fine. | "Read the privacy doc" (line 13). | Controls matrix (line 35) is detailed and specific: TLS 1.3, AES-256, salted SHA-256 with fail-fast, hash-chained audit trail, RBAC. Frameworks table (line 110) is honest: HIA active, PHIPA on request, SOC 2 not held. | One of the strongest pages. The 5 questions summary at the bottom (line 137) is exactly what a privacy officer will want. | Strong. This is the page that should rank in Google for "AHCIP privacy officer brief." |
| **status.html** | "System status" — fine. | "/healthz →" (line 14). | **Hardcoded "All systems operational"** (line 22) and "Last checked: just now" (line 25) and "Updated on every page load by hitting the production /healthz endpoint" (line 11). The route (api.py:4505) does **not** call /healthz — it just renders the template. A status page that lies is worse than no status page. | Either wire it to call /healthz in Python (or client-side fetch + DOM update) or remove the "live" claim and call it a static status snapshot. | Critical — fix the lie. |
| **trust.html** | "Subprocessors" (line 7) — fine. | "Privacy doc" (line 14). | Subprocessor table (line 35) names Hostinger, MiniMax, Stripe, Resend, Let's Encrypt, GitHub with regions and agreements. **This page should be titled "Subprocessors" not "Trust"** — privacy officers look for "subprocessors" specifically (HIA Schedule A). | Strong on detail. The "How we add a new subprocessor" 30-day-notice process (line 84) is exactly what a privacy officer will want. | Strong. Rename the nav label "Subprocessors" for clarity. |
| **try.html** | "Try Zorva on a sample claim" (line 8) — strong, low-commitment. | "More case studies →" (line 14). | The sample encounter (line 19) is concrete: 50-year-old hypertension + sore shoulder, 99213 + 20610, 3 findings with $45/$85/$50 dollar impacts. | This is the single best page for conversion. A physician can read it in 60 seconds and see exactly what the product does. | Strongest page on the site. Don't touch. |
| **what-zorva-finds.html** | "What Zorva finds" — fine. | "Open the sample claim" (line 14). | 12 of the 18 AHCIP rules listed with severity badges and dollar estimates. | Strong — high-severity rules (modifier-25, CMGP, referring NPI, non-insured, telehealth consent) listed first, which is what a privacy officer will want to see. | Strong. |
| **case_studies.html** | "Case studies" (line 8) | Cards link to /case-studies/{slug} (line 38). | 3 case studies, all US-CPT specialty (primary_care, cardiology). | **Body of every case study uses US CPT codes (99213, 99214, 99396, 80061, 93306, 93000) and US ICD-10 (R00.2, I10, E11.65), not AHCIP.** The case_studies.py docstring claims these are drawn from `data/val.json` and `data/train.json` — which is a US-CPT training set, not the cleaned AHCIP val set. **This contradicts the entire Alberta-first positioning.** The "encounter_link" points to /encounter/enc_10032 etc., which may or may not exist on the marketing surface. | Critical — AHCIP-coded case studies or change the "Alberta-first" positioning. |
| **case_study_detail.html** | Template renders fine. | "Send the 100 claims →" (line 91). | "See it live" link goes to /encounter/enc_XXXX (line 76) — works for demo encounters. | Same CPT-not-AHCIP issue as above. | Inherits case_studies.py issues. |
| **legal/privacy.html** | "Privacy Policy" — fine. | Email link (line 124). | Claims 60-day breach notification per HIPAA §164.410 (line 95). **But HIPAA allows 60 days, HIA requires "as soon as possible" — 60 days may not be acceptable to an Alberta privacy officer.** Also calls `Ollama Cloud` the LLM (line 109) but the rest of the site calls it "MiniMax" / "your LLM provider." Two different LLM names for the same product. | The page says "v1 stub — replace with lawyer-reviewed copy before the first paying pilot signs" (line 8). It's not lawyer-reviewed. **The footer of pricing.html:88 sends people to this page and tells them to read it.** | Critical for first paying pilot. Either get lawyer review or change the page label from "Privacy Policy" to "Privacy Policy (DRAFT — pre-pilot stub)." |
| **legal/terms.html** | "Terms of Service" — fine. | Email link (line 120). | 90-day pilot (line 19, 23) — **contradicts home.html:91, pilot.html:7, faq.html:172 (60 days).** Pricing tiers at 200/2,000/2,000+ (line 38–40) — **contradicts pricing.html:43–63 (1,000/3,000/3,000+).** | Same v1 stub banner. | Critical for first paying pilot. Reconcile pilot + tier numbers. |

---

## Cross-cutting gaps (no per-page owner)

### 1. Topbar / nav inconsistency
- **base.html:17–25** lists 9 nav items: Home, Audits, Upload, Pricing, How it works, Security, Try, FAQ, Contact.
- **base.html:30–41** (footer) lists 12 nav items.
- **19 marketing pages are NOT in the topbar:** /about, /blog, /careers, /changelog, /compare, /demo-request, /glossary, /pilot, /press, /roi, /status, /trust, /what-zorva-finds, /for/family-medicine, /case-studies, /legal/privacy, /legal/terms, /audits, /encounters/upload.
- The topbar also includes `/audits` and `/encounters/upload` (dashboard routes, not marketing), which suggests the topbar was designed for an authenticated dashboard view, not a public marketing view. A prospect landing on /pricing and looking for "About" or "Case studies" must scroll to the footer.

### 2. "Acme Family Practice" placeholder visible on every public page
- base.html:27 renders `<div class="tenant-pill">{{ tenant_name or "Acme Family Practice" }}</div>`.
- api.py:856 sets `_TENANT_NAME = "Acme Family Practice"` as the env default.
- **No marketing route overrides `tenant_name` in the template context.** The home page, about page, pricing page, security page — every one shows the literal string "Acme Family Practice" in the topbar.
- This is a fake clinic name. An Alberta physician who lands on the site sees "Acme Family Practice" in the topbar and assumes the site is in a broken state, or that they're somehow on a demo tenant. **Critical bug.**

### 3. Brand mark is a single letter
- base.html:13 renders `<span class="brand-mark">A</span>`.
- There is no logo file in `src/ai_billing_audit/static/` (only favicon.svg, upload.js, dashboard.css).
- A single letter "A" is not a brand mark. It's a placeholder.

### 4. Email domain split (zorva.ca vs ashbi.ca)
- /contact uses `sales@zorva.ca` (api.py:4665)
- /legal/privacy uses `privacy@zorva.ca` (api.py:4328)
- /legal/terms uses `support@zorva.ca` (api.py:4341)
- /about, /careers use `cameron@ashbi.ca` (about.html:85, careers.html:14, 103, 110)
- /press uses `press@ashbi.ca` (press.html:15, 122)
- /security uses `security@ashbi.ca` (security.html:138)
- /status uses `support@ashbi.ca` (status.html:115)
- A prospect who emails `support@zorva.ca` and gets a reply from `cameron@ashbi.ca` will be confused about which company they're actually dealing with. Pick one domain and stick to it.

### 5. Pilot duration: 60 vs 90 days
- **60-day:** home.html:91, pilot.html:7, pilot.html:21, pilot.html:25, pilot.html:33, faq.html:172, faq.html:181, careers.html:81, demo-request.html:38, press.html:68
- **90-day:** contact.html:12, legal_terms.html:19, legal_terms.html:23
- Six pages say 60 days. Two say 90 days. The legal terms page is the one that will be signed — 60 is the marketing number, 90 is the binding number. Pick one.

### 6. Pricing tier volume thresholds: 1,000/3,000/3,000+ vs 200/2,000/2,000+
- **pricing.html:43, 47, 63:** "Up to 1,000 encounter audits / month," "Up to 3,000 encounter audits / month," "3,000+ encounter audits / month."
- **legal_terms.html:38–40:** "$499: up to 200 claims / month. $1,499: 200–2,000 claims / month. $2,999: 2,000+ claims / month."
- **roi.html:91–93:** "Starter — $499/mo, up to 200 claims. Growth — $1,499/mo, up to 2,000 claims. Scale — $2,999/mo, 2,000+ claims."
- 5× discrepancy. The legal terms are the binding document. A clinic that signs a $1,499 tier and submits 800 claims will be told they need the $2,999 tier if pricing.html is right, or be fine if the legal terms are right. This is a billing dispute waiting to happen.

### 7. Pricing tier names: Solo/Practice/Network vs Starter/Growth/Scale
- pricing.html:18, 36, 56: "Solo / Practice / Network"
- roi.html:91–93: "Starter / Growth / Scale"
- These are the same three tiers with two different naming schemes. Pick one.

### 8. Case studies are US-CPT, not AHCIP
- case_studies.py:148 (slugs) and case_studies.py:170+ (bodies) all use US-CPT codes (99213, 99214, 99396, 80061, 93306, 93000) and US ICD-10 codes (R00.2, I10, E11.65).
- The case study prose uses US payer language: "the payer would treat the second service as bundled" (line 159), "the payer denies the 99214" (line 222).
- The home page, about page, pricing page, security page, what-zorva-finds page, and how-it-works page all position Zorva as AHCIP-first.
- **The only worked-example asset on a marketing site that sells "Alberta-first, 18 AHCIP rules" is written in US-CPT.** An Alberta physician will look at case_studies.html and see 99213 / 99396 / 80061 — codes that don't exist in AHCIP SOMB. This is a credibility-killer.

### 9. status.html is fake-dynamic
- status.html:11 says "Updated on every page load by hitting the production /healthz endpoint."
- status.html:25 says "Last checked: just now (this page hits /healthz on every load)."
- The route (api.py:4505) does not call /healthz. It just renders the template with hardcoded "All systems operational" and a fake timestamp.
- A privacy officer will open the page source and see the lie. Or will hit /healthz manually (status.html:14 advertises it) and notice the page claims "just now" while the page rendered seconds ago and the healthz JSON says something different.

### 10. No /404, /500, /503 branded pages
- No 404.html, 500.html, or 503.html in `src/ai_billing_audit/templates/`.
- No `@app.exception_handler(404)` or similar in api.py.
- A prospect who mistypes /tryy or /piltot sees FastAPI's default JSON error or a generic white page with no Zorva branding. This is a top-of-funnel drop.

### 11. No og-image.png, no og:title, no og:description
- No image at `static/og-image.png`.
- No `<meta property="og:*" />` tags in any template's `<head>` (base.html:4–8 has only charset, viewport, title block, stylesheet, favicon).
- Every link shared on LinkedIn / Twitter / Slack / email will preview as a blank card with no image. The Zorva pitch is visual (modifier-25, CMGP) — there should be an og-image.

### 12. No skip-to-content link
- base.html has no `<a class="skip-link" href="#main">Skip to content</a>` before the topbar.
- Accessibility requirement for screen readers and keyboard users. A privacy officer who navigates by keyboard has to tab through 9 topbar items + 12 footer items to get to the body on every page.

### 13. No cookie consent banner
- No cookie banner in base.html or any page.
- The site does not set cookies explicitly (no JS reads/writes cookies), but the legal/privacy page references cookies in the privacy-officer FAQ (faq.html:31) and the contact form records submissions in the audit trail. PIPEDA / HIA / GDPR require disclosure of any tracking technology. The site claims PIPEDA + HIA compliance (security.html:114) without a consent banner.

### 14. No newsletter signup / lead-capture form
- No "Subscribe to our newsletter" form anywhere.
- blog.html:95–99 says "RSS or send a note and we'll add you" — but there is no "send a note" form on the blog page. The CTA points to /contact, which is a sales-form for "send 100 claims," not a newsletter subscribe.
- changelog.html:111–115 has the same RSS-or-contact pattern.
- A prospect who wants to follow Zorva without doing the sales form has only the RSS feed. That's fine for a technical audience; it's a leak for a clinic manager.

### 15. No Calendly / "Talk to a human" path
- demo-request.html:7 says "Book a 30-minute walkthrough" but there is no Calendly / Cal.com / scheduled-time widget. The form (line 65) submits to /contact, which is the same endpoint as the "send 100 claims" form.
- A clinic manager who wants a 15-minute conversation has no low-friction way to get one. The contact form requires them to either commit to a 100-claim audit or write a custom message.

### 16. No named customer testimonials
- press.html:101–118: two quotes attributed to "Billing lead, Alberta family-medicine clinic (2026-Q2 pilot)" and "PCN operations director, central Alberta (2026-Q2 pilot)." No clinic name, no first name, no photo, no LinkedIn.
- The press page itself says "2 Alberta clinics in 60-day pilot (as of 2026-07-13)" (line 68). Those two clinics exist by name internally. If even one clinic has agreed to be named publicly, that's the strongest social proof on the site and it's invisible.
- If no clinic has agreed, the quotes should be removed — anonymized quotes on a healthcare site are a yellow flag, not a green one.

### 17. No third-party coverage or trust seals
- No "As seen in" logos.
- No "Member of" / "Certified by" seals (because none are held; security.html:117 is honest about SOC 2 + ISO 27001 being roadmap items).
- The "Built by Cameron Ashley · Top Rated on Upwork" bar (home.html:38) is the only third-party credibility marker. For a healthcare SaaS selling to PCN central-office admins, the absence of *any* named institutional reference (a college, a PCN, a clinic, a hospital, an academic center) is a gap.

### 18. F1=0.690 is a single test-set number
- about.html:30 says "The auditor runs at F1=0.690 on the cleaned AHCIP val set." home.html:107 says "about 77 of every 100 real billing errors caught before they hit the payer, with about 6 of every 10 raised flags being a real finding."
- The how-it-works page lists 10 encounters / 13 gold findings on the val set (changelog.html:75 implies this scale).
- A 10-encounter / 13-finding val set is a small-n validation. The site quotes a single F1 number as if it were a benchmark. A privacy officer or a skeptical clinic manager will ask: "how many encounters did you test on?" The honest answer is "10."

### 19. "19-encounter audit" claim on home.html doesn't match site
- home.html:116 says "A 19-encounter audit on a real AHCIP-style sample."
- /try shows 1 encounter with 3 findings.
- /case-studies shows 3 studies with 1+2+5 = 8 findings.
- The "19-encounter" / "19-encounter audit on a real AHCIP-style sample" doesn't correspond to anything on the site. It's an internal pilot that hasn't been published.

### 20. Demo-request form posts to /contact
- demo-request.html:68 has `<form class="contact-form" method="post" action="/contact">` and /contact's success state (contact.html:18) sends the user to /case-studies and /roi.
- The form is semantically a "demo request" but routes to the "send 100 claims" endpoint. From the prospect's perspective: I asked for a walkthrough; the success page says "thanks, here's a 1-page audit." Misaligned.

### 21. Empty-state body on home / pricing / for/family-medicine
- for/family-medicine.html:88 says "A 5–10-physician family-medicine practice submitting 3,000–5,000 AHCIP claims per month will see roughly 800–1,500 findings per month from the auditor. Of those, the biller accepts 600–1,200 (about 75% are real findings) and dismisses 200–300."
- These numbers are not cited. A privacy officer will ask: "is this from your 10-encounter val set, or from a real customer?"

---

## Prioritized fix list

### P0 — Ship-blocker (fix before first paying pilot signs)

1. **Replace the "Acme Family Practice" tenant pill on every marketing page** (base.html:27, fed by api.py:856). The simplest fix is to remove the tenant-pill from the public marketing topbar entirely, or to gate it on an authenticated request. Showing a fake clinic name to every prospect is a credibility-killer.
2. **Fix the 60-day vs 90-day pilot duration contradiction.** Reconcile to 60 days across home.html:91, pilot.html:7, contact.html:12, careers.html:81, demo-request.html:38, faq.html:172, faq.html:181, press.html:68, legal_terms.html:19, legal_terms.html:23.
3. **Fix the 1,000/3,000 vs 200/2,000 pricing tier contradiction.** Reconcile pricing.html:43/47/63 with legal_terms.html:38–40 and roi.html:91–93. Pick a number and apply it everywhere. This is a billing-trap risk.
4. **Either add a `/blog/{slug}` route that renders per-post content, or strip the post links from blog.html.** The current state advertises 4 blog posts and links to all 4 of them as 404s.
5. **Make the case studies Alberta-AHCIP, not US-CPT.** Either rewrite case_studies.py with AHCIP GR references and SOMB-procedure codes, or change the entire "Alberta-first" positioning to admit that the only worked examples are US-CPT cardiology. The current contradiction is a trust-destroyer.
6. **Make status.html honest.** Either wire the route (api.py:4505) to call /healthz in Python, or remove the "Updated on every page load" claim and call it a static status snapshot. A lying status page is worse than no status page.
7. **Fix the geographic copy error in contact.html:72** — change "We're a 6-physician family practice in Toronto" to a Calgary/Edmonton example. This is a copy-paste leftover from an Ontario-targeted draft.
8. **Reconcile the email domain split.** Pick `ashbi.ca` or `zorva.ca` and apply consistently. The current 6-email split across two domains confuses prospects about which company they're actually engaging with.

### P1 — Trust + conversion (fix in the next sprint)

9. **Add 14 marketing pages to the topbar nav.** The topbar is missing About, Blog, Careers, Changelog, Compare, Demo-Request, Family-Medicine, Glossary, Pilot, Press, ROI, Status, Trust, What-Zorva-Finds. Either restructure the topbar to a "Product / Company / Resources" mega-menu, or add a "More" dropdown.
10. **Add a branded 404 page, a 500 page, and a 503 page.** Wire `@app.exception_handler(404/500/503)` in api.py and ship `templates/404.html` extending base.html. Top-of-funnel drop today.
11. **Add `og:image`, `og:title`, `og:description` meta tags** in base.html:4–8, plus a 1200×630 static/og-image.png. Every LinkedIn/Twitter/email share previews as a blank card today.
12. **Add a skip-to-content link** in base.html before the topbar for screen-reader and keyboard accessibility.
13. **Either get written permission from one of the two pilot clinics to use their name, or remove the two anonymous quotes from press.html:101–118.** Anonymized quotes on a healthcare site read as a yellow flag, not a green one. If you can name one clinic, do it.
14. **Wire demo-request.html:68 to a `/demo-request` endpoint** (or add a one-line note that says "this routes to the same form as /contact"). The current state has a "book a walkthrough" form that posts to the "send 100 claims" endpoint.
15. **Reconcile pricing tier names** between pricing.html (Solo/Practice/Network) and roi.html (Starter/Growth/Scale). Pick one scheme.
16. **Replace the literal "A" brand mark in base.html:13** with a real logo SVG in `static/`. Single-letter brand marks read as placeholder.
17. **Add a real favicon** beyond the current `favicon.svg` — `apple-touch-icon-180x180.png`, etc. — so the site looks finished in iOS Safari tabs and Android home screens.

### P2 — Polish

18. **Add a cookie consent banner.** Even if the site doesn't set cookies today, the legal/privacy page references cookies. PIPEDA / HIA / GDPR require disclosure.
19. **Add a `/newsletter` route + form** for prospects who want to follow without doing the sales form. The current "send a note and we'll add you" CTA on blog.html and changelog.html has no follow-through path.
20. **Add a Calendly / Cal.com embed** on /demo-request so a clinic manager can pick a 15-minute slot without filling a form.
21. **Add a third-party coverage / certification section** to trust.html (or create a new /press page section for it). Even an empty state with "We're working on PCN-level reference customers" is better than the current state.
22. **Cite the F1=0.690 number with the val set size** (about.html:30, home.html:107). "F1=0.690 on a 10-encounter / 13-gold-finding cleaned AHCIP val set" is the honest version.
23. **Reconcile the "19-encounter audit" claim on home.html:116** with the actual case studies on the site. Either publish a `/case-studies/19-encounter-audit` that backs the claim, or drop the line.
24. **Add a sitemap entry for /case-studies/{slug}** in feeds.py:PUBLIC_MARKETING_PATHS. The per-slug case studies exist (case_studies.py) but are not in the sitemap (feeds.py:163), so search engines won't index them.
25. **Reword the "lawyer review" / "v1 stub" disclaimers** in legal_privacy.html:7, 8 and legal_terms.html:7, 8. Either get lawyer review, or change the page label from "Privacy Policy" to "Privacy Policy (DRAFT — pre-pilot stub)" so a privacy officer doesn't read it and assume it's binding.
26. **Add `aria-label` and `aria-current="page"`** to the topbar links in base.html:17–25. Accessibility hygiene.
27. **Add a no-EMR note to the case study template** for case_studies.html:38 — the "See live encounter ↗" button (case_studies.html:41) requires the prospect to know that the encounter is a demo, not their own. Consider a "View demo encounter" label.
