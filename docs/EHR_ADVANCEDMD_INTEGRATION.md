# AdvancedMD integration — Zorva pilot data-pull path

> Kanban: t_d9aae580 (C7) on board 'pilot-ready'.
> Owner: engineering. Status: SFTP path implemented (see
> `scripts/ehr/advancedmd_pull.sh`); REST path stubbed below.

AdvancedMD is the most common ambulatory EHR in our prospect pipeline
(roughly 22% of pilot inquiries as of 2026-06). They expose two surfaces
relevant to pre-submit auditing:

## 1. SFTP drop (implemented)

**Path:** `scripts/ehr/advancedmd_pull.sh`

**Setup (one-time, per clinic):**

1. The clinic enables the **AdvancedMD Reporting** add-on (or the
   "Daily Charges Export" feature; it ships with the standard
   subscription as of the 2025.x release).
2. The clinic's billing admin generates an SFTP keypair and uploads
   the public key to AdvancedMD's SFTP user admin. The convention
   we use is `zorva-pilot-<tenant-slug>`.
3. The clinic configures the daily export to land in the
   `outgoing/amd_daily_<YYYY-MM-DD>.csv` filename pattern.
4. Zorva's ingest server runs `advancedmd_pull.sh` once daily at
   02:00 clinic-local time, pulling the previous day's CSV.

**Required CSV columns (AdvancedMD template):**

| Column            | Notes                                                  |
|-------------------|--------------------------------------------------------|
| `PatientID`       | Internal MRN. Hashed (SHA-256) on ingest.              |
| `DateOfService`   | ISO `YYYY-MM-DD`.                                      |
| `ProviderNPI`     | 10-digit US NPI.                                       |
| `CPT`             | Comma-separated CPT codes (e.g. `99213,93000`).        |
| `ICD10`           | Comma-separated ICD-10 codes.                          |
| `ChargeCents`     | Integer; cents, not dollars.                           |
| `Payer`           | Free-text payer name.                                  |
| `PlaceOfService`  | CMS POS code (11 = office, 22 = outpatient, etc.).     |
| `ClinicalNote`    | Free-text narrative. Required for the auditor to run.  |

**Output:** `data/inbox/<tenant>/encounters_<YYYY-MM-DD>.jsonl` in the
canonical Zorva encounter-upload shape (see
`src/ai_billing_audit/csv_ingest.py`).

**Deviations from the AdvancedMD template:** we add `TenantId` and
`ProviderName` columns if the clinic's CSV doesn't include them; we
treat empty `ClinicalNote` as a hard fail (no silent-no-note uploads).

## 2. REST API (stubbed)

AdvancedMD exposes a JSON-over-HTTPS API at `https://api.advancedmd.com/v1/`
for charge and claim records. The auth flow is OAuth2 with
client_credentials grant.

**Status:** API path is **not yet implemented** in the SFTP script.
Reason: the API requires AdvancedMD's "API Tier 2" paid plan (~$300/mo
per clinic), and the SFTP path covers 100% of the AdvancedMD pilots in
our pipeline as of 2026-06.

**When we'll need it:** if a pilot clinic refuses the SFTP add-on or
needs sub-daily pull latency, we'll add an `--api` flag to the pull
script. The OAuth2 token cache and the per-clinic rate-limit (60 req/min
on Tier 2) are the main design points; everything else mirrors the SFTP
ingest path.

## 3. Audit-trail integration

Every AdvancedMD pull writes one `ehr_pull` event to the audit chain
(`src/ai_billing_audit/audit_actions.py`) with:

- `tenant_id`
- `source: advancedmd_sftp` (or `advancedmd_api` in the future)
- `encounter_count: N`
- `sha256(csv_contents): ...` for tamper-evidence
- `pulled_at: <utc>`

This row lets the privacy officer reconstruct which clinical notes
were on Zorva at any point in time, and proves that no rows were
edited between the EHR and our ingest.

## 4. Failure modes & alarms

| Failure                  | Detection                        | Action                                                |
|--------------------------|----------------------------------|-------------------------------------------------------|
| SFTP login fails         | exit code != 0 of `sftp`         | Slack `#pilots` channel + PagerDuty if persistent.    |
| CSV missing or empty     | post-pull file check             | Skip ingest, log warning, retry on next run.          |
| CSV schema invalid       | `csv_ingest.py` raises           | Skip ingest, post CSV to #pilots for human review.    |
| Clinical note missing    | per-row validation               | Skip that row only, count in the audit-chain note.    |
| ChargeCents negative     | per-row validation               | Skip that row only, raise invoice-question ticket.    |

## 5. Cleanup

Per `docs/BAA_TEMPLATE_HIPAA.md` and the per-pilot data agreement,
CSV pulls are retained on the ingest server for **30 days** (the
audit-chain row stays forever; the source CSV is purged on day 31).

## 6. Operational checklist

- [ ] SFTP key rotated every 90 days per the security one-pager.
- [ ] Daily run cron is on `ingest-1.zorva.example.com` with monitoring.
- [ ] Per-tenant cron entry lives at
      `deploy/ansible/roles/ingest/tasks/advancedmd.yml`.
- [ ] On-call rotation includes an AdvancedMD specialist.

## 7. References

- AdvancedMD "Daily Charges Export" KB article 20321 (login required).
- AdvancedMD API v1 docs at `https://docs.advancedmd.com/`.
- `src/ai_billing_audit/csv_ingest.py` — the CSV-to-JSONL converter.
- `docs/EHR_INTEGRATION_ROADMAP.md` — the broader EHR priority list.
