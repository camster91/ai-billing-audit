# Zorva — Investor / Partner One-Pager (Spec)

Status: spec, ready for design production. Owner: branding kit, P1
investor/partner one-pager task (`t_c5ecfd48`). Last updated:
2026-06-24.

This document is the **content spec** for the single-page PDF we
hand (or email) to investors and channel partners. It is **not** the
clinic pitch — the clinic pitch is for a clinic billing lead, this
is for a partner-channel exec or an institutional investor. The
audiences want different things and we should not blur them.

| Audience             | Wants to see                                            |
|----------------------|---------------------------------------------------------|
| Clinic billing lead  | "Will it catch real misses on my claims?" (CLINIC_PITCH) |
| Investor / partner   | "Why is this defensible, and why now?" (THIS DOC)        |

The clinic one-pager leads with a sample audit. This one leads with
the category, the TAM, the moat, and the ask.

---

## 1. Layout (8.5" × 11", portrait, one page)

The single page is divided into a 6-row × 2-column grid:

```
   ┌──────────────────────────────────────────────┐
   │  Row 1 — Header: logo + one-line positioning │
   ├────────────────────────┬─────────────────────┤
   │  Row 2 — The category  │  The wedge          │
   │  (left, 60%)           │  (right, 40%)       │
   ├────────────────────────┴─────────────────────┤
   │  Row 3 — TAM / SAM / SOM (single bar chart)  │
   ├──────────────────────────────────────────────┤
   │  Row 4 — Revenue model (3 tiers + Enterprise)│
   ├────────────────────────┬─────────────────────┤
   │  Row 5 — Defensibility │  Current traction   │
   │  (left, 50%)           │  (right, 50%)       │
   ├────────────────────────┴─────────────────────┤
   │  Row 6 — The ask + contact                  │
   └──────────────────────────────────────────────┘
```

Design notes for production:

- **Brand color background** (`primary-700` `#0F766E`) on row 1
  only. Rows 2-6 are light (`surface-light` `#F8FAFC`).
- **Type**: Inter (UI) + IBM Plex Mono (numerals in the bar chart).
- **One page, no exceptions.** If a section doesn't fit, it gets
  cut, not continued on page 2.

## 2. Row 1 — Header

> **Zorva** — Pre-submit audit for AHCIP, built on a curated, version-pinned
> rule library.

A 6-word tagline sits under the logo. No sub-headline. The reader
should be able to explain the company to someone else after 10
seconds of looking at the page.

## 3. Row 2 — The category & the wedge

**Left (60%):**

> **The category.** Pre-submit coding audit — read the clinical note,
> read the billed claim, surface what the biller missed before the
> claim goes to the payer. Adjacent to but distinct from coding
> assistance (the biller uses it to code from scratch) and from
> post-pay audit (the payer uses it to recover money). Pre-submit
> audit is the one that runs **before** the money is at risk.

**Right (40%):**

> **Our wedge.** AHCIP, the Alberta schedule of medical benefits,
> is one of the most complex provincial fee schedules in North
> America. We picked it because (a) it's a single-region start
> which keeps the rule library tractable, and (b) primary-care
> clinics in Alberta bill on AHCIP and have the worst modifier-25
> capture rate in the country (~38%, vs ~71% in Ontario).

## 4. Row 3 — TAM / SAM / SOM

A single horizontal bar chart, three rows, light grey background,
no gridlines. Source for each number cited in a 6pt footnote.

| Tier   | Value          | Definition                                        | Source            |
|--------|----------------|---------------------------------------------------|-------------------|
| TAM    | $4.8B ARR      | US + Canadian primary-care billing software spend | KLAS / HIMSS 2025 |
| SAM    | $620M ARR      | Canada primary-care billing software              | Canada Health Infoway 2025 |
| SOM    | $42M ARR       | Alberta primary-care clinics (5,800 clinics × ~$7.2k avg) | Alberta Health practitioner registry 2026 |

The TAM number is large and probably optimistic. The SOM number is
the one we underwrite — a single-region, single-modality start.
Investors will look at SOM, not TAM.

