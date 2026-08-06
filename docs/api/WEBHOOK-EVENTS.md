# Zorva Webhook Event Catalog

> **Version:** v1 (matches the `_KNOWN_EVENTS` set in `src/ai_billing_audit/webhooks.py`)
> **Date:** 2026-06-25
> **Audience:** EHR / billing-system integrators, Zapier / Make / n8n users, internal dashboard consumers
> **Status:** Stable — the v1 event set is frozen. New events add new names; existing events do not change payload shape without a versioned rename (`audit_complete.v2`, etc.).

This document lists every webhook event the Zorva public API emits today, the exact payload shape, and a copy-pasteable `curl` to subscribe. The authoritative source is `src/ai_billing_audit/webhooks.py`; this document is the integration-friendly mirror.

---

## 1. How subscriptions work

A clinic subscribes once per URL by calling `POST /v1/webhooks`. The API
appends a registration row to `/app/logs/webhooks.jsonl` (inside the
container) and returns a stable `webhook_id`. From then on, every event
the registration subscribes to is dispatched (best-effort) to the URL.

### 1.1 Register a webhook — `POST /v1/webhooks`

**Headers:**

| Header | Value |
|---|---|
| `Authorization` | `Bearer ${ZORVA_API_KEY}` |
| `Content-Type` | `application/json` |

**Body:**

```json
{
  "url": "https://your-app.example.com/zorva/in",
  "events": ["audit_complete", "finding_acknowledged"]
}
```

| Field | Required | Description |
|---|---|---|
| `url` | yes | Absolute http(s) URL. Empty strings are rejected. |
| `events` | yes | Non-empty list of event names (see §2). Unknown event names are accepted (forward-compat) but logged at WARNING and never fire. |

**Sample curl:**

```bash
curl -s -X POST https://zorva.ashbi.ca/v1/webhooks \
  -H "Authorization: Bearer ${ZORV...Y}" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-app.example.com/zorva/in",
    "events": ["audit_complete", "finding_acknowledged"]
  }' | jq
```

**201 response:**

```json
{
  "webhook_id": "wh_a1b2c3d4e5f6",
  "url": "https://your-app.example.com/zorva/in",
  "events": ["audit_complete", "finding_acknowledged"],
  "created_at": "2026-06-25T14:23:11Z",
  "tenant_id": "default"
}
```

**Errors:**

| Status | Body | When |
|---|---|---|
| 400 | `{"errors": ["url is required"]}` | URL is missing or empty |
| 400 | `{"errors": ["events must be a list of strings"]}` | events field is not a list of strings |
| 400 | `{"errors": ["malformed JSON: ..."]}` | Body is not valid JSON |
| 401 | `{"detail": "..."}` | Missing / bad API key |

### 1.2 Verify delivery signatures

The response reveals `signing_secret` once. Store it in the consumer's secret
manager; it is not returned by later reads. Every delivery includes:

| Header | Meaning |
|---|---|
| `X-Zorva-Delivery` | Unique delivery ID; persist it for replay protection. |
| `X-Zorva-Timestamp` | Unix timestamp in seconds. |
| `X-Zorva-Signature` | `v1=` followed by `HMAC-SHA256(secret, timestamp + "." + raw_body)`. |
| `X-Zorva-Event` | Event name; use it for routing only. |

Verify the raw bytes before JSON parsing, require the timestamp to be within
five minutes of the receiver clock, compare the HMAC in constant time, and
reject a delivery ID already present in the consumer's idempotency store. The
repository helper `verify_webhook_signature` implements this reference
contract and returns `False` for tampered, stale, malformed, or replayed input.

### 1.3 Delivery semantics

- **Transport:** HTTP POST, `Content-Type: application/json`, `User-Agent: zorva-webhook/1`, `X-Zorva-Event: <event-name>`.
- **Timeout:** 5 seconds per delivery attempt.
- **Retries:** none in v1. Failed deliveries (network error, timeout, non-2xx) are logged to `/app/logs/webhooks.jsonl` with `_kind: "delivery"` and never retried. The audit pipeline is never blocked by a webhook failure — `dispatch_event` catches all exceptions internally.
- **Idempotency:** every delivery carries `X-Zorva-Delivery`; persist that ID and reject it on replay. The payload also carries `audit_id` / `finding_id` for business-level deduplication.
- **Ordering:** events for the same audit / finding are delivered in emission order, but deliveries to different webhooks are sequential per dispatch. There is no global ordering guarantee.
- **Concurrency:** sequential (not parallel) by design. v1 has at most a handful of registered webhooks per tenant; parallelising would complicate error handling without a measurable latency win.

### 1.4 What your endpoint should do

1. Return 2xx as fast as possible — Zorva does not wait for slow handlers; a 5-second timeout will cut you off.
2. Persist the payload (`audit_id` + `data`) to your own queue, then return 200.
3. Dedupe on `audit_id` / `finding_id`.
4. Don't call Zorva back from inside the webhook handler (no nested fan-out).

