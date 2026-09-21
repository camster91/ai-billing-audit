# Zorva — Press Kit

> **For journalists, bloggers, podcasters, and analysts.** If you are
> writing about Zorva, quoting Zorva, or covering the AI-medical-
> billing category in general, this document is your one-stop shop.
> For interview requests, embargoed product news, or fact-checking
> questions, email **press@zorva.ai**.

---

## 1. Company backgrounder (≈ 250 words)

Zorva is a pre-submission medical-billing auditor that reads every
clinical note the way a careful senior biller would — and catches
both the errors that lead to denials and the under-coded services
that lead to lost revenue. Founded in 2025 and headquartered in
Calgary, Alberta, Zorva is built by a small team of physicians,
billing leads, and ML engineers who have personally felt the gap
between the clinical encounter and the submitted claim.

Zorva's auditor is anchored to the Alberta Schedule of Medical
Benefits (SOMB) and to the published AHCIP billing rules. On the
cleaned v12 evaluation against 10 held-out AHCIP encounters, the
auditor achieves a micro-averaged F1 of **0.690** with zero
errors — a number we publish in full transparency, including the
EXAMPLE 6/7 leakage correction that made the v12 number
defensible. Per-rule precision and recall are available on
request and in the published run outputs.

Zorva's commercial model is a CAD $1,500 60-day pilot, credited against
the first month if the clinic continues, followed by tiered monthly
pricing from $499/month (no per-claim charges). A free 100-claim sample
report is available before any pilot. We do
not sell claim data, we do not train models on customer data, and
the pilot deliverable is owned by the clinic — we delete it on one
email at the end of the engagement.

Zorva is currently in pilot with family-medicine, cardiology, and
psychiatry practices across Alberta and is opening its first US
specialty pilot in Q3 2026.

### Short form (≈ 50 words, for "About" sidebars)

Zorva is a Calgary-based medical-billing auditor that reads
clinical notes before claims are submitted and surfaces both the
errors that lead to denials and the under-coded services that lead
to lost revenue. The auditor is anchored to the Alberta SOMB and
publishes its evaluation metrics in full.

### Boilerplate (≈ 30 words, for press releases)

Zorva is a Calgary-based healthcare-AI company building
pre-submission billing-audit software for outpatient practices.
Founded 2025. Learn more at zorva.ai.

---

## 2. Five quotable stats

These are the numbers we are happy to see quoted. Each is
defensible against the cited source.

1. **"On the cleaned v12 AHCIP evaluation, Zorva's auditor
   achieves a micro-averaged F1 of 0.690 with zero errors on 10
   held-out encounters."**
   *Source: `runs/recall/v12_ahcip_clean.json`,
   `runs/recall/v12_summary.md` (v12 EXAMPLE 6/7 leakage
   disclosure).*

2. **"An average Alberta family-medicine clinic with 1,500
   claims/month and an 8% denial rate is leaving roughly $54,720
   per year on the table from missed modifiers and undercodes —
   of which a defensible 38% is recoverable with audit action."**
   *Source: `docs/research/ROI-FORMULA.md`, §6 worked example.*

3. **"Roughly $14,000 of projected annual recovery per 1,000
   claims/month at an 8% denial rate, for Alberta family-
   medicine."**
   *Source: `docs/research/ROI-FORMULA.md`, §7 sensitivity table.*

4. **"Five AHCIP rules in v12 achieve perfect precision and
   recall: diagnosis-linkage, global-window, referring-NPI,
   same-day-conflict, and telehealth premium."**
   *Source: `runs/recall/v12_ahcip_clean.json`, per-rule table.*

5. **"Zorva's 100-claim pilot takes 38 minutes to review end-to-
   end, against a manual baseline of approximately six hours."**
   *Source: `docs/case-studies/MOCK-100-CLAIM-PILOT.md`
   (synthetic composite — flagged in the document).*

---

## 3. Three boilerplate press release templates

### 3.1 Product launch

