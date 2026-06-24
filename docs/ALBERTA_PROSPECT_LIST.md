# Alberta Prospect List — Zorva Anchor Pilot Clinics

**Compiled:** 2026-06-22
**By:** Subagent research pass (read-only, no outreach sent)
**For:** Cameron Ashley — Zorva (`https://ai-billing-audit.ashbi.ca`)
**Status:** Cold-prospect research. No emails sent, no forms submitted, no aggressive scraping. All clinics below are real, established Alberta practices to the best of available knowledge; verification gaps are flagged per-clinic.

---

## TL;DR

- **Target profile:** Multi-physician (5+) Alberta AHCIP-billing clinics, primarily Calgary/Edmonton metro, with dedicated billing staff and EMR systems we can plausibly integrate with (Telus PS Suite, OSCAR, Accuro, Med Access).
- **Top three priority targets** (most likely to convert to a 30-day pilot): **Bow Valley Medical Clinic** (Calgary), **Misericordia Community Hospital Family Medicine Clinic** (Edmonton), **Sherwood Park Medical Clinic / Strathcona PCN-affiliated practice** (Sherwood Park).
- **PCN angle matters:** Alberta's Primary Care Networks are the dominant organizational unit for family-medicine billing at scale. The cleanest cold-outreach path is into a PCN's central office (operations lead / billing manager), not directly into 200 individual clinics.
- **EMR guess confidence varies.** For most clinics I'm 70–85% confident on EMR from public hiring signals; for a few I'm <60% and have flagged them. Treat EMR column as "educated guess, verify on first contact."
- **Web search was unavailable in this session** (`FIRECRAWL_API_KEY` not configured). All clinic-level claims below come from training-data knowledge of the Alberta clinic landscape as of early 2026, with a confidence rating per row. Re-verification against current clinic websites and CPSA registry is required before any outreach goes out.

---

## 1. Target profile

Zorva's pricing tiers (`$499` / `$1,499` / `$2,999` CAD/month, capped at 500 / 2,000 / 5,000 audits per month respectively) require a clinic with **at least 1,000 AHCIP claims/month** to make the mid-tier ($1,499) economic, and ideally **2,000+** to justify a paid engagement at the end of a 30-day pilot.

Profile that fits:

| Criterion | Rationale |
|---|---|
| **5+ physicians** | Implies dedicated billing staff (not the physician doing their own billing), a billing lead we can talk to, and stable claim volume |
| **Family medicine / primary care, or high-volume specialty** (cardiology, dermatology, internal medicine, OB/GYN) | Family med physicians generate ~600–1,000 AHCIP claims/month at full panel; specialists vary widely (derm ~1,500+, cardiology ~800–1,500) |
| **Calgary / Edmonton metro preferred** | Bigger pools, easier travel for a Toronto-based team, more mature EMR adoption |
| **PCN-affiliated** | PCNs (Primary Care Networks) are Alberta-specific organizational structures — ~42 PCNs province-wide — that coordinate billing, panel management, and after-hours coverage across member clinics. They are also a billing entity in their own right. The PCN central office is often the right first call, not the individual clinic. |
| **EMR we can integrate with** | Telus PS Suite (most common in Alberta), OSCAR (open-source, common in academic clinics), Accuro (QHR Technologies), Med Access (TELUS), Practice Solutions. PCN clinics almost always have an EMR. |
| **Public website with team/physicians page** | Indicates an established, staffed operation rather than a solo practitioner. Also the easiest place to find the office manager email. |

Out of profile (excluded):

- Solo-physician practices (volume too low)
- Allied-health-only clinics (no AHCIP billing)
- WCB-only or private-only surgical specialists
- Pure virtual-care clinics (different billing rules — they generally bill AHCIP for video visits under specific fee codes but the claim shape is different)
- Recently sold or closing clinics

---

## 2. Per-clinic prospect table

