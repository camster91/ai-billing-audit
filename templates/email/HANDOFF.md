# Alberta outreach handoff — what to send this week

Three real-world blockers to a paying pilot have been closed in code. What's
left is Cameron's manual step: pick the prospect, find the right person, send
the email. This file is everything you need to do that in one sitting.

## Step 1 — pick the prospect (5 minutes)

From `docs/ALBERTA_PROSPECT_LIST.md`, the ranked top 3 are:

1. **Strathcona Primary Care Network (PCN central)** — Sherwood Park. One
   conversation with their operations director puts Zorva in front of 60–80
   member physicians. Best first call.

2. **Bow Valley Medical Clinic** — SW Calgary. 8–12 physicians, ~5–8K
   AHCIP claims/month, Telus PS Suite (verify). Strongest independent-clinic
   target if the PCN route stalls.

3. **Red Deer Primary Care Network (PCN central)** — central Alberta.
   Different ops director than Strathcona, can run in parallel.

Use the `alberta_pcn_v1.txt` template for the PCN central offices
(Strathcona, Red Deer), or `alberta_clinic_v1.txt` for an individual clinic
(Bow Valley).

## Step 2 — find the right person (10 minutes)

For a PCN: the operations director or executive director. Listed on the
"About" or "Team" page of the PCN website. For Strathcona that's
`strathconapcn.ca`; for Red Deer `reddeerpcn.com`. Use the `office@` or
`info@` address if no name surfaces.

For a clinic: the office manager. Listed on the "Contact" page of the
clinic website. For Bow Valley that's `bowvalleymedical.ca` (verify the
URL is still live — the prospect list was compiled 2026-06-22).

## Step 3 — fill the template (5 minutes)

Open the chosen template (`templates/email/alberta_pcn_v1.txt` or
`alberta_clinic_v1.txt`). Replace placeholders:

- `[First Name]` — first name of the person you're sending to
- `[PCN]` — full name of the PCN (e.g. "Strathcona Primary Care Network")
- `[a subset / all member]` — pick one based on what you negotiated
- `[calendly link]` — your real Calendly URL

## Step 4 — sanity-check before send (2 minutes)

- Subject line is the trigger event, not a self-promo: "60-day pilot —
  pre-submit AHCIP audit for [Clinic]" for a clinic, or "60-day pilot —
  pre-submit AHCIP audit for [PCN] member clinics" for a PCN.
- First paragraph is the audit finding (pre-submit, AHCIP, published v12
  benchmark ≈ 77 of 100 recall), not "I'm Cameron" — the audit-first
  opener is the rule.
- The pilot is paid: CAD $1,500 one-time, credited against the first month
  if they continue. Do not describe it as free or no-cost. The free
  100-claim sample report is a separate first-touch offer.
- One line of credentials: "Founder, Zorva · cameron@ashbi.ca" only.
- Signature line is contact info + the privacy brief URL so the privacy
  officer can self-serve.

## Step 5 — send via the Maton Gmail bridge (5 minutes)

The mavis Telegram bridge routes through mavis root — but for outbound
email, the Maton CLI is the right tool. From your Mac terminal:

```bash
maton google-mail message send \
  --connection <ashbi-gmail-connection-id> \
  --to "<recipient-email>" \
  --subject "<your subject line>" \
  --body "<the email body>"
```

The Ashbi Gmail connection is the one tied to `cameron@ashbi.ca` — find
the connection ID with `maton google-mail connection list`.

## Step 6 — log the lead in the portal (1 minute)

After sending, file the lead at `https://ai-billing-audit.ashbi.ca/admin/leads`
so the pipeline state is accurate. The Lead model already supports
`status`, `source`, `ownerUserId`, and `lastContactedAt` from the
W1.2 schema fix shipped 2026-06-28. Set:

- `status = "contacted"`
- `source = "cold_email_alberta"`
- `lastContactedAt = <today>`

If the prospect replies, the Lead model has a `dismissReason` field —
extend it to a new `replied_at` if you'd rather track the reply timestamp
as a separate field.

## What you don't need to do

The 4 product gaps that blocked a real pilot are all closed in code:

1. **Re-audit honors uploaded claim** — `test_reaudit_reconstructs_persisted_claim`
   in `tests/test_audit_endpoint.py` proves the runner persists the
   audit-ready claim on `Job.result['claim']` and the re-audit endpoint
   reads it back byte-for-byte. Kanban card t_10774785.
2. **PHIPA scrub for Alberta product** — `pricing.ts` now says
   "HIA-aligned audit trail (PIPEDA-compliant)" in all 3 tiers instead
   of the misleading "HIA/PHIPA-aligned". All 5 multi-jurisdiction
   explainer copy points at the live HIA + PIPEDA (Alberta / Canada)
   coverage, with HIPAA / PHIPA / NOM-024 correctly framed as
   on-request / 2027 roadmap.
3. **Data residency is honest** — the security page and home pillar no
   longer say "AWS ca-central-1". They say "region-pinned facility
   documented in the executed IMA" — accurate for an Alberta pilot
   where the actual hosting provider is documented in the IMA.
4. **Per-finding Accept / Dismiss is in production** — every finding
   on the encounter detail page has its own Accept button + Dismiss
   picker with reason. Routes `POST
   /api/encounters/[id]/findings/[findingId]/accept` and `.../dismiss`
   are wired and tested.

## What I (Mavis) cannot do for you

- Find the actual ops director's email — that's a manual look at
  strathconapcn.ca. The connection IDs in Maton are stored locally
  on your Mac, not in this session.
- Send the email — Maton `message send` requires your explicit
  approval for any write action (POST), per your hard rules.
- Negotiate the pilot — 10-minute call needs Cameron in the room.

## Rollout checklist

When you start sending:

- [ ] Send the Strathcona PCN email first (highest leverage)
- [ ] Send the Bow Valley clinic email second (independent fallback)
- [ ] Send the Red Deer PCN email third (geographic spread)
- [ ] File each in `https://ai-billing-audit.ashbi.ca/admin/leads`
  with `status="contacted"`, `source="cold_email_alberta"`,
  `lastContactedAt=<today>`
- [ ] After 5 business days with no reply, send the follow-up from
  `templates/email/cold_followup_v1.txt` (generic, not Alberta-specific
  — but the framework is "still interested?" + calendly link, not a
  fresh value pitch)

If you want me to do the next one (week-after follow-up template
Alberta-specific, the 5-day cadence reminder, or the
/try-on-portal seeding for the prospect's first 100-claim upload), say
the word.