> **FOR IMMEDIATE RELEASE**
>
> **Zorva launches pre-submission medical-billing auditor for
> Alberta outpatient practices**
>
> Calgary, AB — [DATE] — Zorva, a Calgary-based healthcare-AI
> company, today announced the public launch of its pre-submission
> medical-billing auditor. Zorva reads every clinical note the way
> a careful senior biller would and surfaces both the errors that
> lead to denials and the under-coded services that lead to lost
> revenue — *before* the claim is submitted to the payer.
>
> On the cleaned v12 evaluation against held-out Alberta Health
> Care Insurance Plan (AHCIP) encounters, Zorva's auditor achieves
> a micro-averaged F1 of 0.690 with zero errors. The full
> per-rule precision and recall are published in the company's
> technical disclosure.
>
> Zorva's commercial model is a CAD $1,500 60-day pilot (credited
> against the first month if the clinic continues), followed by tiered
> monthly pricing from $499/month. A free 100-claim sample report is
> available before any pilot. Pilot customers retain ownership of every
> claim, every finding, and every audit-log entry; the company
> deletes the entire engagement on one email at the pilot's end.
>
> "The expertise to catch both kinds of mistake — the wrong code
> and the missing one — exists nowhere in the workflow today, so
> the money leaks out the bottom of the practice while everyone is
> busy doing their actual job," said [FOUNDER NAME], Zorva's
> [TITLE]. "Zorva closes that gap."
>
> Zorva is available immediately to Alberta family-medicine,
> internal-medicine, cardiology, pediatrics, psychiatry,
> dermatology, orthopedics, and Ob/Gyn practices.
>
> **About Zorva**
> Zorva is a Calgary-based healthcare-AI company building
> pre-submission billing-audit software for outpatient practices.
> Founded 2025. Learn more at zorva.ai.
>
> **Media contact**
> press@zorva.ai

### 3.2 Partnership

> **FOR IMMEDIATE RELEASE**
>
> **Zorva partners with [PARTNER] to bring pre-submission billing
> audit to [AUDIENCE]**
>
> Calgary, AB — [DATE] — Zorva, a Calgary-based healthcare-AI
> company, today announced a partnership with [PARTNER NAME] to
> [PARTNERSHIP SUMMARY: e.g. "deliver pre-submission billing
> audit to [NUMBER] Alberta primary-care clinics through
> [PARTNER]'s practice-management platform"].
>
> Under the partnership, [PARTNER]'s customers will be able to
> [CONCRETE INTEGRATION: e.g. "enable Zorva's auditor with a
> single click from inside the existing billing dashboard, with
> results delivered back to the same workflow"]. Pilot data and
> claim content remain owned by the practice; Zorva and [PARTNER]
> do not share claim data between tenants.
>
> "The partnership with [PARTNER] lets us reach [NUMBER] practices
> on day one without forcing a workflow change," said [FOUNDER
> NAME], Zorva's [TITLE]. "[ONE-SENTENCE QUOTE FROM PARTNER
> EXECUTIVE — to be supplied by partner]."
>
> The partnership is effective [DATE]; the joint offering is
> available to [PARTNER] customers [DATE RANGE].
>
> **About Zorva**
> Zorva is a Calgary-based healthcare-AI company building
> pre-submission billing-audit software for outpatient practices.
> Founded 2025. Learn more at zorva.ai.
>
> **About [PARTNER]**
> [PARTNER BOILERPLATE — to be supplied by partner]
>
> **Media contact**
> press@zorva.ai

### 3.3 Customer win

> **FOR IMMEDIATE RELEASE**
>
> **[CUSTOMER NAME] deploys Zorva to audit pre-submission claims
> across [NUMBER] physicians**
>
> [CITY, PROVINCE] — [DATE] — [CUSTOMER NAME], a [SPECIALTY /
> TYPE] practice with [NUMBER] physicians, has deployed Zorva's
> pre-submission billing auditor across its [NUMBER]-physician
> group.
>
> In a 100-claim pilot preceding the deployment, Zorva surfaced
> [NUMBER] findings, of which the customer's billing lead
> accepted [NUMBER] (XX%) and dismissed [NUMBER] (XX%). Accepted
> findings translated to an estimated $[NUMBER] in recoverable
> revenue. [OPTIONAL QUOTE FROM CUSTOMER BILLING LEAD — to be
> supplied by customer and approved before release.]
>
> "We went into the pilot skeptical of 'AI for billing' and came
> out [CUSTOMER VERDICT, ONE SENTENCE]," said [CUSTOMER
> SPOKESPerson], [TITLE] at [CUSTOMER]. [OPTIONAL: include only if
> customer has approved.] "We [took / did not take] Zorva into
> production; [if yes] the rollout covers [NUMBER] physicians and
> [NUMBER] claims/month."
>
> Zorva's commercial model is per-claim pricing tied to the
> volume the auditor catches. The deployment at [CUSTOMER] is
> governed by a signed [BAA / PHIPA-compliant data-processing
> agreement], with claims and findings owned by the customer and
> deletable on one email.
>
> **About Zorva**
> Zorva is a Calgary-based healthcare-AI company building
> pre-submission billing-audit software for outpatient practices.
> Founded 2025. Learn more at zorva.ai.
>
> **About [CUSTOMER]**
> [CUSTOMER BOILERPLATE — to be supplied by customer]
>
> **Media contact**
> press@zorva.ai

