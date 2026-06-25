# Ontario / Toronto Prospect List — Zorva Pilot Clinics

> Kanban: t_5e6d959d (E2) on board 'pilot-ready'.
> Compiled: 2026-06-25 (subagent research pass, no outreach sent).
> See `docs/ALBERTA_PROSPECT_LIST.md` for the Alberta equivalent.

## TL;DR

- **Target profile:** Multi-physician (5+) Ontario OHIP-billing clinics,
  primarily Toronto / GTA / Hamilton / Ottawa metros, with dedicated billing
  staff and an EMR we can plausibly integrate with (Telus PS Suite,
  OSCAR, Accuro, Med Access, Practice Solutions).
- **Top three priority targets:**
  1. **St. Michael's Hospital Family Health Team** (Toronto) — large
     academic FHT, multi-site, ~50 physicians, OHIP+ FHO billing.
  2. **Women's College Hospital Family Practice** (Toronto) — academic
     FHT, ~25 physicians, well-known for digital-health adoption.
  3. **Summerville Family Health Team** (Mississauga) — large community
     FHT, ~30 physicians, OHIP billing at scale.
- **FHT angle matters:** Ontario's Family Health Teams are the dominant
  organizational unit for capitation-blended primary care. They're often
  the right first call, not the individual physician.
- **Verification gaps are flagged per clinic.** Web search was unavailable
  in this research pass; verify against CPSO registry + clinic websites
  before any outreach goes out.

## 1. Target profile

Zorva's pricing tiers (`$499` / `$1,499` / `$2,999` CAD/month, capped at
500 / 2,000 / 5,000 audits per month respectively) require a clinic with
at least 1,000 OHIP claims/month to make the mid-tier ($1,499) economic,
and ideally 2,000+ to justify a paid engagement at the end of a 30-day
pilot.

| Criterion | Rationale |
|---|---|
| **5+ physicians** | Implies dedicated billing staff, a billing lead, stable claim volume |
| **Family medicine / primary care, or high-volume specialty** (cardio, derm, IM, OB/GYN) | Family med generates ~600–1,000 OHIP claims/mo at full panel; specialists vary widely |
| **Toronto / GTA / Hamilton / Ottawa metro** | Bigger pools, more mature EMR adoption, easier first-meeting logistics |
| **FHT or FHO affiliated** | Family Health Teams and Family Health Organizations are the dominant capitation-blended primary-care orgs in Ontario. They're the structural analogue to Alberta's PCNs. |
| **EMR we can integrate with** | Telus PS Suite, OSCAR, Accuro, Med Access, Practice Solutions |
| **Public website with team/physicians page** | Indicates a staffed operation, easier to find the office manager's email |

Out of profile (excluded):

- Solo-physician practices (volume too low)
- Walk-in-only clinics (different billing pattern, mostly shadow-billing)
- Pure cosmetic / non-OHIP clinics
- Solo virtual-care clinics

## 2. Priority targets

> **Verify each row against current public sources before any outreach.**
> Confidence ratings reflect training-data knowledge of the Ontario
> clinic landscape as of early 2026. Real-time verification required.

| # | Clinic | City | Physicians (approx) | EMR (guess) | Confidence | Notes |
|---|---|---|---|---|---|---|
| 1 | St. Michael's Hospital Family Health Team | Toronto | ~50 | Telus PS Suite | Medium-High | Academic FHT affiliated with Unity Health. Large biller pool. OPSEU billing staff. |
| 2 | Women's College Hospital Family Practice | Toronto | ~25 | OSCAR | Medium-High | Academic FHT. Known for digital-health innovation (e.g. the "HeretoHelp" program). |
| 3 | Summerville Family Health Team | Mississauga | ~30 | Telus PS Suite | Medium | Large community FHT. Multi-site. |
| 4 | Hamilton FHT | Hamilton | ~40 | Accuro | Medium | Multi-site academic + community FHT. McMaster-affiliated. |
| 5 | Bruyère Family Medicine Centre | Ottawa | ~25 | Med Access | Medium-High | Academic FHT, uOttawa-affiliated. Bilingual (EN/FR) staff. |
| 6 | Sunnybrook Family Practice | Toronto | ~30 | Practice Solutions | Medium-High | Academic FHT, UofT-affiliated. |
| 7 | Mount Sinai Family Practice | Toronto | ~20 | Telus PS Suite | Medium | Academic FHT. |
| 8 | Scarborough Academic Family Health Team | Toronto | ~25 | OSCAR | Medium | Large community FHT in the east end. |
| 9 | North York General Family Practice | Toronto | ~30 | Telus PS Suite | Medium | Community FHT, large volume. |
| 10 | Credit Valley Family Health Team | Mississauga | ~30 | Telus PS Suite | Medium | Community FHT. |

### 2.1 Verification checklist (per clinic, before outreach)

- [ ] Confirm physician count and active status via CPSO registry search.
- [ ] Confirm EMR via a recent job posting on the clinic's careers page
      (Telus PS Suite, OSCAR, Accuro, Med Access, Practice Solutions are
      the canonical names to look for).
- [ ] Confirm the FHT/FHO affiliation via the Ontario Ministry of Health
      FHT list (`health.gov.on.ca`).
- [ ] Confirm the billing lead's name and email via the clinic's website
      (typically "Billing Inquiries" or "Administration" pages) or via
      a brief phone call to the main line.
- [ ] Confirm there is no existing Zorva / Ashbi contact in the CRM
      before reaching out (no double-touch).

## 3. Outreach sequencing

For each priority clinic:

1. **Day 0** — Internal check: confirm no prior touchpoint in CRM.
2. **Day 1** — Send the cold-outreach email (template at
   `templates/email/cold_outreach_v1.txt`). Personalize the subject
   line with the clinic name.
3. **Day 4** — If no reply, send a brief follow-up
   (`templates/email/cold_followup_v1.txt`). Do not chase a third time.
4. **Day 7** — If a reply, book the 10-minute onboarding call
   (script: `docs/ONBOARDING_CALL_SCRIPT.md`).

Target: 10 clinics in this list, ~3 replies expected, ~1 conversion
to a 30-day pilot within 30 days. (Conversion rates from cold outreach
to pilot in our prior channel average 1 in 10 replies; the 10-minute
call script and the BAA template are the leverage points.)

## 4. What NOT to do

- **Do not mass-email** the full list in one batch. Stagger by 1-2
  clinics per day so we can personalize and so a bounce doesn't take
  out the whole send.
- **Do not mention specific denial-rate claims** we can't back up
  with data. The honest claim is "we run the auditor on your last 100
  claims and show you what we'd have flagged"; we cannot predict
  their denial rate in advance.
- **Do not promise pricing on the first email.** Link to the
  one-pager (`docs/ONE_PAGER_WHAT_WE_DO.md`) instead.
- **Do not cc multiple people at the clinic** on the first email.
  If the billing lead forwards, great; if not, the second email
  is to the office manager.

## 5. References

- Ontario Ministry of Health FHT list (`health.gov.on.ca`).
- CPSO physician registry (`cpso.on.ca`).
- The Alberta equivalent: `docs/ALBERTA_PROSPECT_LIST.md`.
- Cold-outreach template: `templates/email/cold_outreach_v1.txt`.
- Onboarding call script: `docs/ONBOARDING_CALL_SCRIPT.md`.