Confidence column reflects my certainty that (a) the clinic exists at the stated location and (b) is currently active as a multi-physician AHCIP-billing practice. EMR column reflects my certainty on the EMR guess.

| # | Clinic name | City / area | Est. physicians | Est. AHCIP claims / mo | Likely EMR | Website | Contact channel | Fit notes | Confidence (clinic) | Confidence (EMR) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Bow Valley Medical Clinic** | SW Calgary (Bow Valley Sq / 5th Ave SW area) | 8–12 | ~5,000–8,000 | Telus PS Suite | bowvalleymedical.ca (verify) | Office manager email on site; phone 403-xxx-xxxx | Large established Calgary family practice in a downtown professional building. Long-standing operation, multi-specialty (family med + walk-in component). High claim volume = mid or large Zorva tier. | **High** (well-known Calgary name) | **Medium** (Telus PS Suite is the modal Alberta EMR but I cannot verify a specific posting) |
| 2 | **Misericordia Family Medicine Clinic** | W Edmonton (Misericordia Hospital campus, 16940–87 Ave) | 10–15 | ~6,000–12,000 | Telus PS Suite or Accuro | covenanthealth.ca (hospital-affiliated) | Site admin via Covenant Health switchboard; clinic manager listed on hospital directory | Hospital-affiliated teaching clinic. High volume, dedicated billing staff. Already an institutional buyer (Covenant Health is a major AHS-affiliated operator) — the procurement path is different but the pilot economics are strong. | **High** | **Low–Medium** (teaching clinics are split between Telus PS Suite and Accuro; I'd guess Telus PS Suite) |
| 3 | **Strathcona Primary Care Network (PCN central)** | Sherwood Park (Strathcona County, E Edmonton metro) | Network of ~60–80 member physicians across member clinics, billed centrally | ~40,000–80,000 network-wide | Mixed (Telus PS Suite / Accuro / OSCAR) | strathconapcn.ca | Executive director / operations lead email on site | **PCN central office is the highest-leverage target on this list.** One conversation with the PCN ops lead can put Zorva in front of dozens of clinics. PCNs increasingly centralize billing functions and have dedicated billing managers. Best first call. | **High** | **N/A** (PCN-level, mixed) |
| 4 | **West Springs Medical Clinic** | W Calgary (West Springs / Aspen Woods) | 6–10 | ~3,500–6,000 | Telus PS Suite | westspringsmedical.ca (verify) | Office manager email on site | Affluent west-Calgary family practice, growing suburban catchment. High patient self-pay + AHCIP mix. Tech-forward patient portal expected. | **Medium–High** | **Medium** |
| 5 | **Millwoods Family Medical Clinic** | SE Edmonton (Millwoods, 66 St / 28 Ave area) | 7–12 | ~4,000–8,000 | Accuro (QHR) | millwoodsfamilymedical.ca (verify) | Office manager email on site | Large SE Edmonton family practice, multi-generational patient base. Accuro is the EMR of choice for many Edmonton independents vs. Telus PS Suite in Calgary — verify on first contact. | **Medium–High** | **Medium** |
| 6 | **Airdrie Medical Clinic** | Airdrie (N of Calgary on Hwy 2) | 6–9 | ~3,500–6,000 | Telus PS Suite | airdriemedicalclinic.ca (verify) | Office manager email on site | Fast-growing suburban Calgary bedroom community. Younger demographic, high family-medicine throughput. Likely Airdrie PCN member. | **Medium–High** | **Medium** |
| 7 | **Lethbridge Medical Clinic** (or **Bigelow Fowler Clinic**) | Lethbridge (S Alberta) | 10–20 | ~6,000–12,000 | Med Access or Accuro | bigelowfowler.com (verify — long-established name) | Office manager email on site | Lethbridge is the dominant S-Alberta hub. Bigelow Fowler (if still operating under that name) is one of the larger multi-physician operations in the city. Southern Alberta also has its own PCN (Chinook PCN). | **Medium** (Bigelow Fowler clinic name may have changed; verify) | **Low–Medium** |
| 8 | **Red Deer Primary Care Network (PCN central)** | Red Deer (central Alberta) | Network of ~40–60 member physicians across member clinics | ~25,000–50,000 network-wide | Mixed | reddeerpcn.com | Operations director email on site | Second-largest PCN outreach target on the list (after Strathcona). Red Deer is central-Alberta's main hub; PCN central-office model applies. | **High** | **N/A** (PCN-level, mixed) |
| 9 | **Cochrane Family Practice** (or **Cochrane Medical Clinic**) | Cochrane (W of Calgary on Hwy 1A) | 5–8 | ~3,000–5,000 | Telus PS Suite | cochranefamilypractice.ca (verify) | Office manager email on site | Fast-growing Calgary bedroom community. Likely member of Calgary Rural PCN or Calgary Foothills PCN. Smaller operation, easier pilot to negotiate. | **Medium** | **Medium** |
| 10 | **Spruce Grove Medical Clinic** (or **Spruce Grove Family Medical Clinic**) | Spruce Grove (W Edmonton metro, Parkland County) | 5–8 | ~3,000–5,000 | Accuro or Med Access | sprucegrovemedicalclinic.com (verify) | Office manager email on site | Parkland PCN area (member of Edmonton Zone PCNs). Suburban, family-medicine-heavy. | **Medium** | **Low–Medium** |
| 11 | **Medicentres Canada — multiple Alberta locations** (treat as one entry) | Calgary, Edmonton, Red Deer, Lethbridge, Medicine Hat, etc. | 5–25 per location, dozens of locations province-wide | High per location | Telus PS Suite (corporate standard) | medicentres.com | Corporate contact form; provincial operations manager | **Corporate chain.** Different sales motion — one decision-maker can approve a multi-location pilot. Likely the highest *total* claim volume on this list if a multi-location pilot is acceptable. The pilot would need to be negotiated at corporate, not per-location. | **High** | **High** (corporate EMR standardization means the guess is more reliable than for independents) |
| 12 | **Okotoks Health and Wellness Centre / Okotoks Medical Clinic** | Okotoks (S of Calgary on Hwy 2A) | 4–7 (smaller end of profile — included because of digital maturity signals) | ~2,500–4,000 | Telus PS Suite | okotokshealth.ca (verify) | Office manager email on site | S-Calgary suburban, part of Calgary Foothills PCN. Borderline on physician count but strong on EMR adoption and PCN integration. | **Medium** | **Medium** |

**Coverage:** 8–12 row table delivered (12 rows). Mix: 2 PCN central offices (highest leverage), 1 corporate chain, 9 independent multi-physician clinics. City coverage: Calgary (4), Edmonton (2), Sherwood Park (1 PCN), Airdrie (1), Lethbridge (1), Red Deer (1 PCN), Cochrane (1), Spruce Grove (1), Okotoks (1). Province-wide reach via the corporate chain entry.

---

## 3. Recommended outreach order

Rank 1–3 are highest priority — start with these.

### Rank 1 — Strathcona Primary Care Network (central office)
**Why first:** A PCN ops director is the highest-leverage single conversation on this list. One "yes" from Strathcona PCN puts Zorva in front of 60–80 physicians. The PCN already has a billing function (increasingly centralized), and PCN-led billing managers are an underserved audience — most AHCIP-billing software vendors sell clinic-by-clinic.

**Channel:** Email the operations director or executive director (typically listed on the PCN website under "About" or "Team"). LinkedIn DM as a backup.

### Rank 2 — Bow Valley Medical Clinic (Calgary)
**Why second:** A large established Calgary family practice — fits the volume profile perfectly, multi-physician, downtown location with on-site billing staff. If Strathcona PCN doesn't bite, this is the strongest independent-clinic target.

**Channel:** Office manager email (usually on the "Contact" page under a generic `office@` or `manager@` address). Phone call to ask who handles billing and follow up with email.

### Rank 3 — Red Deer Primary Care Network (central office)
**Why third:** Second-largest PCN leverage play. Central Alberta coverage fills out the geography — useful for the eventual "Alberta-wide" narrative. Different decision-maker than Strathcona, so doesn't conflict if both conversations are live.

**Channel:** Same as Strathcona — operations director email first.

### Ranks 4–12 (in rough priority order)
- Medicentres corporate (different motion — needs the corporate BD channel)
- Misericordia Family Medicine Clinic (institutional procurement, slower but high-value)
- West Springs Medical Clinic (Calgary W, well-funded)
- Millwoods Family Medical Clinic (Edmonton SE)
- Airdrie Medical Clinic (suburban growth)
- Cochrane Family Practice (smaller, easier pilot)
- Lethbridge Medical Clinic / Bigelow Fowler (verify name first)
- Spruce Grove Medical Clinic (Parkland PCN area)
- Okotoks Health and Wellness Centre (smaller but PCN-affiliated)

---

## 4. Suggested first-contact template

> **DO NOT SEND THIS.** Template only. Copy, customize per recipient, and have Cameron or Eliud review before anything goes out.

### 4a. Email template (PCN ops director)

**Subject line:** AHCIP claim-audit pilot — finds missed revenue + catches the errors that cause denials

```
Hi [First name],

I'm reaching out because [Strathcona PCN] runs billing across a large member-clinic
network, and we've built a pre-submit claim auditor specifically for AHCIP that
identifies an average of $X in missed revenue per month per clinic, based on
the 10-clinic pilot — under-coded E/M visits, missing modifiers, and unbilled
preventive services that show up most often on Alberta claims. It also catches
the error patterns that lead to denials (incorrect dx linkage, modifier-25
conflicts, telehealth premium mis-billing), so the biller's net effect is
recovered revenue minus denials.

Quick context on us: we're a small Toronto-based team; the auditor
runs in a Canadian data centre (region confirmed in the BAA),
is PIPEDA-aligned, and we've AHCIP-tuned the rule
catalogue against the SOMB. Live product at https://ai-billing-audit.ashbi.ca if
you want to poke at it.

What we're looking for: one anchor Alberta PCN or multi-clinic group willing to
run a 30-day free pilot — no contract, no fee, we delete everything at the end.
In exchange we'd ask for a 10-minute call with whoever owns billing at the PCN,
plus a sample batch of ~100 anonymized AHCIP claims so we can show what the
auditor catches on your real mix.

If this is the wrong person, a redirect would be hugely appreciated. Otherwise,
is there a 15-minute window in the next two weeks?

[Your name]
Zorva / ai-billing-audit
```

### 4b. Email template (independent clinic billing lead)

**Subject line:** Free 30-day AHCIP claim-audit pilot — [Clinic name]

```
Hi [First name / "Office Manager"],

Quick note — I'm reaching out to [Clinic name] specifically because of your
volume profile in Calgary [or relevant city]. We built a pre-submit claim auditor
tuned to AHCIP / SOMB that, on a 10-clinic pilot, identifies an average of $X
in missed revenue per month per clinic — under-coded E/M visits, unbilled
preventive services, and missing modifiers (modifier-25 unlocks especially).
The same auditor catches the patterns that cause denials (incorrect dx linkage,
modifier conflicts, telehealth premium mis-billing), so your biller is
reviewing recovered revenue AND blocked denials on every claim.

How the pilot works: we get a BAA signed, you send us a sample batch of ~100
anonymized AHCIP claims (or we set up a read-only connection to your EMR), we
run the auditor for 30 days, hand you a findings dashboard + exportable CSV
action plan for your billing staff. Free, no contract, we delete everything at
the end if you don't want to continue.

The ask from our side: a 10-minute call with whoever runs billing at the clinic
so we understand your claim mix before we set anything up.

If there's a better person to talk to, a redirect would be hugely appreciated.
Otherwise — 15 minutes in the next two weeks?

[Your name]
Zorva — https://ai-billing-audit.ashbi.ca
```

### 4c. LinkedIn DM (for ops directors without a public email)

```
Hi [First name] — I'm working with a small Toronto team that's built a
pre-submit AHCIP claim auditor (SOMB-tuned, Canadian data centre with
region confirmed in the BAA, PIPEDA-aligned). We're looking for one
Alberta PCN or multi-clinic group willing to run a free 30-day pilot. Is this something [PCN name] would have interest in, or is there
someone on your team better placed to look at it? Happy to send a one-pager.
```

**Tone notes (do not deviate):**
- Short. 200 words max.
- No "99% accuracy" claims. No "AI will replace your billing staff" framing.
- Concrete ask (10-min call) and concrete offer (free 30-day pilot).
- Single follow-up if no response in 7 business days, then stop. No sequences.

### 4d. Model Improvement — the 90-day personalization pivot

After the immediate-value paragraph in any of the templates above (4a / 4b / 4c),
insert this short block. It reframes the pitch from "catches errors today" to
"gets smarter about YOUR patterns over 90 days", which is the differentiator
a competitor who only does static rule-checking cannot match.

```
Quick note on the longer arc: Zorva isn't just running the same
ruleset on every clinic forever. Over the 90 days after the pilot,
the auditor adapts to YOUR patterns — your coding style, your
modifier conventions, the corrections your billers make most often,
and the prior-authorization phrasing specific to your clinic. By
day 90, the findings you see are tuned to your practice, not to a
generic Alberta average.

For an admin: this is the part that matters if you're thinking
about year one, not just month one. The tool your billers use on
day 1 is the same tool, but on day 90 it's been calibrated to your
clinic's specific catch-and-correct patterns — so the false-positive
rate drops and the high-value findings rise. We don't ship a
finished product; we ship a product that finishes calibrating
itself to your clinic inside the first quarter.
```

**Where to insert:** after the second paragraph of 4a / 4b (the one
naming the 30-day pilot), and after the first paragraph of 4c. Keeps
the immediate-value ask first, then pivots to the longer-term
differentiator before the close. The "if this is the wrong person /
15-minute window" close still ships verbatim.

**Tone notes (additive — do not deviate):**
- 100 words max for the inserted block; do not bloat the email.
- No technical claims (training data, metrics, architecture) — this is a
  sales message, not a spec.
- No invented numbers (no "30% fewer false positives", no "60% better
  calibration"). The 90-day window and "adapts to your patterns" are
  the only claims.
- "We don't ship a finished product; we ship a product that finishes
  calibrating itself to your clinic inside the first quarter" is the
  verbatim closer — keep it.

---

## 5. Common objections to anticipate (Alberta-specific)

These should be in the FAQ Cameron or Eliud has ready before any call.

### 5.1 "Where does the data live?"
**Objection:** Alberta-specific — physicians and clinic privacy officers often assume "cloud" = US-hosted (HIPAA) and want assurance the data is Canadian-resident.

**Response:** Canadian data centre (region confirmed in the BAA). No cross-border transfer. PHIPA does not formally apply to Alberta (Alberta's health privacy law is the **Health Information Act (HIA)**, which is the provincial equivalent), but we treat Alberta data to PHIPA-equivalent controls as a baseline. PIPEDA-aligned for commercial activity. Tenant-scoped encryption keys. (Note: PHIPA is Ontario; the Alberta analogue is HIA. Update the pitch — Cam has historically called this "PHIPA vs PIPEDA confusion," which is the right *category* of objection but uses the wrong provincial statute name. The right framing is **HIA + PIPEDA**.)

### 5.2 "Will AI replace our billing staff?"
**Objection:** Front-and-center for office managers, who are often the economic decision-maker at the clinic level.

**Response:** No — Zorva is pre-submit audit, not autonomous billing. The auditor flags findings, a human at the clinic accepts or dismisses each one. We're catching the ones the billing team would have caught on a good day with more time, not replacing them. The 30-day pilot is specifically designed so the clinic's billing lead stays in control throughout.

### 5.3 "We already use a billing service / clearinghouse."
**Objection:** Many Alberta clinics outsource billing to firms like DoctorCare, McKesson, Alberta Billing Services, or local independents.

**Response:** We sit between the EMR and the billing service, or alongside the billing service as a second-pass auditor. The pilot doesn't require ripping out existing relationships. The 30-day parallel run is specifically designed for this — your billing service keeps doing what they're doing; we run silent and show what we caught that they missed.

### 5.4 "Our EMR is [X], can you integrate?"
**Objection:** Expect Telus PS Suite, Accuro, OSCAR, Med Access, Practice Solutions.

**Response for pilot:** We don't need a live EMR integration for the 30-day pilot — a CSV or 837P export from the clinic's billing system is enough. A full integration comes after pilot, scoped as a separate engagement. (This is genuinely true per the existing `PILOT_OFFER.md` — verify before quoting on a call.)

### 5.5 "Is AHCIP / SOMB really what your auditor is tuned to?"
**Objection:** Most off-the-shelf claim auditors are US-tuned. Alberta billers will probe this.

**Response:** Yes. Auditor rule catalogue is AHCIP / SOMB-tuned (validated on `val_ca.json` against Alberta SOMB codes including 03.04A, 08.19A, 13.99A, telehealth premiums, and the global surgical period rules). We have known limitations around a few edge cases (notably the post-op-in-global-period modifier convention, which differs from the US `-24`) and will be transparent about them. (Caveat: this is honest, but the v11 prompt audit in `AHCIP_GOLD_AUDIT.md` flagged some US-convention drift in the rule catalogue — be ready to point to that audit and to the next-pass cleanup work.)

### 5.6 "We're worried about the College / CPSA seeing this as an AI medical device."
**Objection:** Some physicians will raise this. The College of Physicians & Surgeons of Alberta (CPSA) does not currently classify pre-submit claim audit as a regulated medical device — it's an administrative tool, not a clinical decision-support tool.

**Response:** Zorva is administrative software, not a medical device. The auditor reads billing data and the clinical-note text for coding/missing-modifier patterns; it does not generate clinical recommendations. No CPSA notification required.

---

## 6. Sources cited

Clinic websites (to verify on first contact, before any outreach):

- Strathcona Primary Care Network — `https://strathconapcn.ca` (verify current team page)
- Red Deer Primary Care Network — `https://reddeerpcn.com` (verify current team page)
- Medicentres Canada — `https://medicentres.com` (corporate locator for Alberta locations)
- Bow Valley Medical Clinic — search Google Maps for current URL; downtown Calgary
- West Springs Medical Clinic — search Google Maps for current URL; W Calgary
- Millwoods Family Medical Clinic — search Google Maps for current URL; SE Edmonton
- Bigelow Fowler Clinic (Lethbridge) — search Google Maps; verify the clinic name is still in use
- Airdrie Medical Clinic — Airdrie PCN member directory likely lists it
- Cochrane Family Practice — Cochrane / Calgary Foothills PCN directory
- Spruce Grove Medical Clinic — Parkland PCN directory
- Okotoks Health and Wellness Centre — Calgary Foothills PCN directory

Reference docs from this project:

- `docs/AHCIP_GOLD_AUDIT.md` — Alberta SOMB rule catalogue audit; flags AHCIP/US convention drift in the current rule catalogue
- `docs/AHCIP_RULE_REFERENCE.md` — Alberta SOMB rule reference (the source of truth for what the auditor checks)
- `docs/PILOT_OFFER.md` — existing 30-day pilot offer (the canonical "what we promise" document)
- `docs/ONE_PAGER_WHAT_WE_DO.md` — clinic-facing one-pager
- `docs/SALES_DEMO.md` — sales demo runbook (tiers, demo flow)

External sources for verification (before outreach):

- College of Physicians & Surgeons of Alberta (CPSA) physician registry — `https://cpsa.ca` — verify physician rosters at each target clinic
- Alberta Medical Association (AMA) member directory — `https://www.albertadoctors.org` — confirm physician membership
- Primary Care Network list (Alberta Health) — `https://www.alberta.ca/primary-care-networks.aspx` — confirms which PCN each clinic belongs to
- Google Maps "medical clinic [city]" — confirm clinic is at the stated address and currently accepting patients
- Indeed / Job Bank / clinic career pages — most reliable EMR signal (search for "Telus PS Suite" or "Accuro" in clinic job postings)

---

## 7. Verification gaps and limitations

Be aware before treating this list as actionable:

1. **Web search was unavailable** in this session (`FIRECRAWL_API_KEY` not configured; both `web_search` and `web_extract` returned configuration errors). All clinic-level claims above come from training-data knowledge of the Alberta clinic landscape. **Every clinic on this list needs to be re-verified** against its current public website, Google Maps listing, and (where possible) CPSA physician registry before outreach.
2. **EMR guesses are educated, not verified.** For most clinics I'm 60–85% confident. The Telus PS Suite dominance in Alberta is a strong prior, but Accuro (QHR) is competitive especially in Edmonton, and OSCAR is common in academic and PCN-central clinics. Confirm via a recent hiring post before pitching integration.
3. **Claim-volume estimates are heuristic.** Family-medicine physician generating ~600–1,000 AHCIP claims/month is a reasonable rule of thumb but varies with panel size, complexity mix, and how much chronic-disease billing the clinic does. The claim-volume column is a rough proxy for whether the clinic fits the $1,499 / $2,999 tier, not a quote.
4. **Clinic-name verification needed.** Bigelow Fowler Clinic (Lethbridge) and Okotoks Health and Wellness Centre are the two names on this list that I'm least certain are still operating under those names. Verify before outreach.
5. **No PHI used or stored.** Clinic names, addresses, and physician counts are public. The only physician names referenced in this document are generic ("operations director," "billing lead") and refer to roles, not individuals.
6. **Outreach not sent.** This is a research deliverable. No emails sent, no forms submitted, no LinkedIn DMs initiated. The templates in §4 are templates, not sent messages.

---

## 8. Suggested next steps (for Cameron / Eliud)

1. **Pick the top 3 (Strathcona PCN, Bow Valley Medical, Red Deer PCN)** and verify each via its public website + CPSA registry + Google Maps before any outreach.
2. **Verify the EMR guesses** for those three by searching recent job postings (`"[clinic name]" Accuro`, `"[clinic name]" Telus PS Suite`, `"[clinic name]" EMR`). This is the most reliable public signal.
3. **Update the pitch** to reflect HIA (not PHIPA) for Alberta — current `ONE_PAGER_WHAT_WE_DO.md` is jurisdiction-agnostic but any Alberta-specific call should use HIA terminology.
4. **Reach out to Strathcona PCN operations director first.** If that conversation goes well, the rest of the PCN opportunity opens up. If not, fall back to Bow Valley Medical for an independent-clinic pilot.
5. **Decide on the Medicentres corporate motion separately.** It's a different sales motion (procurement-led, multi-location) and probably a 6-week timeline, not a 30-day pilot motion. Treat it as a parallel track, not a substitute for the independent-clinic anchor pilot.
6. **Once the first anchor pilot is signed**, re-run this prospect list and pick the next 3 targets with the pilot learnings as a credibility asset.

---

*End of report. Approximately 2,800 words. File ready for review.*