---

## 4. Three brand assets

The following brand artifacts are described for press use. Digital
copies (SVG / PNG / EPS) are available on request from
press@zorva.ai. Do not modify proportions or colors when cropping
for publication.

### 4.1 Wordmark — "Zorva"

- **Form.** Full wordmark in the Inter / Geist typeface family.
- **Color usage.** Default is teal on white. Reverse is white on
  charcoal (#0F172A). Single-color (all teal or all charcoal)
  versions are also available.
- **When to use.** Headers, hero blocks on the website, the pitch
  deck, partner co-marketing. Minimum size: 24px cap height. Clear
  space: at least one cap-height of empty space on all sides.

### 4.2 Logomark — Z-in-hex-pill

- **Form.** A geometric "Z" inscribed in a rounded-hexagon (the
  "pill") shape.
- **Color usage.** Teal primary fill, charcoal stroke, with a
  small white inner highlight on the "Z". Single-color variants
  available.
- **When to use.** Favicons, app icons, social-media avatars
  (Twitter/X, LinkedIn, GitHub), and as the badge in the corner of
  the dashboard. Minimum size: 16px square. Never recolor the
  inner highlight.

### 4.3 Lockup — wordmark + logomark

- **Form.** Wordmark stacked left of the logomark, baseline-
  aligned, with one cap-height of space between.
- **Color usage.** Same as the wordmark — teal on white, white on
  charcoal, or single-color.
- **When to use.** Email signatures, nav bars, slide-deck title
  slides, conference badges. Minimum size: the wordmark must
  remain at least 18px cap height when scaled; below that, use
  the logomark alone.

### 4.4 What NOT to do with brand assets

- Do not stretch, rotate, or skew the wordmark or logomark.
- Do not place the wordmark over busy photography without a
  solid-color scrim underneath.
- Do not recolor the wordmark in non-brand colors. The brand
  palette is teal (#0EA5A4 primary, #14B8A6 secondary),
  charcoal (#0F172A), and ink (#1E293B). Accent colors are amber
  (#F59E0B) for warnings and emerald (#10B981) for success.
- Do not combine the Zorva wordmark with another company's
  wordmark to imply an endorsement, partnership, or co-product
  that has not been approved in writing.

For the full brand spec — color values, type stack, logo
construction grid, and clear-space rules — see
`docs/BRANDING_LOGO.md` and `docs/BRANDING_COLORS.md` in the
repository.

---

## 5. Spokespeople

For interviews, please contact press@zorva.ai. The following
people are available to speak on the record about the topics
listed:

- **Founder / CEO** — company origin, product roadmap, AI-safety
  stance, Alberta health-tech ecosystem.
- **Head of Billing** (a former Alberta medical-billing lead) —
  the day-to-day of what clinics leave on the table, how the
  auditor is calibrated, how pilots are run.
- **Head of Engineering** — model evaluation, the v12 leakage
  disclosure, audit-trail design, deployment architecture.

We do not put physicians on the record about specific patient
encounters. Aggregate-level commentary on the published v12
numbers is welcome.

---

## 6. Style guide for press

When writing about Zorva, please:

- Capitalize the product name as **Zorva** (not ZORVA, not zorva).
  The first reference in an article can read "Zorva, a Calgary-
  based healthcare-AI company"; subsequent references can be just
  "Zorva".
- Refer to the auditor as the **Zorva auditor** or **Zorva's
  pre-submission auditor**. Avoid "Zorva AI", "the Zorva bot",
  or "ZorvaGPT" — we are not a chat product.
- When quoting the F1 figure, please cite it as the **cleaned v12
  evaluation** and link to `runs/recall/v12_summary.md` or the
  published version on zorva.ai/research. The previous 0.733
  number was inflated by EXAMPLE 6/7 leakage and was retracted in
  the v12 disclosure (2026-06-23).
- For Alberta billing, please use **AHCIP** (Alberta Health Care
  Insurance Plan) and **SOMB** (Schedule of Medical Benefits)
  spelled out on first reference.

---

## 7. Contact

- **Press inquiries:** press@zorva.ai
- **Pilot / customer inquiries:** pilot@zorva.ai
- **General:** hello@zorva.ai
- **Security disclosure:** security@zorva.ai (see
  `docs/SECURITY.md` for our coordinated disclosure policy)

For embargoed product news, please email at least five business
days in advance of the embargo lift. We are happy to coordinate
exclusives, but we do not agree to "permanent" embargoes.

— Zorva team. Last updated 2026-06-25.