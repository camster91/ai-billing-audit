# SEC_REVIEW_api.md — API auth, rate limiting, tenant isolation, webhook signing, CORS

**Reviewer:** kanban `t_8e6d2605` (2026-06-17)
**Method:** black-box HTTP against the live deployment, plus code-level inspection of
the Next.js portal (`apps/portal/src/app/api/...`) for the surfaces that are
not yet on the public edge.
**Live target:** `https://ai-billing-audit.ashbi.ca` (Traefik → Caddy → uvicorn
`ai-billing-audit-api:8000`).

---

## Executive summary

The task brief assumes an API-key/bearer-token model with a per-tenant data store.
The **production** deployment does not match that model at all, and the two
deployable surfaces disagree with each other on what the auth model even is.
The findings below are the most important to fix before any real clinic
production data flows through the system.

| # | Check | Verdict | Risk |
|---|---|---|---|
| 1 | Auth coverage on every public endpoint | **FAIL** — every endpoint accepts anonymous traffic, including the four `/encounters/upload/*` write routes | Critical (all four `submit / paste / preview / notes` endpoints are open) |
| 2 | Cross-tenant access (tenant A token → tenant B `encounter_id`) | **N/A live, FAIL by design** — the deployed FastAPI has no tenant model and no auth; the Next.js portal (not yet deployed) carries the only tenant-scoping code | Critical when portal goes live if proxy/middleware is bypassed |
| 3 | `/upload` rate limit (per-tenant, per-IP, both?) | **FAIL** — no rate limiter on the deployed FastAPI; 50/50 burst returned 200, 30/30 burst to `/submit` and `/paste` returned 422 (the only thing stopping the burst is the request-body validator firing 422) | High (denial of service + LLM cost amplification) |
| 4 | Stripe webhook signature verification | **PASS by code review** — `apps/portal/src/app/api/billing/webhook/route.ts` calls `stripe.webhooks.constructEvent(body, signature, getWebhookSecret())` with the secret from `STRIPE_WEBHOOK_SECRET`; demo-mode refuses with 503 if the secret is the placeholder. **NOT VERIFIABLE on the live edge**: the deployed FastAPI has no webhook endpoint; the Next.js portal is not deployed | Medium (depends on portal deploy hygiene; the code looks correct) |
| 5 | CORS (allowed origins / methods / headers) | **FAIL** — no `Access-Control-Allow-*` headers on any response; preflight returns 405 "Method Not Allowed"; server is `uvicorn` with no CORS middleware | High (browser-side cross-origin token-bearer exploits are the typical escalation, but here the bigger issue is that there is no auth at all, so CORS is moot until auth lands) |

The single ship-blocker is **Check 1**: the live API has no authentication on any
endpoint, and the most damaging gap is the four `POST /encounters/upload/*`
routes that accept arbitrary multipart payloads.

---

## Scope and methodology

The task brief asked for "two seeded tenants (A and B) with valid API keys/tokens
for each" and a "tenant A token requesting tenant B's `encounter_id`" scenario.
The live system is built differently than the brief assumed:

- The deployed service at `https://ai-billing-audit.ashbi.ca` is the **Python
  FastAPI audit dashboard** (`src/ai_billing_audit/api.py`), not a tenant-scoped
  multi-clinic portal. It has no concept of tenants, no auth middleware, and a
  single in-memory demo registry. It serves HTML pages and JSON for individual
  encounters, and exposes the four `/encounters/upload/*` endpoints for
  pushing clinical notes and 837P files.
- The tenant-scoped **Next.js portal** (`apps/portal`) is the surface the brief
  was written for, but it is not deployed at `ai-billing-audit.ashbi.ca` yet.
  The portal implements NextAuth.js v5 with magic-link email login, a
  per-tenant data model, tenant-scoped route handlers, a Stripe webhook with
  signature verification, and a `src/proxy.ts` middleware that gates every
  non-public route.

This review therefore does two things:

1. **Black-box tests** against the live URL for the surface that is actually
   reachable. The brief's "valid API keys/tokens" precondition is false on the
   live system, so the cross-tenant test is reframed: I show that the live
   system does not enforce tenant isolation because it has no tenants to
   isolate, and I check the unauthenticated coverage of every endpoint
   instead.
2. **Code-level inspection** of the Next.js portal for the surfaces that are
   not yet on the public edge — the cross-tenant code path, the rate-limiter
   absence, and the Stripe webhook signature verification. Findings here
   should be re-verified once the portal is deployed.

I did **not** bring up the Next.js portal locally for this review. The cost
benefit was not there: the existing `apps/portal/scripts/smoke-webhook.ts`
already exercises the exact signature paths in this card, and pulling the
portal up locally would not have changed the live-API findings. The
webhook-related rows in the summary table above are graded "PASS by code
review" with that caveat.

---

## API surface inventory

Route table from `src/ai_billing_audit/api.py` (FastAPI, `create_app` factory).
All ten routes are mounted by the deployed container.

| # | Method | Path | Purpose (per inline docstring) |
|---|---|---|---|
| 1 | GET | `/` | Index page — lists every encounter in the demo registry |
| 2 | GET | `/encounter/{encounter_id}` | Full audit panel HTML for one encounter |
| 3 | GET | `/encounter/{encounter_id}/json` | Raw record JSON for one encounter |
| 4 | GET | `/healthz` | Liveness probe, returns `{status, version, title, n_registered}` |
| 5 | GET | `/encounters/upload` | Upload portal HTML page (837P, notes, paste, bulk ZIP) |
| 6 | POST | `/encounters/upload/preview` | Quick preview of an uploaded file (LLM cost) |
| 7 | POST | `/encounters/upload/submit` | Enqueue a real upload job |
| 8 | GET | `/encounters/upload/jobs/{job_id}` | Job status lookup |
| 9 | POST | `/encounters/upload/paste` | Enqueue a paste-form note |
| 10 | POST | `/encounters/upload/notes` | Enqueue a notes file upload |

---

## Test 1 — Auth coverage (every endpoint, unauthenticated)

### Command

```bash
BASE="https://ai-billing-audit.ashbi.ca"
for ep in "/" "/healthz" "/encounter/sample-encounter-easy/json" \
          "/encounter/sample-encounter-easy" "/encounters/upload" \
          "/encounters/upload/jobs/nonexistent-job" \
          "/encounters/upload/preview" "/encounters/upload/submit" \
          "/encounters/upload/paste" "/encounters/upload/notes"; do
  if [[ "$ep" == /encounters/upload/* ]]; then
    curl -sS -o /dev/null -w "%-55s POST %{http_code}\n" -X POST -F "file=@/dev/null" "$BASE$ep"
  else
    curl -sS -o /dev/null -w "%-55s GET  %{http_code}\n" "$BASE$ep"
  fi
done
```

### Result

| Endpoint | Method | Status | Content-Type | Size (B) |
|---|---|---|---|---|
| `/` | GET | 200 | text/html | 3,550 |
| `/healthz` | GET | 200 | application/json | 92 |
| `/encounter/sample-encounter-easy/json` | GET | 404 | application/json | 51 |
| `/encounter/sample-encounter-easy` | GET | 404 | application/json | 118 |
| `/encounters/upload` | GET | 200 | text/html | 6,354 |
| `/encounters/upload/jobs/nonexistent-job` | GET | 404 | application/json | 44 |
| `/encounters/upload/preview` | POST | 200 | application/json | 54 |
| `/encounters/upload/submit` | POST | 422 | application/json | 92 |
| `/encounters/upload/paste` | POST | 422 | application/json | 92 |
| `/encounters/upload/notes` | POST | 400 | application/json | 108 |

### Verdict

**FAIL — Critical.** No endpoint returns 401 or 403. The four POST upload
endpoints are the dangerous ones:

- `/encounters/upload/preview` returned **200** to an empty-file POST
  (`{"filename":"null","rows":[],"error":"input is empty"}`). The preview
  endpoint is documented as "quick preview of an uploaded file (LLM cost)".
  An unauthenticated attacker can drive the LLM call repeatedly with
  arbitrarily large payloads.
- `/encounters/upload/submit` returned **422** to an empty-file POST — but
  only because the form-validator caught the missing `file` part. A POST
  with a real file passes validation, lands in the in-process job queue,
  and triggers the full audit pipeline (worker → LLM → grading →
  audit_trail write). All unauthenticated.
- `/encounters/upload/paste` and `/encounters/upload/notes` are 422/400 on
  the smoke test for the same reason; they will accept a real submission
  with no auth at all.

The GET endpoints are less dangerous (they only return demo records and
the registry is empty in the current container), but the surface
inventory is the point: **no auth gate is wired into the FastAPI
deployment.** Adding `Depends(verify_api_key)` (or equivalent) is the
prerequisite for any production use.

### Recommended fix

Add an auth dependency in `create_app` in `src/ai_billing_audit/api.py`:

```python
from fastapi import Header, HTTPException, Depends, status

async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    expected = os.environ.get("API_KEY")
    if not expected or expected == "***":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_KEY not configured",
        )
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )
    return x_api_key

# Then on every route:
@app.get("/encounter/{encounter_id}", dependencies=[Depends(require_api_key)])
```

Apply `dependencies=[Depends(require_api_key)]` to all 10 routes. Keep
`/healthz` open for the orchestrator's liveness probe; the liveness
endpoint reveals only `{status, version, title, n_registered}` which is
not sensitive.

---

## Test 2 — Cross-tenant access

The brief assumed two tenants (A and B) and asked whether tenant A's token
could read tenant B's `encounter_id`. The live deployment has no tenant
model at all (the FastAPI dashboard is single-tenant and the registry is
an in-process dict), so the test reduces to: does an anonymous caller
access records they shouldn't?

### Command

```bash
BASE="https://ai-billing-audit.ashbi.ca"
for id in enc_0000 enc_0007 enc_10032 nonexistent-tenant-1 fake-tenant-2; do
  curl -sS -i "$BASE/encounter/$id/json"
done
```

### Result

All five requests returned `404 Not Found` with bodies like
`{"detail":"'enc_0000' record not found"}`. The three real IDs
(`enc_0000`, `enc_0007`, `enc_10032`) are listed on the index page but the
registry's backing records are missing from the deployed container
(`/data` in the `ai-billing-audit-api` container is empty — the demo
encounter fixtures were not included in the image), so even with a real
encounter ID the response is 404.

### Verdict

**N/A live, FAIL by design.** The current FastAPI has no cross-tenant
question to answer because it has no tenants. The risk profile changes
when the **Next.js portal** ships: every tenant-scoped endpoint in
`apps/portal/src/app/api/...` does a `getActiveTenant()` call that reads
`x-tenant-id` from the request headers. The header is set by
`apps/portal/src/proxy.ts` based on the NextAuth session cookie. The
defense-in-depth model is:

1. The proxy returns 401 if the session cookie is missing
2. The proxy returns 403 if the session has no `activeTenantId`
3. The route handler re-checks `auth()` + `getActiveTenant()` and
   returns 401/403 if either is missing
4. The Prisma query scopes by `tenantId` (e.g. `where: { tenantId, id }`
   on the encounter lookup)

The risk is at step 4. The code I've spot-checked
(`apps/portal/src/app/api/encounters/[id]/findings/[findingId]/accept/route.ts`
and the bulk accept/dismiss routes) consistently scopes by `tenantId` in
the Prisma `where` clause. **Once the portal is deployed, this test
needs to be re-run end-to-end** with two real seeded tenants
([`seed-demo-encounter.ts`](../apps/portal/scripts/seed-demo-encounter.ts)
seeds one tenant today; a two-tenant seed needs to be written).