## 5. Row 4 — Revenue model

Three tiers + an Enterprise band. CAD pricing. Each tier carries
the claim-volume band and the average revenue per clinic per
month.

| Tier            | Claim band / month | Price (CAD) | Notes                           |
|-----------------|--------------------|-------------|---------------------------------|
| Solo            | < 500 claims       | $499 / mo   | Self-serve, no onboarding call  |
| Practice        | 500–1,500 claims   | $1,499 / mo | Most clinics land here          |
| Group           | 1,500–3,000 claims | $2,999 / mo | Multi-clinic, shared dashboard  |
| Enterprise      | 3,000+ claims      | Talk to us  | Custom contract, on-prem option |

**Why flat-fee matters (single line, in bold):** a percentage of
recovered revenue would put us inside the AKS anti-kickback safe
harbor, which is a regulatory cliff we are deliberately avoiding.
The flat-fee model is also the one that closes fastest with clinic
CFOs because it maps to their existing SaaS line item.

## 6. Row 5 — Defensibility (left) & traction (right)

**Left (50%):**

> **Why this is defensible.**
>
> 1. **The rule library** — a curated, version-pinned set of AHCIP
>    + SOMB rules, updated monthly by a billing-ops contractor. The
>    library is the moat; the LLM is interchangeable.
> 2. **Customer data gravity** — once a clinic's findings history
>    is in Zorva, the workflow cost of switching is high. We have
>    export-to-CSV (no lock-in by force), but the audit history is
>    the real switching cost.
> 3. **Regulatory alignment** — HIA, PIPEDA, HIPAA, and the
>    Washington My Health My Data Act. New entrants can replicate
>    the LLM wrapper in a quarter; they cannot replicate the
>    compliance posture in a year.

**Right (50%):**

> **Current traction (as of 2026-06-22).**
>
> - **8 clinics** in 60-day pilots (3 Alberta family medicine, 2
>   Alberta cardiology, 1 Alberta dermatology, 2 BC internal
>   medicine).
> - **$172k ARR** committed across the pilots (1 Practice tier,
>   4 Solo tiers, 3 Group tiers).
> - **38% modifier-25 capture rate lift** on average across the
>   8 pilots vs the 90-day pre-pilot baseline.
> - **<1% false-positive rate** on HIGH-severity findings in the
>   v12 auditor (measured against a held-out AHCIP validation set
>   of 240 encounters).
> - **NPS**: not yet measured (pilot cohort is too small).

## 7. Row 6 — The ask + contact

**For investors:** "We are raising a $3.5M seed to (a) ship the
self-serve Solo tier, (b) expand from AHCIP to two additional
provincial fee schedules, (c) hire a head of security to take us
to SOC 2 Type II. Lead introduction: maya@zorva.health."

**For partners:** "We work with two channels today — independent
billing services (reseller) and clinic-management software vendors
(embedded integration). If you are either, we'd like to talk.
Partner introduction: maya@zorva.health."

A single email address on the page — not two. The reader should
not have to choose between "press@" and "partners@" and "investors@".
All three route to the founder; she triages.

## 8. Production checklist

- [ ] All four numerical claims in section 6 are sourced and
      footnoted.
- [ ] The TAM / SAM / SOM numbers are re-verified within 30 days
      of the PDF being sent to an investor. (The Alberta clinic
      count in particular changes quarterly.)
- [ ] The pricing tiers match `getPricingConfig()` in
      `apps/portal/src/lib/pricing.ts` exactly. (If the env-driven
      config drifts from the one-pager, the one-pager loses.)
- [ ] PDF is < 250 KB (most investors open it on a phone first).
- [ ] PDF is signed with a real cryptographic signature (a
      DocuSign envelope is acceptable for v1).

## 9. What this doc is NOT

- It is not the data room. The data room is a separate Notion
  page sent under NDA after a qualified intro call.
- It is not the term sheet. The term sheet is the term sheet.
- It is not the clinic pitch. Do not send this to a clinic
  billing lead — the section they care about ("Will it catch real
  misses on my claims?") is not on this page at all.