# 10-minute onboarding-call script — Zorva pilot

> Kanban: t_68701d4f (C6) on board 'pilot-ready'. Owner: Eliud Gonzalez.
> Use this for the **first** call with a prospective pilot clinic's billing
> lead. Goal: figure out if the pilot is worth both sides' time, and if so,
> what the data-feed shape looks like. Hard stop at 10 minutes.

## Pre-call (60 seconds, on your end)

- Open the prospect's clinic website; note physician count + specialty mix.
- Check `docs/ALBERTA_PROSPECT_LIST.md` (or the relevant regional list) for
  any prior context on this clinic.
- Have `docs/PILOT_OFFER.md` open in a tab to share-screen if asked.
- Have `docs/DATA_AGREEMENT_TEMPLATE.md` ready to email after the call.

## Minute 0–2: intro + agenda

> "Hi [name], thanks for taking 10 minutes. Quick agenda: I want to
> understand your claim mix, where you think your biggest audit pain is,
> and whether a 30-day pilot would actually help. I'll keep us to 10
> minutes and follow up by email today. Sound good?"

If they want to skip the agenda, let them — prospects who want to talk
about a specific concern first are giving you the most useful signal.
Note the concern and circle back to the agenda items if there's time.

## Minute 2–5: claim mix + pain points

Ask, in order:

1. **Volume.** "How many claims do you submit per month? Per week?"
2. **Specialty mix.** "What's your dominant specialty — primary care,
   specialty, multi-specialty?"
3. **Current audit.** "What's your current pre-submit review process —
   is it manual, software-assisted, or none?"
4. **Top denial reasons.** "If you had to guess, what are the top two or
   three denial reasons you've seen in the last quarter? Modifier-25
   issues? Documentation? NCCI edits?"
5. **EHR / billing system.** "What EHR are you on, and what billing
   system — even if it's the same vendor?" (This drives the integration
   roadmap priority; log it.)

**Listen more than you talk.** The goal is to learn whether their pain
points overlap with what Zorva actually catches (modifier-25, missing
diagnoses, NCCI/MUE, E/M level). If they mention something we don't
cover (e.g. credentialing issues, payer contract negotiation), note it
as out-of-scope and offer a referral.

## Minute 5–7: pilot fit

If their answers line up with what we do, explain the pilot in 90 seconds:

> "Here's how the 30-day pilot works: we sign a BAA, you send us a
> sample of your last 100 claims (837P, CSV, or a FHIR Claim feed), and
> our auditor runs on those claims and produces a per-finding dashboard.
> We don't submit claims and we don't store the clinical notes beyond
> 30 days. At the end of the month we sit down with you and walk
> through every finding — what we caught that your team would have
> caught, what we caught that you wouldn't have, and where we got it
> wrong. No cost, no commitment."

If they push back on data-sharing:

> "Totally fair — we can do a shadow run on a fully-synthetic copy of
> your claim mix instead of the real claims. Less informative but
> useful for a first look. The full pilot with real data requires the
> BAA, which we have a template for."

If they ask about pricing, **do not quote specific numbers on the
first call.** Direct them to the one-pager
(`docs/ONE_PAGER_WHAT_WE_DO.md`) which has the three-tier table.

## Minute 7–9: data-feed shape + next steps

> "If we move forward, the next step is a 30-minute technical call with
> your IT contact to figure out the data feed. Two questions:
>
> 1. Can your billing system export 837P or CSV? (Most can.)
> 2. Is there a clinic-side IT contact who'd join that call?"

Capture both answers. Set up the technical call before hanging up if
they're keen; otherwise email within the hour to book it.

## Minute 9–10: close

> "Last thing — anything else I should have asked, or any concern I
> didn't address?"

Let them talk for 30 seconds. Then:

> "Great. I'll send you the BAA template and the pilot offer doc within
> the hour. [If keen:] let's get the technical call on the calendar —
> how's [two specific time slots] next week?"

End the call on time. Prospects respect the 10-minute hard stop; it
signals that we respect their time and that the rest of the pilot will
be similarly disciplined.

## After the call (within 60 minutes)

1. **Email 1** — the prospect: thank-you + BAA template + pilot offer
   doc + link to the one-pager.
2. **Email 2** — internally (Slack #pilots or `pilot-ready` kanban):
   one-paragraph summary of the call + the answers to the 5 questions
   above + the agreed next step (technical call date, or "no fit, log
   reason").
3. **CRM update** — log the call outcome in whatever system Cam /
   Eliud are using; tag with clinic name + specialty + volume.

## What to do if the call goes long

If the prospect is talking past 10 minutes and you can't politely
close, **politely close**:

> "I'm going to have to run in 30 seconds — can I follow up by email
> on [the open question]? I want to give you my full attention on the
> technical call next week."

If they keep going past 10 minutes and you can't get a word in, mute
and send yourself a note to follow up. The pilot is supposed to be
disciplined; a 35-minute first call is a bad signal.

## Red flags to watch for

- **"We just want a quote first."** → Send the one-pager, offer to
  book a 10-minute follow-up after they've read it. Don't quote
  numbers without understanding the claim mix.
- **"Can you handle our credentialing too?"** → Out of scope. See
  `docs/ANTI_FEATURES.md` §6.
- **"We need it integrated with [EHR] tomorrow."** → Honest answer:
  direct integrations are 2-4 weeks. CSV upload is available
  immediately. If they can't wait, this isn't a fit.
- **"What's your data-breach history?"** → Be honest: zero breaches
  to date. Point them to `docs/SECURITY_ONEPAGER.md` and the BAA
  breach-notification clause (60 days under HIPAA, 5 business days
  under PHIPA).

## What good looks like

A good first call ends with:
- A booked technical call OR a clear "not right now, here's why."
- An email sent within 60 minutes.
- A one-paragraph internal log.
- A clear next step that doesn't require chasing.