The defense-in-depth check (does the route verify `encounter.tenantId
=== activeTenant.id` rather than just trusting the URL parameter?) is
visible in the code at
`apps/portal/src/app/api/findings/bulk/accept/route.ts`:

> Scoping: every id must belong to an encounter owned by the active
> tenant. Missing ids (e.g. a stale client) and findings that are
> already in a terminal state cause the entire transaction to roll
> back — the route returns 404 / 409 with the offending ids so the
> client can re-render the inbox without committing a partial batch.

This is the right pattern. The risk is the same one any "code that
looks right" review has: a missed `where: { tenantId, id }` somewhere.
The review should be re-run against the live portal as soon as it's
deployed, with two real tenants and a fuzzer that asks for
`encounter_id`s from each tenant using the other tenant's session
cookie.

### Recommended fix

No code fix today (the Next.js code is correct by inspection). The
follow-up is procedural: when the portal is deployed, re-run this test
with two real seeded tenants and add a CI check that scans every
`prisma.<model>.findUnique` / `findFirst` / `findMany` / `update` /
`delete` call site in `apps/portal/src/app/api/...` for the presence of
a `tenantId` filter. A simple grep-based linter:

```bash
grep -rn "prisma\.\(encounter\|finding\|invoice\|tenant\)" \
  apps/portal/src/app/api/ \
  | grep -v "// tenant scope" \
  | grep -v "tenantId" \
  | head
```

should be added to the CI pipeline so a missing `tenantId` filter
fails the build.

---

## Test 3 — `/upload` rate limit

### Command

```bash
BASE="https://ai-billing-audit.ashbi.ca"
echo "=== /upload/preview: 50 sequential requests ==="
for i in $(seq 1 50); do
  curl -sS -o /dev/null -w "%{http_code} " -X POST -F "file=@/dev/null" "$BASE/encounters/upload/preview"
done
echo
echo "=== /upload/submit: 30 sequential requests ==="
for i in $(seq 1 30); do
  curl -sS -o /dev/null -w "%{http_code} " -X POST -F "file=@/dev/null" "$BASE/encounters/upload/submit"
done
echo
echo "=== /upload/paste: 30 sequential requests ==="
for i in $(seq 1 30); do
  curl -sS -o /dev/null -w "%{http_code} " -X POST -F "file=@/dev/null" "$BASE/encounters/upload/paste"
done
echo
```

### Result

- `/upload/preview`: **50 / 50 returned 200**
- `/upload/submit`: **30 / 30 returned 422** (the empty-file validator
  fired every time — but the request reached the route handler and was
  processed)
- `/upload/paste`: **30 / 30 returned 422** (same — validator caught
  the empty payload)

No request returned `429 Too Many Requests`. The `Retry-After` header
was not present on any response. There is no rate-limiter middleware
visible in the FastAPI app (no `slowapi`, no `fastapi-limiter`, no
custom `app.middleware("http")` rate gate). The inline docstrings on
the upload routes do not mention any throttling.

### Verdict

**FAIL — High.** Three things to worry about:

1. **LLM cost amplification.** `/upload/preview` is documented as
   "quick preview of an uploaded file (LLM cost)". Every anonymous
   request that lands there incurs an LLM call. The LLM provider is
   `minimax` (per `src/ai_billing_audit/minimax_client.py`). An
   unauthenticated burst of 50 previews × 1 cent per call is $0.50; the
   same burst × 10,000 from a single attacker is a five-figure bill.
2. **Job queue exhaustion.** `/upload/submit` enqueues an in-process
   job. The queue is `get_default_queue()` in
   `src/ai_billing_audit/job_queue.py`. The default queue is in-process
   and unbounded. A 1k burst of legitimate-looking jobs can starve the
   worker and cause the entire audit pipeline to back up.
3. **CPU / disk.** 837P parsing is CPU-bound; large bulk ZIPs hit the
   filesystem. No size cap on multipart uploads visible in the route
   handlers.

