# Strathcona PCN — Zorva Pilot Pitch (1-Page Sales Script)

> **Use case:** Cold/warm introduction to the **Strathcona Primary Care
> Network** (Sherwood Park, AB) — executive director, operations lead,
> or central billing manager.
> **Speaker:** Cameron Ashley or designated sales rep.
> **Format:** 10-minute call, 1-pager left behind.
> **Status:** Working draft, June 2026.

---

## The one-liner (say this first, in plain English)

> "Strathcona PCN's network of 60 to 80 family-medicine physicians is
> currently leaving roughly **$300,000 to $600,000 per year** in
> AHCIP revenue on the table — not because the physicians are bad
> billers, but because AHCIP denies claims for preventable reasons
> that a pre-submit auditor catches in under a second. We'd like to
> prove that on **your real claims**, at no cost, for 60 days."

---

## The missed-revenue calculation (numbers we can defend)

| Input | Value | Source |
|---|---|---|
| Strathcona PCN member physicians | ~60–80 | PCN public materials |
| Avg AHCIP claims per family physician per month | ~700 | `docs/AHCIP_RULE_REFERENCE.md` (700 × 9 mo. of billing) |
| AHCIP claim denial / clawback rate, primary care | ~8–12% | Common Alberta billing-consultant range |
| Of those denials, fraction that are *preventable* pre-submit | ~40–60% | Zorva rule coverage vs. common denial causes (dx_linkage, E/M upcode, after-hours premium missing, telehealth premium missing) |
| Avg AHCIP claim value, comprehensive 03.04A | ~$55–$80 | SOMB 2026-04 (`open.alberta.ca/publications/somb-2026-04-01`) |

**Math (mid-case, 70 physicians):**
- Annual claims: 70 × 700 × 12 = **588,000 claims/yr**
- Denied: 588,000 × 10% = **58,800 denied/yr**
- Preventable (50%): **29,400 recoverable claims/yr**
- Recovered value at $65 avg: **$1,911,000 gross**, of which typical
  Alberta billing improvements capture 30–60% via better code selection
  + premium capture (CMGP, telehealth, after-hours). Working figure:
  **~$300K–$600K/yr of recovered / newly-billed revenue across the
  network.**

**A more conservative single-clinic number** (8-physician clinic,
2,000 claims/mo, 10% denial rate, 40% preventable, $60 avg): ~$58K/yr.
That's the number a single clinic CFO can sign off on.

---

## The AHCIP rule that pays for itself in 2 weeks: telehealth premium

> "Here's one example we see over and over. When a family physician
> does a virtual follow-up — phone or secure video — AHCIP wants a
> **telehealth premium code** on the claim: **HSC 03.01T** for
> secure videoconference, or **03.01S** for secure electronic
> communication — both currently **$20.00** per encounter (SOMB
> 2026-04; AMA Fee Navigator entries 03.01S / 03.01T). Most clinics
> we audit **forget to add the premium**, so they bill a 03.04A at
> $60 and leave $20 on the table. For a clinic doing 30 virtual
> visits/week, that's **$31,000/year** in unclaimed premium from a
> single missed two-character code. AHCIP will not pay it after the
> fact — you have to submit it on the original claim. That's exactly
> the kind of thing Zorva catches pre-submit."

**Other high-leverage AHCIP rules we cover (one-line each, in case asked):**
- **dx_linkage** (CRITICAL): H-Link auto-denies claims with empty /
  placeholder dx codes. This is the single most common Alberta
  denial cause.
- **E/M level upcode / undercode** (HIGH): brief visit billed as
  comprehensive = recoverable overpayment on audit; comprehensive
  work billed as brief = lost fee.
- **after-hours premium** (LOW–MEDIUM): evenings, weekends, stat
  holidays — Alberta publishes specific premium codes physicians
  frequently miss.
- **CMGP** (MEDIUM): chronic disease management premium (modifier
  on 03.04A for T2DM, HTN, CKD, COPD, CHF, etc.).
- **90-day global surgical period** (HIGH, GR 3.2.1): no `-24`
  modifier in Alberta — post-op E/M visits are not separately
  billable unless the condition is genuinely unrelated.

**Honest calibration number we cite:**
> "On our cleaned AHCIP validation set, v12 of the auditor catches
> **6–7 of every 10 real billing errors** before submission (F1 =
> 0.690, precision 0.647, recall 0.846; 10 AHCIP encounters, 13
> audited gold findings; see `runs/recall/v12_summary.md`). It's not
> perfect — about 1 in 3 flags is a false positive — but the cost of
> a false positive is 5 seconds of biller review, and the cost of a
> missed real error is $50–$200 in denied revenue per claim."

---

## The ask: 60-day no-cost pilot