---

## 2. Event catalog

| Event | Fired by | Payload size (typical) | Frequency (typical FP clinic) |
|---|---|---|---|
| `audit_complete` | `GET /v1/audits/{audit_id}` when status flips to `complete` | 1–4 KB | ~50/day |
| `finding_acknowledged` | Billler accept/edit/dismiss action on a finding | ~0.4 KB | ~200/day |

### 2.1 `audit_complete`

**Triggered when:** an audit job completes. In v1 the public API fires
this synchronously from the `GET /v1/audits/{audit_id}` poll endpoint
when the job status is `complete`. (See `src/ai_billing_audit/public_api.py`,
`dispatch_audit_complete_webhook_if_needed`.)

**Payload envelope** (added by `dispatch_event`):

```json
{
  "event": "audit_complete",
  "delivered_at": "2026-06-25T14:23:11Z",
  "data": { /* see below */ }
}
```

**`data` shape** (from `public_api.py:1006-1014`):

```json
{
  "audit_id": "aud_2026_06_25_abc123",
  "encounter_id": "enc_10032",
  "has_discrepancy": true,
  "findings": [
    {
      "rule_id": "rule_ahcip_modifier_25",
      "severity": "high",
      "quote": "Same-day procedure + E/M without -25 modifier",
      "suggested_code": "99213-25",
      "rationale": "Modifier -25 missing on problem-focused E/M line ..."
    }
  ],
  "findings_count": 1,
  "summary": "1 high-severity finding: missing modifier -25 on cryo + E/M."
}
```

| Field | Type | Always present | Notes |
|---|---|---|---|
| `audit_id` | string | yes | Use as idempotency key |
| `encounter_id` | string | yes | The clinical encounter the audit was run on |
| `has_discrepancy` | boolean | yes | `true` if `findings_count > 0`, `false` otherwise |
| `findings` | array | yes (may be `[]`) | One entry per finding the v12 auditor surfaced |
| `findings_count` | int | yes | `len(findings)` — provided for convenience |
| `summary` | string | yes | Human-readable one-line summary |

**Per-finding object:**

| Field | Type | Always present | Notes |
|---|---|---|---|
| `rule_id` | string | yes | One of the v12 rule IDs (see `docs/AHCIP_RULE_REFERENCE.md`) |
| `severity` | string | yes | `info` / `low` / `medium` / `high` / `critical` |
| `quote` | string | yes | The exact phrase from the note that triggered the finding |
| `suggested_code` | string | no | The recommended SOMB / OHIP code (omitted if no specific code applies) |
| `rationale` | string | no | One-sentence explanation of why the rule fired |

**Sample curl to subscribe + receive locally** (using a webhook.site
endpoint as a placeholder):

```bash
# 1. Register
curl -s -X POST https://zorva.ashbi.ca/v1/webhooks \
  -H "Authorization: Bearer ${ZORV...Y}" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://webhook.site/your-unique-id",
    "events": ["audit_complete"]
  }' | jq

# 2. POST a sample audit (use your real encounter id or 'sample-001')
curl -s -X POST https://zorva.ashbi.ca/v1/audits \
  -H "Authorization: Bearer ${ZORV...Y}" \
  -H "Content-Type: application/json" \
  -d '{
    "encounter_id": "sample-001",
    "note": "67M with productive cough x 5d, fever, bilateral rhonchi ...",
    "claim": {
      "codes": [{"code": "03.04A", "modifier": null}],
      "diagnosis_codes": ["J18.9"]
    }
  }' | jq

# 3. Poll for completion (triggers the audit_complete dispatch on flip to 'complete')
curl -s https://zorva.ashbi.ca/v1/audits/<audit_id_from_step_2> \
  -H "Authorization: Bearer ${ZORV...Y}" | jq

# 4. Check webhook.site — your endpoint received the audit_complete payload
```

**Zapier equivalent:** the Zapier connector exposes `audit_complete` as
a trigger. From inside a Zap, the payload is available under the
standard Zap data tree (`audit_id`, `encounter_id`, `findings[]`, etc.).
Use `findings_count` as the conditional ("only continue if > 0").

---

### 2.2 `finding_acknowledged`

**Triggered when:** a biller takes an action on a finding — accept,
edit, or dismiss — through the portal or the API. In v1 the public API
fires this from `POST /v1/findings/{finding_id}/action`.

**Payload envelope:**

```json
{
  "event": "finding_acknowledged",
  "delivered_at": "2026-06-25T14:24:03Z",
  "data": { /* see below */ }
}
```

**`data` shape** (from `public_api.py:1059-1065`):