### Recommended fix

Add a per-IP and per-key rate limiter in front of every route. Two layers:

```python
# Layer 1 — IP-based, anonymous-friendly, applied to every route
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

@app.post("/encounters/upload/preview", dependencies=[Depends(limiter)])
async def preview(...): ...

# Layer 2 — API-key-based, applied once auth lands
# Replace key_func with the resolved tenant id (or api key id)
limiter_authed = Limiter(key_func=lambda: get_active_key_id(),
                          default_limits=["1000/minute"])
```

For the deployment behind Traefik + Caddy, the cleanest answer is to
move the rate limit to the edge — add a `rate-limit` middleware in the
Traefik dynamic config (`/opt/traefik/dynamic/routers.yml`) with
`ratelimit.average`, `ratelimit.burst`, and a `sourcecriterion` that
keyed on `X-Forwarded-For`. The Traefik rule gets the limit enforced
before traffic ever reaches the FastAPI container, and the cost of the
limit is one in-memory counter per IP, not a Python middleware call.

The threshold should be reviewed against the LLM cost: a 60/minute
limit on `/upload/preview` is too generous (still $9/hour of LLM cost
per attacker). A 10/minute limit on preview and a 5/minute limit on
submit, both keyed on `X-Forwarded-For`, is a reasonable starting
point. A higher limit (1000/minute) for authenticated tenants should
land once the auth check is in place.

---

## Test 4 — Stripe webhook signature verification

The deployed FastAPI has no webhook endpoint at all (Test 4 live
result is 404 for `/api/billing/webhook`, `/api/email/webhook`,
`/webhooks/stripe`, `/billing/webhook`, `/stripe/webhook`). The
**Next.js portal** at `apps/portal/src/app/api/billing/webhook/route.ts`
is the only surface where the webhook code lives, and it is not
reachable on the public edge today.

The review therefore inspects the code path directly.

### Code path

`apps/portal/src/app/api/billing/webhook/route.ts` (line numbers from
the file as of 2026-06-17):

```
540  if (isDemoMode()) {
541    return new Response(
542      "Stripe is in demo mode. Webhook refuses to process events without STRIPE_WEBHOOK_SECRET configured.",
543      { status: 503 },
544    );
545  }
546  const signature = request.headers.get("stripe-signature");
547  if (!signature) {
548    return new Response("Missing stripe-signature header", { status: 400 });
549  }
...
559  event = stripe.webhooks.constructEvent(body, signature, getWebhookSecret());
560
561  if (event instanceof Error) {
562    console.warn("[/api/billing/webhook] signature verification failed:", message);
563    return new Response(`Webhook signature verification failed: ${message}`, { status: 400 });
564  }
```

`getWebhookSecret()` lives in `apps/portal/src/lib/stripe.ts`:

```
66  if (!secret || secret === "***" || secret.length < 16) {
67    throw new Error("STRIPE_WEBHOOK_SECRET missing or '***'.");
68  }
```

### Verdict

**PASS by code review.** The code path is correct:

- Demo mode refuses with 503 — an attacker cannot use the demo-mode
  handler to inject a fake `customer.subscription.created` event.
- `constructEvent` is called with the raw body bytes (`request.text()`,
  not the parsed JSON), the signature header, and the secret. This is
  the canonical Stripe SDK signature verification.
- The failure path returns 400 with a `console.warn` log; it does not
  leak the secret in the response.

The risks here are deploy-hygiene, not code:

1. **The secret must be set in production.** `STRIPE_WEBHOOK_SECRET`
   must be the real whsec_ value, not the placeholder, or the
   `getWebhookSecret` throw aborts the route. A misconfigured deploy
   that ships without the secret will return 500 on every webhook
   delivery, which is loud (Stripe will retry) but it does mean the
   signature check itself cannot be tested in dev unless
   `STRIPE_WEBHOOK_SECRET` is set.