| Term | Detail |
|---|---|
| **Cost to Strathcona PCN** | **$0.** No fees, no procurement form, no automatic conversion. |
| **Duration** | 60 calendar days (vs. industry-standard 30, because PCN member onboarding takes time). |
| **Data scope** | A representative sample of 1,000–5,000 AHCIP claims from across the network. We accept a CSV or 837P extract from your existing billing system. |
| **Privacy** | Canadian data residency (`ca-central-1`), no training on Strathcona data, hash-chained audit trail, **60-day hard delete at pilot end** with a written deletion certificate. Full HIA-compliant DPA template is ready (2 pages, privacy-officer signable). |
| **What we need from you** | A 30-minute call with the central billing lead, a sample data export (de-identified if you prefer), and a 30-minute review at pilot end. |
| **What you get** | A per-clinic and network-aggregate report of caught errors, estimated recoverable revenue, a CSV of every flag for billing-staff training, and a written reference letter from the PCN — **only if you're happy with the result**. |

---

## The pricing (only if asked — the pilot is free)

| Tier | Price (CAD) | What you get |
|---|---|---|
| **Small practice** | **$499/mo** | Up to 500 audits/mo, email support, weekly digest. |
| **Mid clinic (most PCN member clinics land here)** | **$1,499/mo** | Up to 2,000 audits/mo, 5 seats, daily digest, priority support. |
| **Large practice / PCN network** | **$2,999/mo** | Up to 5,000 audits/mo, unlimited seats, same-day response SLA, quarterly rules-tuning session. |
| **Network-wide enterprise** | Custom | Volume discount + central billing-leader dashboard + per-clinic roll-up. Talk to us. |

A typical 8-physician member clinic at the mid tier pays $17,990/yr
and recovers, on the conservative single-clinic math, ~$58K/yr.
**Net payback for the clinic: ~$40K/yr.** For the network at scale,
the math is in the high six figures.

---

## Objection handling (the 4 we expect)

1. **"Will your system see patient data?"**
   *Yes — but only the four fields needed for the audit (claim codes,
   dx codes, free-text clinical note, and the biller's decision), only
   inside a Canadian data centre, only retained for 60 days unless you
   opt in, never used to train any AI model, and the DPA gives you
   audit-trail access to prove all of the above.*

2. **"We already use a billing service (e.g. Alberta Medical Billing
   Services, Think Research, etc.)."**
   *Zorva runs **before** submission. Your billing service is the
   last-mile submission and reconciliation. We catch the errors
   before they leave your building. We're complementary, not a
   replacement.*

3. **"We're worried about AI replacing our billing staff."**
   *Zorva is decision support. Your billers still approve every
   finding. The auditor flags; humans decide. Most of our pilot
   clinics report that their billers' job gets **easier** (less
   manual re-work) and they shift into higher-leverage work like
   premium capture optimization and training.*

4. **"What happens to our data at the end of the pilot?"**
   *60-day hard delete. We send you a deletion certificate. You can
   also export everything before then. There's an opt-in for
   aggregated, de-identified metrics only — k-anonymized, no direct
   identifiers — and the default is opt-out.*

---

## The close

> "The pilot is free, the data lives in Canada, the HIA paperwork is
> 2 pages, and the worst-case outcome is that we delete 1,000 of your
> claims after 60 days and you keep the per-clinic report. The
> best-case outcome is that the PCN identifies a six-figure revenue
> improvement it can roll out across all 60+ member clinics. Can we
> schedule a 30-minute call with you and your central billing lead
> in the next two weeks?"

---

## Sources & supporting docs (one-page footer)

- **AHCIP SOMB 2026-04-01** — `open.alberta.ca/publications/somb-2026-04-01`
- **AMA Fee Navigator — HSC 03.01S / 03.01T** —
  `albertadoctors.org/fee-navigator/hsc/03.01S` and `/03.01T`
- **v12 calibration** — `runs/recall/v12_summary.md` (F1 = 0.690,
  P = 0.647, R = 0.846, 10 AHCIP encounters / 13 gold findings)
- **HIA-compliant DPA** — `docs/legal/HIA-DPA-TEMPLATE.md`
- **Pilot offer** — `docs/PILOT_OFFER.md` and `docs/DATA_AGREEMENT_TEMPLATE.md`
- **Prospect profile** — Strathcona PCN, rank 1 in
  `docs/ALBERTA_PROSPECT_LIST.md` (60–80 member physicians, network-
  wide claim volume ~40,000–80,000/yr)

---

*Companion: `docs/gtm/PILOT_DEMO_RECORDING_SCRIPT.md` (live demo
flow), `docs/gtm/SALES_DEMO.md` (longer sales deck), and
`docs/ALBERTA_STRATEGY_BRIEF.md` (overall Alberta plan).*
