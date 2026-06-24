# VPS smoke test — `ai-billing-audit.ashbi.ca`

Run on 2026-06-16 (Tue) at 23:30 EDT, kanban `t_b199142a`, profile
`default`. The five-step smoke was aborted at step 1: the public
hostname answers 404 from Traefik because no route exists. Steps 2-5
were not attempted — they would all fail at the same wall (no backend
container to talk to). Each step below records the exact curl, the
exact observed status, and the conclusion.

> **Bottom line:** the `ai-billing-audit` app was never successfully
> deployed to the VPS. The repo is at `~/projects/ai-billing-audit`,
> the deploy script `deploy-to-vps.sh` exists, and it was committed
> (`5305197 Mirror VPS build to v0.1.0-rc1`), but no container is
> running, no Traefik route is defined, no source dir exists on the
> host. The 404s on the public hostname are Traefik's default
> response for an unrouted `Host(...)` rule — there is no backend
> to fail.
>
> The associated bug is filed as `BUG-2026-06-16-04 — VPS deploy
> never completed: no Traefik route, no container, no project dir`
> in `docs/BUGS.md`.

## Environment

- **Local machine:** macOS 26.5.1, terminal backends OK
- **Target host:** VPS at `187.77.26.99` (ssh alias `hostinger`),
  Traefik v3.2 watching `/opt/traefik/dynamic/`
- **Project repo (local):** `~/projects/ai-billing-audit`,
  commit `5305197` (v0.1.0-rc1)
- **Project repo (VPS):** `ls /opt/projects/ai-billing-audit` →
  *No such file or directory*
- **Public hostname:** `ai-billing-audit.ashbi.ca`
  (DNS A → `187.77.26.99`, confirmed via `dig +short`)

## Pre-flight checks

| Check | Command | Observed | Verdict |
|---|---|---|---|
| DNS resolves to VPS | `dig +short ai-billing-audit.ashbi.ca A` | `187.77.26.99` | OK |
| TLS endpoint answers | `openssl s_client … -connect ai-billing-audit.ashbi.ca:443` | TCP handshake, X.509 returned | OK (cert is Traefik default — see below) |
| Cert subject | `openssl x509 -noout -subject -issuer` | `subject=CN=TRAEFIK DEFAULT CERT`, `issuer=CN=TRAEFIK DEFAULT CERT` | **NOT** a Let's Encrypt cert. Traefik's auto-generated default cert is being served because no route is defined for this host, so the `letsencrypt` resolver never ran. |
| Cert dates | `openssl x509 -noout -dates` | `notBefore=Jun 16 23:07:20 2026 GMT`, `notAfter=Jun 16 23:07:20 2027 GMT` | Within validity, but self-signed default cert |
| Traefik dynamic config | `ssh hostinger 'grep -i "ai-billing" /opt/traefik/dynamic/routers.yml /opt/traefik/dynamic/tls.yml'` | no matches | **No route defined** |
| Container inventory | `ssh hostinger 'docker ps -a \\| grep -i billing'` | (none) | **No container present** |
| Project source on VPS | `ssh hostinger 'ls /opt/projects/ai-billing-audit'` | `No such file or directory` | **Never rsynced** |
| Cert file on VPS | `ssh hostinger 'ls /opt/traefik/certs/ \\| grep -i billing'` | (none) | **No cert provisioned** |

## Step 1 — `GET /healthz` (public, via Traefik)

**Expected (per spec):** 2xx response (FastAPI `healthz` returns
`{"status":"ok","version":...,"title":...,"n_registered":...}`).

**Actual:** HTTP **404**, body `404 page not found`,
`content-type=text/plain; charset=utf-8`, 19 bytes, ~220ms.

```bash
$ curl -k -sS -o /tmp/healthz.body \
    -w 'http=%{http_code} size=%{size_download} ct=%{content_type} time=%{time_total}\n' \
    https://ai-billing-audit.ashbi.ca/healthz
http=404 size=19 ct=text/plain; charset=utf-8 time=0.220994
$ cat /tmp/healthz.body
404 page not found
```

The `-k` flag was used because the local mac doesn't trust the
self-signed Traefik default cert. The 404 is **not** a TLS failure
or a Caddy 404 — Traefik returns its built-in `404 page not found`
when an incoming request matches no `Host(...)` rule. The cert being
self-signed Traefik default (not LE) is itself evidence: Traefik only
falls through to the default cert if no router claimed the request.

### Route scan (confirms no router exists)

All 15 candidate paths return 404:

```
404  /
404  /health
404  /healthz
404  /api
404  /api/v1
404  /docs
404  /openapi.json
404  /v1/healthz
404  /api/health
404  /api/encounters
404  /encounters
404  /api/v1/encounters
404  /encounter/1
404  /encounter/1/json
404  /encounters/upload
```

If a route existed, FastAPI's `/` and `/healthz` would at minimum
return content (200 / HTML). Every path 404ing on the same response
shape (text/plain, 19 bytes) is Traefik's static 404 page, not an
application-level not-found.