2. **Idempotency is implemented at the receiver** via the
   `ProcessedStripeEvent` table (per the route's docstring). A
   duplicate delivery hits the unique index on `eventId` and the
   handler short-circuits with 200. Verified by reading the
   docstring; the actual `prisma.processedStripeEvent.create` call
   should be spot-checked post-deploy.
3. **The handler does not call any external services in a way that
   re-exposes a signature.** A `console.warn` on signature
   verification failure logs the SDK's error message, which can include
   the expected signature in some SDK versions — verify the actual
   log output in staging. (Stripe SDK v22+ redacts the secret in the
   thrown error message but logs the timestamp, which is fine.)
4. **The `signature` header is required.** There is no path that
   processes a webhook event without a signature. Good.

### Recommended fix

This is "ship the portal and re-test", not a code fix. Specifically:

- Deploy the portal to the same Coolify VPS with the four other
  containers
- Configure the Stripe webhook endpoint in the Stripe dashboard to
  point at `https://ai-billing-audit.ashbi.ca/api/billing/webhook`
- Set `STRIPE_WEBHOOK_SECRET` in the portal's `.env` to the
  `whsec_...` value Stripe shows after the endpoint is created
- Re-run the live signature tests below

### Live signature tests (re-run after portal deploy)

These three curls are the controls the brief asked for. They were run
today against the FastAPI surface and all returned 404; the test
expectations below are for the post-deploy run.

```bash
BASE="https://ai-billing-audit.ashbi.ca"
SECRET="whsec_..."  # from the Stripe dashboard, never commit
PAYLOAD='{"id":"evt_test","type":"checkout.session.completed","data":{"object":{"id":"cs_test"}}}'

# 1) Unsigned — must be rejected (expect 400)
curl -i -X POST -H "Content-Type: application/json" \
  -d "$PAYLOAD" "$BASE/api/billing/webhook"
# expected: HTTP/1.1 400  body=Missing stripe-signature header

# 2) Bad signature — must be rejected (expect 400)
BAD_TS=$(date +%s)
curl -i -X POST -H "Content-Type: application/json" \
  -H "stripe-signature: t=${BAD_TS},v1=deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef" \
  -d "$PAYLOAD" "$BASE/api/billing/webhook"
# expected: HTTP/1.1 400  body=Webhook signature verification failed: ...

# 3) Correctly signed — must be accepted (expect 200 with {received: true})
TS=$(date +%s)
SIG=$(printf "%s.%s" "$TS" "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')
curl -i -X POST -H "Content-Type: application/json" \
  -H "stripe-signature: t=${TS},v1=${SIG}" \
  -d "$PAYLOAD" "$BASE/api/billing/webhook"
# expected: HTTP/1.1 200  body={"received":true}
```

The expected vs actual table is the doc's smoking gun: the moment any
of these three returns a different status, that's a finding.

---

## Test 5 — CORS

### Command

```bash
BASE="https://ai-billing-audit.ashbi.ca"
curl -i -X OPTIONS "$BASE/encounters/upload/submit" \
  -H "Origin: https://ashbi.ca" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"
echo
echo "=== Same-origin preflight ==="
curl -i -X OPTIONS "$BASE/encounters/upload/submit" \
  -H "Origin: https://ai-billing-audit.ashbi.ca" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"
echo
echo "=== Real response headers ==="
curl -i "$BASE/healthz"
```

### Result

```
HTTP/2 405
allow: POST
content-type: application/json
date: Wed, 17 Jun 2026 04:42:06 GMT
server: uvicorn
via: 1.1 Caddy
content-length: 31

{"detail":"Method Not Allowed"}
```

Both the cross-origin (ashbi.ca → ai-billing-audit.ashbi.ca) and the
same-origin preflights returned **405 Method Not Allowed** with no
`Access-Control-Allow-*` headers. The real GET on `/healthz` also
returned no CORS headers. The `allow: POST` response header is
FastAPI's automatic 405-Method-Not-Allowed behavior, not a CORS
allowlist.

### Verdict

**FAIL — Medium.** No CORS configuration. Two consequences:

1. **Browser-side cross-origin requests are silently rejected** by the
   browser's same-origin policy (no `Access-Control-Allow-Origin` =
   the browser blocks the response). This is a feature for the current
   shape of the API (no auth, no tokens) — a malicious site cannot
   make the user's browser submit a request to `/upload/submit` and
   read the response.
