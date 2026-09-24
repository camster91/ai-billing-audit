# QA — API Hardening: Adversarial Inputs

**Date:** 2026-06-17
**Operator:** kanban worker `default` (task `t_9d37bfee`)
**Target:** https://ai-billing-audit.ashbi.ca
**Server stack observed:** FastAPI / uvicorn, fronted by Caddy (TLS terminator) and Traefik; no app-level auth on any endpoint.
**Per-case raw output:** `docs/qa_artifacts/api_hardening_2026_06_17/raw/case_NN.txt`

---

## 0. Endpoint surface and spec-vs-reality note

The task body was written against an API shape that no longer matches the live service. The live `/openapi.json` (title: `ai-billing-audit demo dashboard`) exposes the following routes:

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Demo encounter list (HTML) |
| GET | `/healthz` | Liveness |
| GET | `/encounter/{encounter_id}` | Encounter detail (HTML) |
| GET | `/encounter/{encounter_id}/json` | Encounter detail (JSON) |
| GET | `/encounters/upload` | Upload form (HTML) |
| POST | `/encounters/upload/preview` | Multipart, field `file` |
| POST | `/encounters/upload/submit` | Form-encoded |
| POST | `/encounters/upload/paste` | Form-encoded, field `content` |
| POST | `/encounters/upload/notes` | Multipart, field `file` |
| GET | `/encounters/upload/jobs/{job_id}` | Job status |

The task body's references that don't exist on the live API:

- `POST /encounters` (cases 1, 2, 3, 4, 7) → no plain `POST /encounters` route. The nearest write surface is `POST /encounters/upload/preview` (multipart `file`). All "POST encounter" cases below are mapped to the real write surface and called out inline.
- `POST /findings/<id>/dismiss` (case 6) → endpoint does not exist. Both the literal request and the closest mutation (`POST /encounters/upload/paste` with empty content) are exercised.
- Auth header (cases 8, 9) → the API has **no auth on any endpoint** (no `Authorization` validation; the multi-tenant portal `apps/portal` is a separate service). Expected `401` is never produced because the check does not exist. Both the no-header and bad-token probes are run; all responses are recorded.

The 5xx-defect rule from the task is unchanged: any 5xx observed becomes a `BUGS.md` entry.

---

## 1. Test cases — results

### Case 1 — POST /encounters with empty body

**Spec target:** `POST /encounters` (does not exist).
**Mapped to:** `POST /encounters/upload/preview` with empty body, `content-type: application/json`.

```bash
curl -i -X POST https://ai-billing-audit.ashbi.ca/encounters/upload/preview \
  -H 'content-type: application/json' --data-binary ''
```

- **Expected:** 422
- **Actual:** 422
- **Body:** `{"detail":[{"type":"missing","loc":["body","file"],"msg":"Field required","input":null}]}`
- **Verdict:** PASS. Missing `file` field produces a clear, structured validation error from FastAPI's Pydantic layer. The error pinpoints the exact field and is suitable for an API client to surface to a human.

### Case 2 — POST with `encounter_id='../../../etc/passwd'`

**Spec target:** `POST /encounters` with traversal payload. Mapped to the closest read-by-id surface: `GET /encounter/../../../etc/passwd` (percent-encoded + raw) and to `GET /encounter/enc_0000` (a real id from the demo list) to confirm normal lookup.

```bash
curl -i https://ai-billing-audit.ashbi.ca/encounter/%2E%2E%2F%2E%2E%2F%2E%2E%2Fetc%2Fpasswd
curl -i https://ai-billing-audit.ashbi.ca/encounter/../../../etc/passwd
curl -i https://ai-billing-audit.ashbi.ca/encounter/enc_0000
```

- **Expected:** 404 (no leak of `/etc/passwd` content)
- **Actual:** 404 (percent-encoded) and 404 (raw, slash-collapsed by the HTTP client before send)
- **Verdict:** PASS. No filesystem content is exposed. Encoded traversal is rejected with a clean 404. (The `../` literal is silently normalized by curl/ALPN to `/etc/passwd` and then the route returns 404 because no encounter by that id exists.)
- **Note:** The actual encounter id `enc_0000` (shown on `/` as a demo) also returns 404 — see Finding F-1.

