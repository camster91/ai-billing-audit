# Task 3 — Canadian small-clinic EHR data-transfer story (for Eliud)

**Research time:** 25 min, web only. No Canadian-government source citation used; URLs listed at end.

## Market reality (1-10 provider clinics, Canada)

The big three for small primary-care clinics are TELUS PS Suite, OSCAR McMaster, and TELUS QHR/Accuro. These cover >80% of the small-clinic segment. The MVP's current ingest path (837P file upload, JSON paste, clinical-note file upload) is *fine* for tech-forward clinics but **will not scale to the median small clinic** without one of the integrations below.

## Per-EHR export story

### TELUS PS Suite (PS) — Ontario default, ~40% market
- **Billed-claim export path:** PS Suite has built-in MOH file send/receive via **MC EDT** (Medical Claims Electronic Data Transfer). The PS Suite training manual (`scribd.com/document/443881510`) shows `MOH > Send & Receive Files Via MC EDT` — this is the file-out path that produces 837P-equivalent Ontario claim files. These are written to a local outbox, not pushed to the ministry.
- **SFTP/API:** No public REST API for third parties. Vendors integrate via the **6B interoperability service** (`6b.health/.../telus-ps-suite-emr-integration`) which is a paid intermediary, or via OntarioMD's PS Suite extensions. Direct SFTP/EDI from a third party requires the clinic's own MOH MC EDT credentials.
- **Clinical note export:** No native JSON. Reports can be exported as PDF or CSV; raw encounter data is reachable only through OntarioMD's vendor extension program.
- **Minimum viable integration:** A weekly batch script on the clinic's PS Suite server that copies the MC EDT outbox to a clinic-controlled SFTP folder. **Realistic for a tech-comfortable MOA; not realistic for a solo doctor.**

### OSCAR McMaster — open-source, BC/ON/QC mix
- **Billed-claim export path:** OSCAR has the same MC EDT path as PS Suite for Ontario (`oscarmanual.org/oscar_emr_12/General+Operation/billing/ONbilling/edt-setup/`), and ClinicAid integration (`blog.clinicaid.ca/2014/04/clinicaid-billing-integration-oscarEMR.html`) is the dominant third-party billing pipeline.
- **SFTP/API:** ClinicAid has a public API for billing (`clinicaid.ca/api-integrations/`) and OSCAR itself supports CSV export of patient/encounter data. The ClinicAid API is the only realistic on-ramp for real-time 837P-equivalent data from OSCAR today.
- **Clinical note export:** OSCAR has the most open export story of the three — direct DB access for vendor partners, plus CSV/PDF.
- **Minimum viable integration:** Pull from **ClinicAid's API** if the clinic already uses ClinicAid (most OSCAR clinics do). Otherwise the clinic runs a local cron that writes OSCAR's encounter CSV to an SFTP drop. OSCAR clinics are the most likely to have a tech-comfortable MOA.

### QHR Accuro — Western Canada + specialty clinics
- **Billed-claim export path:** Accuro has a built-in "Billing Period Export" that creates a snapshot as **CSV** (`userguide.accuroemr.com/Billing_Period_Export.htm`). This is the realistic handoff.
- **SFTP/API:** No public API. QHR/Accuro is a closed product. Enterprise integrations go through TELUS Health's enterprise API, which is gated and priced per integration (CHIME mentions this in `help.chimeclinic.com/features/platform-level/emr-integration`).
- **Clinical note export:** CSV/built-in reports only; no JSON or API.
- **Minimum viable integration:** MOA clicks `Start > Reports > Billing Period Export > Save CSV to SFTP folder` on a weekly cadence. Pure manual — but Accuro's export is the most *complete* of the three, so a CSV-based ingest path actually works.

## Top-3 minimum-viable integrations (ranked by effort vs. coverage)

1. **PS Suite via 837P-from-MC-EDT-outbox SFTP drop** — covers the largest single market. Requires a 1-page setup doc the MOA follows. 4-hour engineering to build a `pssuite-sftp-watcher` that ingests new files.
2. **OSCAR via ClinicAid API** — second-largest segment, and ClinicAid already has the API. 1-day engineering to wire to ClinicAid's `https://clinicaid.ca/api-integrations/`. Requires the clinic to be a ClinicAid customer (most OSCAR clinics are).
3. **QHR Accuro via weekly CSV drop** — third. Cheapest to ship (we already accept file uploads), but most manual on the clinic side. 0 engineering if we add a CSV-to-internal-JSON parser alongside the 837P parser.

## What I would tell Eliud (the operations contact)

The current MVP ingest path is sufficient as a *demo* and as an *API product* for a clinic with an in-house tech person, but it is not a turnkey product for the median small clinic. The realistic path to a paying customer is:

- Build the PS Suite SFTP watcher first. That covers the Ontario base.
- Build a ClinicAid API adapter second. That covers OSCAR clinics.
- Keep the 837P file upload as the escape hatch for everything else (Accuro, niche EHRs, paper-based clinics that batch-export at end of month).

The MVP does not need a "live" integration to ship — Eliud can use the 837P file upload for the first pilot clinic and tell the customer "drop your 837P weekly into this SFTP folder." That works today. The PS Suite and ClinicAid adapters are the path to *self-serve* onboarding, which is the real product question.

## Sources

- `telus.com/en/health/health-professionals/clinics/ps-suite` (vendor)
- `scribd.com/document/443881510/PS-Suite-Training-Workbook-Ontario` (MC EDT path)
- `oscarmanual.org/oscar_emr_12/General+Operation/billing/ONbilling/edt-setup/` (OSCAR MC EDT)
- `blog.clinicaid.ca/2014/04/clinicaid-billing-integration-oscarEMR.html` (ClinicAid↔OSCAR)
- `clinicaid.ca/api-integrations/` (ClinicAid API)
- `userguide.accuroemr.com/Billing_Period_Export.htm` (Accuro CSV export)
- `help.chimeclinic.com/features/platform-level/emr-integration` (Accuro enterprise API gating)
- `6b.health/services/interoperability-and-integration/primary-care-ehr-integration/telus-ps-suite-emr-integration/` (paid PS Suite integration)