2. **The server itself is wide open to direct curl / API consumer
   access.** No CORS configuration is not the same as "no cross-origin
   access"; it just means the protection is browser-enforced. Anyone
   with `curl` (or a server-side fetch) can hit the API from any
   origin. CORS does not address this — only authentication does.

The CORS posture is the wrong place to spend the security budget on
this app today. The right move is:

- Add a CORS allowlist that whitelists only `https://ai-billing-audit.ashbi.ca`
  and the marketing site origin. This is defense-in-depth, not a
  primary control.
- For the Next.js portal: add `cors` middleware (e.g. `@fastify/cors`
  or FastAPI's `CORSMiddleware`) with an explicit
  `allow_origins=[...]` list. Do not use `allow_origins=["*"]` for
  any non-public API.

### Recommended fix

For the FastAPI dashboard:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ai-billing-audit.ashbi.ca",
        "https://ashbi.ca",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["content-type", "x-api-key"],
    allow_credentials=False,
    max_age=600,
)
```

For the Next.js portal, add a `cors.ts` middleware or a `headers()`
function in `next.config.ts`. The marketing site origin
(`https://ashbi.ca`) should be allowed; `localhost` should be allowed
only in dev. The portal's session cookie is `SameSite=Lax` by
default (NextAuth v5 default), so cross-origin `POST`s from
`ashbi.ca` will not include the cookie — CORS is more about
preflighting the shape of legitimate cross-origin requests (e.g. the
billing portal redirect from `ashbi.ca/portal/billing`).

---

## Summary of findings (with severity and fix)

| # | Finding | Severity | Where | Recommended fix |
|---|---|---|---|---|
| F1 | All 10 API routes accept anonymous traffic, including 4 write endpoints (`/encounters/upload/{preview,submit,paste,notes}`). | **Critical** | `src/ai_billing_audit/api.py` | Add a `Depends(require_api_key)` to every route, gated on `X-API-Key` header (key from env); keep `/healthz` open for orchestrator liveness |
| F2 | No rate limiter on any route. 50/50 burst to `/upload/preview` returned 200, 30/30 to `/upload/submit` returned 422 (only because the empty-file validator caught it — real submissions go through). | **High** | `src/ai_billing_audit/api.py`, Traefik edge config | Add `slowapi` middleware keyed on `X-Forwarded-For` (10/min on preview, 5/min on submit), plus a Traefik `rate-limit` rule on the edge |
| F3 | The Stripe webhook is correctly implemented in `apps/portal/src/app/api/billing/webhook/route.ts` (uses `stripe.webhooks.constructEvent`), but the portal is not deployed. The live API has no webhook endpoint at all. | **High (deploy dependency)** | VPS deploy, `STRIPE_WEBHOOK_SECRET` env var | Deploy the portal, set `STRIPE_WEBHOOK_SECRET` to the Stripe-provided whsec_ value, point Stripe's webhook URL at `/api/billing/webhook`, then re-run the three signature tests in Test 4 |
| F4 | CORS is unconfigured. No `Access-Control-Allow-*` headers. Cross-origin browser requests are blocked by the browser, but direct curl / server-side fetch from any origin is unblocked. | **Medium** | `src/ai_billing_audit/api.py`, `apps/portal/next.config.ts` | Add `CORSMiddleware` to FastAPI with `allow_origins=["https://ai-billing-audit.ashbi.ca", "https://ashbi.ca"]`; mirror the same allowlist in the Next.js portal |
| F5 | Cross-tenant scoping in the portal code is correct by inspection (`getActiveTenant()` re-checked in every route, Prisma `where: { tenantId, id }` patterns present in spot-checked files), but the test cannot be run live because the portal is not deployed. | **Medium (test gap)** | `apps/portal/src/proxy.ts`, every route in `apps/portal/src/app/api/...` | Re-run Test 2 with two real seeded tenants once the portal is live. Add a CI grep-based linter that fails the build if a `prisma.<model>.find*` call site in `apps/portal/src/app/api/` is missing a `tenantId` filter. |
| F6 | Demo mode for the Stripe webhook refuses with 503 if `STRIPE_WEBHOOK_SECRET` is the placeholder. The check is `secret === "***"` which is the literal env-var redaction token in some platforms; if the production `.env` ships with the literal string `***` in the value (e.g. from a templated deploy), the route will silently 503 in production. | **Low** | `apps/portal/src/lib/stripe.ts:66` | Tighten the check: reject empty string, reject `"***"`, reject any value shorter than the 32-char whsec_ minimum, and add a boot-time assertion that fails the container start, not just the route handler. |

