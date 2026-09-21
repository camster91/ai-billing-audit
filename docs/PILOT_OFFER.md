# 60-Day Pilot — AI Claims Audit

**CAD $1,500 one-time. No auto-conversion. Credited against your first month
if you continue.**

We're offering a 60-day pilot of our claims-audit product to Alberta clinics.
One flat fee, no contract beyond the pilot itself, and you can walk away at the
end — at which point we delete everything you shared with us. This page is
what we'd hand to your billing lead.

**Decision recorded 2026-09-20.** Earlier drafts of this page quoted no
pilot fee at all, and the pricing page and other sales documents each
described different terms (60 days with no fee, 30 days with no fee, or no
fee followed by a monthly charge). The offer is now a paid pilot: a clinic
that pays has told us something real, and a clinic that pays nothing has
not. Any document that still describes an unpaid pilot is out of date.

---

## 1. What you get

- A full audit of your last **100 claims** — we run the same auditor your peers
  use in production.
- **Dashboard access** for the pilot period: see findings, claim scores, and the
  recommended action plan for each claim.
- An exportable action plan (CSV) your billing staff can drop straight into
  their workflow.
- A 30-minute review call with us at the end of the pilot to walk through every
  finding.

## 2. What it costs

- **CAD $1,500, one time, for the 60-day pilot.** Invoiced at the start of the
  pilot. No per-claim charges, no setup fee.
- **Credited against your first month** if you continue onto a subscription
  after the pilot. In effect, a clinic that continues pays nothing extra for
  the pilot.
- **No automatic conversion.** The pilot ends at day 60 unless you choose to
  continue in writing. Nothing renews itself and no card is kept on file.
- **Ongoing tiers** after the pilot start at $499/month; see `/pricing`.

**Not ready for a pilot?** We'll audit 100 **de-identified** claims at no charge
and send back a one-page finding-by-finding report — no fee, no follow-up unless
the report is useful. That sample report is a separate offer from the pilot and
is deliberately free; it is how a billing lead decides whether the pilot is
worth paying for.

## 3. What we get

- **Real-world data for R/P validation** — your claims help us calibrate the
  auditor on patterns we don't see in synthetic data.
- A **testimonial** from your billing lead at the end of the pilot — only if
  you're happy with the result. If you're not, no ask.

## 4. Data handling

- **Encrypted in transit** — TLS 1.3 on every connection to the dashboard and
  the upload endpoint.
- **Encrypted at rest** — claims and findings are stored in encrypted storage;
  decryption keys are scoped to the pilot tenant.
- **Deleted on request** — at the end of the pilot, on one email from your
  billing lead, we delete every claim, every finding, and every audit log entry
  within 7 business days. We send a written confirmation.
- **Never shared with third parties** — no subcontractors, no analytics resale,
  no model-training data sales. Your data stays in your tenant.
- **Data residency** — hosted on a Canadian VPS (`ca-central-1`). Note that the
  LLM provider is outside Alberta; that cross-border disclosure is flagged in
  the HIA agreement (section 4 and Appendix A) and must be reviewed by your
  privacy officer before any data moves.

## 5. Timeline (60 days)

- **Weeks 1–2 — Connect.** We sign the HIA Information Manager Agreement, get a
  read-only data feed or sample file from your billing system, and stand up your
  dashboard.
- **Weeks 3–6 — Shadow run + weekly review.** The auditor runs alongside your
  normal process. We collect findings, you collect results, and we meet weekly
  to walk through what the system caught and missed.
- **Weeks 7–8 — Measure and decide.** We measure the lift against your day-30
  baseline, write up the ROI, and you decide whether to roll Zorva out to the
  rest of the practice. If you don't continue, we delete your data per the
  commitment in section 4 and part as friends.

## 6. The only ask

- **One 10-minute call** with your billing lead at the start, so we understand
  your claim mix and where the audit pain actually lives.
- **A signed HIA Information Manager Agreement before any data moves.** We have
  a template ready. Your compliance team reviews it, signs it, and only then
  does the first byte of claim data leave your building.

---

**Ready to start, or just want to ask a few questions first?**

Reach out to **Eliud Gonzalez** — he's the one running this pilot for us. He'll
get you the HIA agreement template, schedule the 10-minute call, and answer
anything that's still unclear.