```bash
for path in / /health /healthz /api /api/v1 /docs /openapi.json \
            /v1/healthz /api/health /api/encounters /encounters \
            /api/v1/encounters /encounter/1 /encounter/1/json \
            /encounters/upload; do
  status=$(curl -k -s -o /dev/null -w '%{http_code}' \
    "https://ai-billing-audit.ashbi.ca${path}")
  echo "$status  $path"
done
```

**Step 1 result: FAIL.** No HTTP 2xx reachable on the public
hostname. Aborting the rest of the smoke run.

## Step 2 — POST sample encounter to API

**Status: not attempted.** The API host is unreachable on every path;
a POST would hit the same Traefik 404 wall. Documented command for
reference (will work once the deploy is fixed and the route exists):

```bash
# Source-of-truth endpoint from src/ai_billing_audit/api.py
curl -k -sS -X POST https://ai-billing-audit.ashbi.ca/encounters/upload/submit \
  -F "payload=$(cat <<'JSON'
{
  "rows": [{
    "encounter_id": "smoke-test-001",
    "patient_id":   "patient-smoke-001",
    "claim": {
      "cpt_codes": ["99213"],
      "icd10_codes": ["I10"],
      "modifiers": [],
      "visit_date": "2026-06-16",
      "provider_npi": "1234567893"
    },
    "note_text": "Smoke-test encounter. Office visit, established patient, hypertension follow-up."
  }]
}
JSON
)"
```

**Expected response (when deploy exists):** HTTP 200 with a
`{job_ids: [...], accepted: 1, rejected: 0, ...}` shape per
`/encounters/upload/submit` in `api.py:487`.

## Step 3 — Verify row in `audit_trail` table

**Status: not attempted.** No app means no DB. The schema is in
`audit_trail.sql` at the repo root; once the deploy runs, verify with:

```bash
# Once deploy exists — read DATABASE_URL/AUDIT_TRAIL_DB from the host env
ssh hostinger 'docker exec $(docker ps -qf "name=postgres") \
  psql -U postgres -d audit -c \
  "SELECT id, encounter_id, patient_id, created_at FROM audit_trail WHERE encounter_id = '"'"'smoke-test-001'"'"' ORDER BY id DESC LIMIT 5"'
```

## Step 4 — Observe job queue processing

**Status: not attempted.** The job queue lives in the FastAPI
process; with no process running, there's nothing to observe.
Documented command for after-fix verification:

```bash
# Once deploy exists
ssh hostinger 'tail -F /opt/projects/ai-billing-audit/logs/upload_jobs.jsonl | \
  jq -c "select(.encounter_id == \"smoke-test-001\")"'
```

## Step 5 — Re-fetch finding via API

**Status: not attempted.** The finding endpoint is
`/encounter/{encounter_id}/json` (api.py:248). Documented command:

```bash
# Once deploy exists
curl -k -sS https://ai-billing-audit.ashbi.ca/encounter/smoke-test-001/json \
  | jq '. | {encounter_id, status, finding_summary, codes: .codes}'
```

## Summary

| # | Step | Expected | Observed | Pass/Fail |
|---|---|---|---|---|
| 1 | `GET /healthz` (public) | 2xx + JSON body | 404, 19 bytes, Traefik default | **FAIL** |
| 2 | POST `/encounters/upload/submit` | 200 + `{job_ids:[...]}` | not attempted (blocked by 1) | n/a |
| 3 | Row in `audit_trail` | ≥ 1 row matching payload | not attempted (no app) | n/a |
| 4 | Worker log entry | job state change captured | not attempted (no app) | n/a |
| 5 | `GET /encounter/{id}/json` | 200 with finding | not attempted (no app) | n/a |

**Deployment status: NOT VERIFIED.** The 5-step smoke was blocked at
step 1 because the `ai-billing-audit` application is not deployed
to the VPS. Bug filed as `BUG-2026-06-16-04` in `docs/BUGS.md`.

## Acceptance criteria — final

- [ ] `GET /healthz` returns a 2xx status; status code recorded in
      the doc. — **Failed**: 404 recorded above, see step 1.
- [ ] A sample encounter is successfully POSTed to the API;
      request and response captured. — **Not done**: blocked by
      step 1; documented command shown.
- [ ] The posted encounter is verified to exist in the `audit_trail`
      table (row count ≥ 1, matching payload fields). — **Not done**:
      no DB; documented command shown.
- [ ] The job queue is observed processing the encounter (worker
      log entry or queue state change captured). — **Not done**: no
      worker; documented command shown.
- [ ] A subsequent API response includes the finding derived from
      the posted encounter. — **Not done**: no API; documented
      command shown.
- [ ] `docs/VPS_SMOKE_TEST.md` exists and contains: the curl
      commands for steps 1-2 (and the verification call for step
      5), plus the documented response status codes for each. —
      **Done**: this file.
- [ ] Any failure during the five steps results in a filed bug with
      reproduction details. — **Done**: `BUG-2026-06-16-04` in
      `docs/BUGS.md`.