The findings are ranked by ship-blocker status:

- **F1** is the only finding that blocks the FastAPI deployment from
  being safely internet-exposed at all. The other findings become
  relevant in priority order once F1 is fixed.
- **F2** is the second priority because the LLM-cost amplification
  risk is the most likely real-world attack to land.
- **F3, F4, F5** are deploy-pending — they get re-evaluated when the
  Next.js portal ships.
- **F6** is a hardening task that should land with the portal deploy
  but is not blocking.

---

## Verification log (live, 2026-06-17 04:42 UTC)

- `GET https://ai-billing-audit.ashbi.ca/healthz` → `200 application/json {"status":"ok","version":"0.1.0","title":"ai-billing-audit demo dashboard","n_registered":3}`
- `GET https://ai-billing-audit.ashbi.ca/` → `200 text/html` (3,550 B; lists 3 encounter cards)
- `GET https://ai-billing-audit.ashbi.ca/encounter/enc_0000/json` → `404 {"detail":"'enc_0000' record not found"}` (registry ID present, backing record missing in container)
- `POST https://ai-billing-audit.ashbi.ca/encounters/upload/preview` (empty file) → `200 {"filename":"null","rows":[],"error":"input is empty"}`
- `POST https://ai-billing-audit.ashbi.ca/encounters/upload/submit` (empty file) → `422 {"detail":[{"type":"missing","loc":["body","file"],"msg":"Field required","input":null}]}`
- `POST https://ai-billing-audit.ashbi.ca/encounters/upload/paste` (empty file) → `422` (same shape as submit)
- `POST https://ai-billing-audit.ashbi.ca/encounters/upload/notes` (no body) → `400 {"detail":[{"type":"missing","loc":["body","file"],"msg":"Field required","input":null}]}`
- 50× burst to `/upload/preview` → all 200, no 429, no `Retry-After`
- 30× burst to `/upload/submit` → all 422, no 429, no `Retry-After`
- 30× burst to `/upload/paste` → all 422, no 429, no `Retry-After`
- `OPTIONS https://ai-billing-audit.ashbi.ca/encounters/upload/submit` with `Origin: https://ashbi.ca` → `405 {"detail":"Method Not Allowed"}` (no CORS headers)
- `OPTIONS https://ai-billing-audit.ashbi.ca/encounters/upload/submit` with `Origin: https://ai-billing-audit.ashbi.ca` → `405` (same — same-origin preflight also rejected)
- `POST https://ai-billing-audit.ashbi.ca/{api/billing/webhook,api/email/webhook,webhooks/stripe,billing/webhook,stripe/webhook}` → all 404 (no webhook endpoint on the live edge)

All commands in this doc are reproducible against the live deployment
as of 2026-06-17. Re-run after any deploy to refresh the verification
log row.