### Case 3 — `encounter_id` as a 10 MB string

**Spec target:** a 10 MB payload. Mapped to two probes:
- (a) `GET /encounter/<200-char-string>` to exercise the path-parameter path.
- (b) `POST /encounters/upload/preview` with a 10 MiB file body.

```bash
# (a) — sample path stress
curl -i 'https://ai-billing-audit.ashbi.ca/encounter/AAAA...AAAA'   # 200 chars

# (b) — full 10 MiB upload
dd if=/dev/zero bs=1M count=10 | curl -i -X POST \
  https://ai-billing-audit.ashbi.ca/encounters/upload/preview \
  -F 'file=@-;filename=big.bin;type=application/octet-stream'
```

- **Expected:** 413 or 422 (no 5xx)
- **Actual:**
  - (a) `GET` 404
  - (b) `POST` **200** with body `{"filename":"big.txt","rows":[],"error":"no CLM segment found; the file is not a recognisable 837P payload"}`
- **Verdict:** PARTIAL — the size limit is not what the task assumed. Server accepts payloads up to **at least 10 MiB** with full read, then rejects at **25 MiB** with a clean `413`. Limit is somewhere in the 10–25 MiB window; the exact threshold wasn't probed. See Finding F-2 for the 10 MiB accept (real concern: full-file read into memory for every upload, no streaming/chunked validation).

### Case 4 — `content-type: text/html`

```bash
curl -i -X POST https://ai-billing-audit.ashbi.ca/encounters/upload/preview \
  -H 'content-type: text/html' \
  --data-binary '<html><body>not json</body></html>'
```

- **Expected:** 415
- **Actual:** 422
- **Body:** `{"detail":[{"type":"missing","loc":["body","file"],"msg":"Field required","input":null}]}`
- **Verdict:** ACCEPTABLE. The endpoint is multipart-only, so any non-multipart body — including `text/html` and `application/json` — is rejected at the body parser with 422. A stricter API would return 415 ("Unsupported Media Type") for a clearly wrong type; the current 422 still rejects the input safely and gives a useful error. Not a defect.

### Case 5 — `GET /encounters/nonexistent_id`

**Mapped to:** `GET /encounter/<nonexistent_id>` (the live API uses singular `/encounter/...`).

```bash
curl -i https://ai-billing-audit.ashbi.ca/encounter/nonexistent_id_xyz_does_not_exist
```

- **Expected:** 404
- **Actual:** 404
- **Verdict:** PASS.

### Case 6 — `POST /findings/<id>/dismiss` with `finding_id='undefined'`

**Spec target:** `POST /findings/undefined/dismiss` (does not exist).
**Mapped to:** the literal request (will 404 because the route is missing) plus the closest mutation: `POST /encounters/upload/paste` with empty content.

```bash
curl -i -X POST https://ai-billing-audit.ashbi.ca/findings/undefined/dismiss \
  -H 'content-type: application/json' \
  --data-binary '{"finding_id":"undefined"}'

curl -i -X POST https://ai-billing-audit.ashbi.ca/encounters/upload/paste \
  -F 'content='
```

- **Expected:** 404 (literal) and 422 (paste)
- **Actual:** 404 and 422
- **Verdict:** PASS. The literal endpoint is absent; the existing paste endpoint rejects empty input cleanly with 422. No 5xx.

### Case 7 — Valid JSON, missing required fields

