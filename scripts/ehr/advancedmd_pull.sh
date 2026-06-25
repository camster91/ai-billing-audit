#!/usr/bin/env bash
# AdvancedMD EHR data-pull path for the Zorva pilot.
#
# Kanban: t_d9aae580 (C7) on board 'pilot-ready'.
#
# AdvancedMD is the most common ambulatory EHR in our prospect list
# (~22% of pilot inquiries). They expose two relevant surfaces:
#
#   1. SFTP drop   — daily CSV export of appointment + charge data
#                     (subscription required, included with the
#                     "AdvancedMD Reporting" add-on)
#   2. API v1      — REST API for charge/claim records; OAuth2 with
#                     a clinic-scoped client_id and client_secret
#                     (paid API plan, separate from SFTP)
#
# This script implements the SFTP path because (a) every AdvancedMD
# clinic with the reporting add-on can use it, (b) the API plan is
# usually a 30-day onboarding wait, and (c) the CSV shape is the
# canonical pre-submit feed for our auditor.
#
# Expected input file: amd_daily_<YYYY-MM-DD>.csv with columns
#   PatientID, DateOfService, ProviderNPI, CPT, ICD10, ChargeCents,
#   Payer, PlaceOfService
# (AdvancedMD's "Daily Charges Export" template — see their KB
# article 20321 for the schema. We document deviations in
# docs/EHR_ADVANCEDMD_INTEGRATION.md.)
#
# Output: data/inbox/<tenant>/encounters_<YYYY-MM-DD>.jsonl in the
# Zorva encounter-upload shape (see src/ai_billing_audit/csv_ingest.py).
#
# Usage:
#   ./scripts/ehr/advancedmd_pull.sh \
#     --host sftp.advancedmd.com \
#     --user "$AMD_SFTP_USER" \
#     --tenant acme-clinic \
#     --out data/inbox
#
# Env: AMD_SFTP_USER, AMD_SFTP_KEY_PATH, AMD_SFTP_REMOTE_DIR.

set -euo pipefail

HOST=""
USER=""
TENANT=""
OUT_DIR=""
KEY_PATH="${AMD_SFTP_KEY_PATH:-$HOME/.ssh/amd_sftp_key}"
REMOTE_DIR="${AMD_SFTP_REMOTE_DIR:-./outgoing}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --user) USER="$2"; shift 2 ;;
    --tenant) TENANT="$2"; shift 2 ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    --key) KEY_PATH="$2"; shift 2 ;;
    --remote-dir) REMOTE_DIR="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 64 ;;
  esac
done

if [[ -z "$HOST" || -z "$USER" || -z "$TENANT" || -z "$OUT_DIR" ]]; then
  echo "usage: $0 --host H --user U --tenant T --out DIR" >&2
  exit 64
fi

mkdir -p "$OUT_DIR/$TENANT"

# Pull today's CSV via sftp batch.
BATCH=$(mktemp)
trap 'rm -f "$BATCH"' EXIT
{
  echo "cd $REMOTE_DIR"
  echo "lcd $OUT_DIR/$TENANT"
  TODAY=$(date -u +%Y-%m-%d)
  echo "get amd_daily_${TODAY}.csv amd_${TENANT}_${TODAY}.csv"
  echo "bye"
} > "$BATCH"

echo "[amd] pulling amd_daily_${TODAY}.csv from ${USER}@${HOST}"
sftp -b "$BATCH" -i "$KEY_PATH" -o BatchMode=yes "${USER}@${HOST}"

CSV="$OUT_DIR/$TENANT/amd_${TENANT}_$(date -u +%Y-%m-%d).csv"
if [[ ! -s "$CSV" ]]; then
  echo "[amd] FAIL: pulled CSV is missing or empty: $CSV" >&2
  exit 1
fi

# Convert CSV to Zorva encounter-upload JSONL.
OUT="$OUT_DIR/$TENANT/encounters_$(date -u +%Y-%m-%d).jsonl"
echo "[amd] converting $CSV -> $OUT"
python3 - "$CSV" "$OUT" <<'PY'
import csv, json, sys, uuid

src, dst = sys.argv[1], sys.argv[2]
with open(src, newline="") as fh, open(dst, "w") as out:
    reader = csv.DictReader(fh)
    for row in reader:
        cpt = [c.strip() for c in (row.get("CPT") or "").split(",") if c.strip()]
        icd = [c.strip() for c in (row.get("ICD10") or "").split(",") if c.strip()]
        enc = {
            "encounter_id": row.get("PatientID") + "-" + row.get("DateOfService", ""),
            "tenant_id": row.get("TenantId") or "",
            "patient_hash": hashlib_for(row.get("PatientID", "")),
            "date_of_service": row.get("DateOfService"),
            "provider_npi": row.get("ProviderNPI"),
            "provider_name": row.get("ProviderName"),
            "payer": row.get("Payer"),
            "place_of_service": row.get("PlaceOfService"),
            "claim": {"cpt_codes": cpt, "icd10_codes": icd},
            "charge_cents": int(row.get("ChargeCents") or 0),
            "clinical_note": row.get("ClinicalNote", ""),
            "source": "advancedmd_sftp",
        }
        out.write(json.dumps(enc) + "\n")
print(f"wrote {dst}", file=sys.stderr)


def hashlib_for(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.lower().encode("utf-8")).hexdigest() if s else ""
PY

echo "[amd] done: $OUT"
