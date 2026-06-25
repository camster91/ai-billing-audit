#!/usr/bin/env bash
# Smoke test for /encounters/{id} 500-on-fresh-upload bug.
# Kanban task: t_9c35ced7 on board 'pilot-ready'.
#
# Steps:
#   1. POST one encounter to /encounters/upload
#   2. Poll /encounters/upload/jobs/{job_id} until status is done
#   3. GET /encounter/{id} (singular, live route) AND /encounters/{id} (plural, shadow route)
#   4. Exit 0 only if BOTH return 2xx with the matching encounter_id
#
# Usage:
#   ./scripts/smoke_postupload.sh [--base URL] [--token TKN] [--payload PATH]
# Env: ZORVA_BASE, ZORVA_PILOT_TOKEN, ZORVA_PAYLOAD.
set -euo pipefail

BASE="${ZORVA_BASE:-http://localhost:8000}"
ACCESS_TOKEN=""
PAYLOAD="${ZORVA_PAYLOAD:-data/synth/val.json}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="$2"; shift 2 ;;
    --token) ACCESS_TOKEN="$2"; shift 2 ;;
    --payload) PAYLOAD="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 64 ;;
  esac
done

# Allow ZORVA_PILOT_TOKEN env var to populate ACCESS_TOKEN.
if [[ -z "$ACCESS_TOKEN" && -n "${ZORVA_PILOT_TOKEN:-}" ]]; then
  ACCESS_TOKEN="$ZORVA_PILOT_TOKEN"
fi

auth_args=()
if [[ -n "$ACCESS_TOKEN" ]]; then
  auth_args=(-H "Authorization: Bearer ${ACCESS_TOKEN}")
fi

if [[ ! -f "$PAYLOAD" ]]; then
  echo "[smoke] FAIL: payload file not found: $PAYLOAD" >&2
  exit 2
fi

SAMPLE=$(python3 - "$PAYLOAD" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
if isinstance(data, dict):
    data = data.get('encounters') or data.get('entries') or []
print(json.dumps(data[0]))
PY
)
EID=$(printf '%s' "$SAMPLE" | python3 -c "import json,sys; print(json.load(sys.stdin)['encounter_id'])")

echo "[smoke] base=${BASE} encounter=${EID}"

echo "[smoke] POST /encounters/upload"
UPLOAD_RESP=$(curl -fsS -X POST \
    -H "Content-Type: application/json" \
    "${auth_args[@]}" \
    --data "$SAMPLE" \
    "${BASE}/encounters/upload" 2>/dev/null) || {
    echo "[smoke] FAIL: upload POST failed" >&2
    exit 1
}
JOB_ID=$(printf '%s' "$UPLOAD_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('job_id') or d.get('id') or '')")
if [[ -z "$JOB_ID" ]]; then
    echo "[smoke] FAIL: upload response had no job_id: ${UPLOAD_RESP}" >&2
    exit 1
fi
echo "[smoke] job_id=${JOB_ID}"

echo "[smoke] polling /encounters/upload/jobs/${JOB_ID}"
STATUS=""
for _ in {1..30}; do
    sleep 2
    J=$(curl -fsS "${auth_args[@]}" "${BASE}/encounters/upload/jobs/${JOB_ID}" 2>/dev/null || echo "")
    STATUS=$(printf '%s' "$J" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status') or d.get('state') or '')" 2>/dev/null || echo "")
    case "$STATUS" in
        done|completed|success) echo "[smoke] job complete"; break ;;
        failed|error)
            echo "[smoke] FAIL: job failed: ${J}" >&2
            exit 1
            ;;
    esac
done
case "$STATUS" in
    done|completed|success) ;;
    *) echo "[smoke] FAIL: job did not complete in 60s (status=${STATUS})" >&2; exit 1 ;;
esac

fail=0
for path in "/encounter/${EID}" "/encounters/${EID}"; do
    echo "[smoke] GET ${path}"
    CODE=$(curl -s -o /tmp/zorva_smoke.body -w "%{http_code}" "${auth_args[@]}" "${BASE}${path}" || echo "000")
    BODY=$(cat /tmp/zorva_smoke.body || true)
    if [[ "$CODE" =~ ^2 ]]; then
        if printf '%s' "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('encounter_id')=='${EID}' else 1)" 2>/dev/null; then
            echo "[smoke] OK ${path} -> ${CODE}"
        else
            echo "[smoke] WARN ${path} returned ${CODE} but body did not contain matching encounter_id"
            fail=1
        fi
    else
        echo "[smoke] FAIL ${path} -> ${CODE}: ${BODY}" >&2
        fail=1
    fi
done

if [[ $fail -ne 0 ]]; then
    echo "[smoke] OVERALL: FAIL"
    exit 1
fi
echo "[smoke] OVERALL: PASS"
exit 0
