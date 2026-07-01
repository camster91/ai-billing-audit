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

P11 reality-check (Cameron, 2026-07-01): the previous numbers
(TAM=$4.8B, SAM=$620M, SOM=$42M ARR) were taken from KLAS / HIMSS
2025 and Canada Health Infoway 2025 estimates cited in the
original draft of this doc, but neither source URL was captured
and neither number was re-verified against the live dataset. The
Alberta practitioner registry figure (5,800 clinics × ~$7.2k avg)
was a back-of-envelope calculation, not a registry extract.

Until those sources are verified AND the registry count is
re-pulled, the section reads:

| Tier   | Value (PLACEHOLDER) | Definition                                        | Source            |
|--------|---------------------|---------------------------------------------------|-------------------|
| TAM    | TBD                 | US + Canadian primary-care billing software spend | NEEDS SOURCE — KLAS / HIMSS 2025 cite unverified |
| SAM    | TBD                 | Canada primary-care billing software              | NEEDS SOURCE — Canada Health Infoway 2025 cite unverified |
| SOM    | TBD                 | Alberta primary-care clinics (N clinics × ~$Xk avg) | NEEDS SOURCE — Alberta Health practitioner registry extract |

If sending the PDF before these are sourced, replace the row with
a single line: "Pre-revenue; market sizing deferred until first
pilot completes and the validated SOM is grounded in actual
pricing × confirmed pipeline."

The SOM number, once sourced, is the one we underwrite — a
single-region, single-modality start. Investors will look at SOM,
not TAM.

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

> **Current traction (as of 2026-07-01).**
>
> P11 reality-check (Cameron, 2026-07-01): the previous version
> of this section contained fabricated numbers — "8 clinics in
> 60-day pilots," "$172k ARR committed," "38% modifier-25 lift,"
> and a "<1% false-positive rate on 240 encounters" that did not
> match the actual v12 benchmark (P=0.647, R=0.846, F1=0.690
> on a 10-encounter / 13-finding validation set, see
> `runs/recall/v12_ahcip_clean.json`). The founder also was
> listed as `maya@zorva.health` — a placeholder name from an
> earlier draft, never a real person.
>
> Honest current state as of 2026-07-01:
>
> - **0 clinics in pilot** — the first 60-day no-cost pilot is
>   scoped (privacy-officer brief at `docs/PRIVACY_OFFICER_BRIEF.md`,
>   cold-outreach queue ready) but has not yet started.
> - **v12 auditor benchmark**: F1=0.690 micro on the cleaned
>   AHCIP validation set (10 encounters, 13 gold findings;
>   P=0.647, R=0.846). The shadow runner on the full 19-encounter
>   / 31-finding val set is at `runs/shadow/val_ca-20260630T193918.md`
>   and finds ~$602 SOMB-anchored impact on a single shadow run.
> - **NPS**: not yet measured.
> - **Total ARR**: $0 committed. Pre-revenue.
>
> Treat this section as a placeholder to populate only after the
> first pilot signs. Do NOT send the PDF with the placeholder text
> below — the "Founder, Zorva" line at the bottom is the only
> named person, and the contact email is the founder's real
> address, not the placeholder used in earlier drafts.

## 7. Row 6 — The ask + contact

**For investors:** "Pre-revenue. Currently raising a friends-and-
family round to fund the first 60-day pilot cycle (lawyer review
of the HIA IMA template, one full-time founder, infrastructure).
Lead introduction: cameron@ashbi.ca."

**For partners:** "We work with two channels today — independent
billing services (reseller) and clinic-management software vendors
(embedded integration). If you are either, we'd like to talk.
Partner introduction: cameron@ashbi.ca."

A single email address on the page — not two. The reader should
not have to choose between "press@" and "partners@" and "investors@".
All three route to the founder; he triages.

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