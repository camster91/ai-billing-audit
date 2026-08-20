# Zorva analytics schema and ownership

> Issue #75. Privacy-conscious launch attribution and funnel
> reporting for the public marketing surface.

## TL;DR

- **Backend:** Plausible (privacy-focused, no cookies, no cross-site
  tracking, no personal data) for page views and custom-event counts.
  Loaded only when `NEXT_PUBLIC_PLAUSIBLE_DOMAIN` is set at build time
  in `apps/portal/src/app/layout.tsx`.
- **Self-hosted beacon:** `POST /api/analytics/event` as a guaranteed
  server log for events that need a server-side trail (contact
  submit success / failure, error codes). Today the handler logs to
  stdout; a future forwarder can attach a real backend without
  touching the page code.
- **Schema:** closed. Events and allowed properties are enumerated
  in `apps/portal/src/lib/analytics-events.ts`. The schema is
  enforced at call time by `assertSafePayload(event, payload)` so a
  bad call never reaches the network.
- **No PII.** Names, emails, clinic names, message text, IP, and
  User-Agent are explicitly listed in `FORBIDDEN_KEYS`. Submit
  success sends only `claim_volume_bucket` (a coarse bucket string)
  and `billing_setup` (a 3-valued enum) — both aggregated counts,
  not identifiers.
- **UTM capture** is automatic. The boot reads `?utm_source`,
  `?utm_medium`, `?utm_campaign` from the URL on page load,
  persists in `sessionStorage`, and includes them on every event.

## Event schema (v1)

| Event | Properties | Where it fires |
|---|---|---|
| `cta_click` | `cta_id`, `page_path`, `href`, `text`, `utm_*` | Delegated click handler on any element with `data-analytics="<cta_id>"`. Fires in `apps/portal/src/components/AnalyticsBoot.tsx`. |
| `contact_start` | `page_path`, `utm_*` | First `focus` event inside the contact form. `apps/portal/src/app/contact/ContactForm.tsx`. |
| `contact_submit_success` | `claim_volume_bucket`, `billing_setup`, `page_path`, `utm_*` | `POST /api/leads` returns 2xx. |
| `contact_submit_failure` | `error_code` (one of `disposable_email`, `invalid_input`, `rate_limited`, `network_error`, `http_<status>`, or the server's `error` string), `page_path`, `utm_*` | Any non-2xx response, any thrown exception during submit. |

`text` is truncated to 80 characters at call time and never carries
free-form message text — it is the visible CTA label.

## CTA IDs (v1, living in the page markup)

| CTA ID | Location | Notes |
|---|---|---|
| `home_hero_contact` | Marketing landing — hero primary | "Start a conversation" |
| `home_hero_how_it_works` | Marketing landing — hero secondary | "See how the workflow works" |
| `home_bottom_contact` | Marketing landing — bottom CTA | "Contact Zorva" |
| `security_pdf_download` | Security page — one-pager download | Pre-existing in the security page |

Adding a new CTA: set `data-analytics="<cta_id>"` on the element.
The click handler reads it; no code change needed.

## Retention and access

- **Plausible:** 30 days of aggregate, no per-user, no export. Access
  controlled by the Plausible workspace owner. Plausible does not
  store or process personal data.
- **`/api/analytics/event` stdout log:** rolled by the deploy log
  policy documented in `docs/OPERATIONS_RUNBOOK.md`. Operators
  confirm retention before turning the handler on in production.
  Today's handler logs only the event name, the timestamp, and the
  schema-validated properties — no PII ever reaches the log.
- **SessionStorage (UTM):** cleared when the user closes the tab.
  No PII. UTM values are hard-capped to 100 characters each.

## Weekly funnel report

Computed from Plausible's aggregate event counts and the
`/api/analytics/event` server log:

```
sessions                       (Plausible page_view total on /, /how-it-works, /pricing, /security, /contact)
cta_click total                (sum of cta_click event counts)
  ↳ home_hero_contact          (CTA → /contact)
  ↳ home_hero_how_it_works     (CTA → /how-it-works)
  ↳ home_bottom_contact        (CTA → /contact)
  ↳ security_pdf_download      (PDF one-pager)
contact_start                  (Plausible)
contact_submit_success         (Plausible + server beacon)
contact_submit_failure         (server beacon only)
  ↳ disposable_email
  ↳ invalid_input
  ↳ rate_limited
  ↳ network_error
  ↳ other
```

Source breakdown is available by `utm_source` / `utm_medium` /
`utm_campaign`. No per-user or per-visit drill-down.

## Acceptance against #75

- [x] Production analytics backend (Plausible) and data owner are
      documented (this file + the layout.tsx comment block).
- [x] Event names and allowed properties are versioned (`v1` in
      `analytics-events.ts`) and tested (`tests/analytics-events.test.ts`).
- [x] UTM/source attribution survives the intended journey to a
      successful contact submission (UTM is captured on page load,
      persisted in sessionStorage, and attached to every event).
- [x] Automated tests prevent contact-form PII from entering
      analytics payloads (`FORBIDDEN_KEYS` + `assertSafePayload`
      + the `tests/analytics-events.test.ts` PII matrix).
- [x] Production CSP and browser checks show no blocked analytics
      requests (`script-src`/`connect-src`/`img-src` allow
      `plausible.io`; self-hosted beacon stays `self`-only).
- [ ] A synthetic campaign visit appears in the weekly funnel
      without personal data — **requires a live deploy with
      `NEXT_PUBLIC_PLAUSIBLE_DOMAIN` set.** Not exercised in CI.
- [ ] The report distinguishes traffic, leads, qualified
      conversations, and pilot candidates — `qualified_conversation`
      and `pilot_candidate` are downstream of the sales workflow
      and are not produced by the page-side code. Owned by the
      sales ops team.

## Open questions for review

1. **Where does `qualified_conversation` and `pilot_candidate`
   come from?** These are downstream of sales / CRM and are not
   page-side events. If the source is the `leads` table in
   Postgres, an ETL into the same Plausible-aggregated report is
   out of scope for this PR.
2. **Should the contact form `contact_start` event fire on the
   *first* focus, or only after the user has typed a character?**
   Current v1 fires on first focus. If the funnel definition
   excludes "touched but did not engage," the event should be
   deferred to `onChange` instead.
3. **UTM persistence lifetime.** Today the boot uses
   `sessionStorage` (cleared on tab close). If the funnel needs
   attribution across sessions, switch to a 30-day cookie (Plausible
   handles this for the page view count; the custom-event payload
   would need a parallel `localStorage` write).