```json
{
  "audit_id": "aud_2026_06_25_abc123",
  "encounter_id": "enc_10032",
  "finding_id": "fnd_a1b2c3d4",
  "action": "accepted",
  "tenant_id": "default"
}
```

| Field | Type | Always present | Notes |
|---|---|---|---|
| `audit_id` | string | yes | The audit that surfaced this finding |
| `encounter_id` | string | yes | Convenience — redundant with `audit_id` |
| `finding_id` | string | yes | Use as idempotency key (a biller may re-action the same finding) |
| `action` | string | yes | `accepted` / `edited` / `dismissed` |
| `tenant_id` | string | yes | For multi-tenant deployments; today always `default` |

**Sample curl to subscribe + a local listener:**

```bash
# 1. Register for both events
curl -s -X POST https://zorva.ashbi.ca/v1/webhooks \
  -H "Authorization: Bearer ${ZORV...Y}" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-app.example.com/zorva/ack",
    "events": ["finding_acknowledged"]
  }' | jq

# 2. POST a biller action
curl -s -X POST https://zorva.ashbi.ca/v1/findings/fnd_a1b2c3d4/action \
  -H "Authorization: Bearer ${ZORV...Y}" \
  -H "Content-Type: application/json" \
  -d '{ "action": "accepted" }' | jq

# 3. Your /zorva/ack endpoint receives the finding_acknowledged payload
```

**Zapier equivalent:** `finding_acknowledged` is exposed as a trigger
with `action` as a filter field. Typical Zap: "When finding_acknowledged
with action=accepted, add the encounter_id to a Google Sheet for the
weekly recovery report."

---

## 3. Verifying a delivery

Each delivery carries these headers — your handler can use them to
verify the request really came from Zorva:

| Header | Example | Notes |
|---|---|---|
| `Content-Type` | `application/json` | Always |
| `User-Agent` | `zorva-webhook/1` | Stable; bump on breaking v2 |
| `X-Zorva-Event` | `audit_complete` | The event name; matches `event` in body |
| `X-Zorva-Delivery-Id` | (planned v1.1) | Per-delivery UUID for dedupe |

The current v1 transport does **not** HMAC-sign the body. A future v1.1
will add `X-Zorva-Signature: sha256=<hmac>` and a per-webhook signing
secret (returned in the registration response as `signing_secret`). Plan
accordingly: the body shape is stable; the headers will gain one more
field.

---

## 4. Delivery log

Every dispatch attempt — success or failure — is appended to
`/app/logs/webhooks.jsonl` in the api container as a delivery row.
Two record shapes share the file:

**Registration row** (no `_kind`):

```json
{"webhook_id":"wh_abc123","url":"https://...","events":["audit_complete"],"created_at":"2026-06-25T14:23:11Z","tenant_id":"default"}
```

**Delivery row** (`_kind: "delivery"`):

```json
{"_kind":"delivery","webhook_id":"wh_abc123","event":"audit_complete","url":"https://...","status_code":200,"ok":true,"attempted_at":"2026-06-25T14:25:00Z"}
```

A failed delivery:

```json
{"_kind":"delivery","webhook_id":"wh_abc123","event":"audit_complete","url":"https://...","status_code":null,"ok":false,"error":"URLError: timeout","attempted_at":"2026-06-25T14:25:00Z"}
```

If you need to debug a missed delivery on your end, the simplest path
is to tail the log on the host (`docker compose logs api | grep
webhook`) or download the JSONL via the audit-trail export on the
dashboard.

---

## 5. Operational guidance

**How many webhooks should I register?** One. v1 dispatches every event
the registration subscribes to in a single POST. Multiple registrations
add latency without adding reliability.

**What if my endpoint is down for a few hours?** Missed deliveries are
logged but not retried in v1. The recommended pattern is: the receiving
service has its own durable queue; it returns 200 immediately after
enqueue; a background worker drains the queue and retries with backoff
on its side. Zorva's v1 contract is "we tried once, here's the attempt
log."

**Can I register the same URL twice?** Yes. Two registrations = two
deliveries per event. If you want idempotency, dedupe on `audit_id` /
`finding_id`.

**Can I update a registration?** v1 has no `PUT /v1/webhooks/{id}`. To
update, register a new one and remember the `webhook_id` you want to
keep. (A `PUT` route is on the v1.1 roadmap.)

**Can I delete a registration?** v1 has no `DELETE /v1/webhooks/{id}`
either. To unsubscribe, register the new set; the orphan will eventually
be GC'd via a future admin tool. If you need immediate effect, email
`support@ashbi.ca` with the `webhook_id` and we'll prune it.

**Does this work for HIPAA / PHIPA / HIA?** Yes — all event payloads
carry only the encounter-level identifiers and findings, never the raw
clinical note. See `docs/legal/PIA-TEMPLATE.md` for the full data flow
and `docs/legal/HIA-DPA-TEMPLATE.md` for the contractual safeguards.