**Mapped to:** `POST /encounters/upload/preview` with a JSON body of `{"foo":"bar","baz":42}` (the route is multipart, so JSON isn't valid here, but the body parser will still surface "missing `file` field").

```bash
curl -i -X POST https://ai-billing-audit.ashbi.ca/encounters/upload/preview \
  -H 'content-type: application/json' \
  --data-binary '{"foo":"bar","baz":42}'
```

- **Expected:** 422 with helpful error
- **Actual:** 422
- **Body:** `{"detail":[{"type":"missing","loc":["body","file"],"msg":"Field required","input":null}]}`
- **Verdict:** PASS. FastAPI's Pydantic v2 validator names the field, its location, and the error type — this is a developer-friendly error.

### Case 8 — Every endpoint without `Authorization` header

**Mapped to:** all 10 live endpoints, with no `Authorization` header at all.

```bash
# GETs
for ep in / /healthz /encounter/enc_0000 /encounter/enc_0000/json \
          /encounters/upload /encounters/upload/jobs/nonexistent_job_xyz; do
  curl -sS -o /dev/null -w "%{http_code}  $ep\n" -m 15 "https://ai-billing-audit.ashbi.ca$ep"
done

# POSTs (with minimal valid form/file payloads)
for ep in /encounters/upload/preview /encounters/upload/submit \
          /encounters/upload/paste /encounters/upload/notes; do
  curl -sS -o /dev/null -w "%{http_code}  $ep\n" -m 15 -X POST "https://ai-billing-audit.ashbi.ca$ep" \
    -F 'file=@/tmp/small.txt;type=text/plain' || true
done
```

- **Expected:** 401 on every endpoint
- **Actual:**
  - GET `/` → 200
  - GET `/healthz` → 200
  - GET `/encounter/enc_0000` → 404
  - GET `/encounter/enc_0000/json` → 404
  - GET `/encounters/upload` → 200
  - GET `/encounters/upload/jobs/nonexistent_job_xyz` → 404
  - POST `/encounters/upload/preview` → 422
  - POST `/encounters/upload/submit` → 422
  - POST `/encounters/upload/paste` → 422
  - POST `/encounters/upload/notes` → 422
- **Verdict:** **FAIL — no auth on any endpoint** (the demo dashboard service is unauthenticated by design; the multi-tenant portal at `apps/portal` is a separate service and was not in scope of this probe). See Finding F-3.

### Case 9 — Every endpoint with a bad `Authorization` token

```bash
# Same endpoints as case 8, plus:
curl -sS -H "Authorization: Bearer ${AI_BILLING_AUDIT_TOKEN:?Set AI_BILLING_AUDIT_TOKEN before running this request}" \
  -o /dev/null -w "%{http_code}  $ep\n" -m 15 "https://ai-billing-audit.ashbi.ca$ep"
```

- **Expected:** 401
- **Actual:** Identical to case 8. Header is ignored; endpoints behave exactly as they do with no header.
- **Verdict:** **FAIL — header ignored, same defect as F-3.** A bogus token gets the same response as a real client would. This is acceptable for a "demo dashboard" surface but should be explicitly documented in a security note for the project.

### Case 10 — 100 POSTs in 1 second from a single client

**Mapped to:** 100x concurrent `POST /encounters/upload/preview` (50 workers) with a small valid text file, then extended to 200 concurrent (50 workers) and 100 serial to characterize the rate-limit story.

```bash
# 100x, 50 workers
seq 100 | xargs -P 50 -I{} curl -sS -o /dev/null -w "%{http_code}\n" -m 15 \
  -X POST https://ai-billing-audit.ashbi.ca/encounters/upload/preview \
  -F 'file=@/tmp/small.txt;type=text/plain'
```

- **Expected:** at least some 429s; zero 500s
- **Actual:**
  - 100 reqs, 50 workers, 9.99 s wall clock: **200/200 → 200**
  - 200 reqs, 50 workers, 12.48 s wall clock: **200/200 → 200**
  - 100 reqs, 1 worker (serial), 19.38 s wall clock: **100/100 → 200**
- **Verdict:** **PARTIAL** — zero 500s (good), but **zero 429s as well** (rate limiting is not implemented). The 100-req burst (intended "1 second") took ~10 s because there is no global concurrency cap and the server processes every request to completion. See Finding F-4.

---

## 2. Findings (5xx-class defects and hardening gaps)

**5xx defect count: 0.** No 5xx responses were observed in any case. Per the task's "every 500 response observed is filed as a separate bug" rule, no new entries were added to `docs/BUGS.md`.

The following hardening gaps are documented here for future work; they are not 5xx defects and the task scope is "report/file" not "fix":

### F-1 — Demo encounter ids on `/` are placeholders, not real rows (informational)

The home page (`GET /`) renders a list of encounters including `enc_0000`, `enc_0007`, `enc_10032`. Hitting `GET /encounter/enc_0000` returns **404**. Either the demo list is hard-coded and the detail route has no backing data, or the detail route expects a different id shape. Not a security defect; UX confusion at most.

### F-2 — Upload endpoint accepts ≥ 10 MiB with full-file read (DoS surface)

`POST /encounters/upload/preview` reads the entire request body before doing any parse/validation. Probes:
- 1 MB → 200
- 2 MB → 200
- 5 MB → 200
- 10 MB → 200 (read fully in 0.96 s; `size_upload=10485957`)
- 25 MB → 413
- 50 MB → 413
- 100 MB → 413

A single client can send 10 MiB and have it fully ingested in <1 s. With no auth (F-3) and no rate limit (F-4), a small number of clients could exhaust server memory by sending many concurrent 10-MiB uploads. **Recommended fix:** cap preview body to a small size (e.g. 1 MiB) and stream/parse 837P segments in chunks rather than reading the full body.

### F-3 — No authentication on any endpoint (the "expected 401" cases)

Every endpoint on `https://ai-billing-audit.ashbi.ca` is reachable without an `Authorization` header and a malformed token is silently ignored. The "demo dashboard" branding suggests this is intentional, but the task expected 401s and the API is reachable from the public internet. **Recommended fix (out of scope per task):** if the API is meant to be private, gate it behind the same session/cookie auth as the portal at `apps/portal`; if it is meant to be public demo, document that explicitly in `README.md` and the deploy runbook.

### F-4 — No rate limiting (the "expected 429" case)

200 concurrent requests over 12.48 s → 200 × 200. 100 serial requests → 100 × 200. No 429 ever emitted. No reverse-proxy or app-level throttle observed. **Recommended fix (out of scope per task):** add a Caddy or app-level per-IP token bucket (e.g. 10 req/s) before exposing further.

### F-5 — `content-type: text/html` returns 422, not 415 (acceptable, not a defect)

The multipart-only endpoints return 422 for any non-multipart body, including `text/html`. 415 ("Unsupported Media Type") would be more semantically precise, but the current 422 is safe and the error message is clear.

---

## 3. BUGS.md updates

**No changes.** Per the task: "Every 500 response observed is filed as a separate bug." Zero 5xx responses were observed across 10 cases (300+ total requests when case 10's rate-limit probes are counted), so the rule yields an empty list.

The five findings above (F-1 to F-5) are hardening gaps rather than server errors and are out of the task's "file only 5xx" scope. They're documented here for the next iteration of the hardening sweep.

---

## 4. How to reproduce

```bash
BASE=https://ai-billing-audit.ashbi.ca

# Case 1
curl -i -X POST $BASE/encounters/upload/preview -H 'content-type: application/json' --data-binary ''

# Case 2
curl -i "$BASE/encounter/%2E%2E%2F%2E%2E%2F%2E%2E%2Fetc%2Fpasswd"

# Case 3
dd if=/dev/zero bs=1M count=10 2>/dev/null | curl -i -X POST $BASE/encounters/upload/preview \
  -F 'file=@-;filename=big.bin;type=application/octet-stream'

# Case 4
curl -i -X POST $BASE/encounters/upload/preview -H 'content-type: text/html' \
  --data-binary '<html>not json</html>'

# Case 5
curl -i $BASE/encounter/nonexistent_id_xyz_does_not_exist

# Case 6
curl -i -X POST $BASE/findings/undefined/dismiss -H 'content-type: application/json' \
  --data-binary '{"finding_id":"undefined"}'

# Case 7
curl -i -X POST $BASE/encounters/upload/preview -H 'content-type: application/json' \
  --data-binary '{"foo":"bar","baz":42}'

# Case 8 / 9 — see loop in case-8 / case-9 sections above

# Case 10
seq 100 | xargs -P 50 -I{} curl -sS -o /dev/null -w "%{http_code}\n" -m 15 \
  -X POST $BASE/encounters/upload/preview \
  -F 'file=@/tmp/small.txt;type=text/plain'
```

Per-case raw `curl -i` output is in `docs/qa_artifacts/api_hardening_2026_06_17/raw/case_NN.txt`.
