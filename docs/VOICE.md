# Zorva Brand Voice Guidelines

This document is the source of truth for how Zorva sounds in writing — across the
marketing site, the portal UI, security documentation, and every email a
customer, clinician, or partner might receive from us. When in doubt, default to
the rules here.

---

## 1. Voice summary

Zorva is **confident and specific**. We are a trustworthy medical-tech product for
clinics that bill public payers, not a salesy SaaS — we earn trust by naming the
number, citing the source, and showing our limits, not by reaching for the
superlative. The brand is allowed to be quiet; it is not allowed to be vague.

---

## 2. Audience

We write for three readers who overlap but are not identical:

- **Clinic billing leads** — know AHCIP/MSP/OHIP submission workflows, the pain
  of rejected claims, and the cost of a missed modifier. They do not need
  definitions of "appeal" or "undercode."
- **Privacy / compliance officers** — read the security page and the BAA before
  anyone else. They will quote our words back to legal.
- **Practice managers** — care about billable hours, recovered revenue, and
  whether the biller is still in the loop. They may not know what SOMB is and
  we should not make them feel like they should.

All three of these readers are professional, time-poor, and skeptical of vendor
language. Speak to them the way a senior colleague would speak across a desk.

---

## 3. Tone by context

| Surface | Tone | Rules of thumb |
| --- | --- | --- |
| Marketing pages (hero, pricing, features) | Specific, benefit-led, never hype | Lead with the concrete outcome. Quantify. If you cannot quantify, name the qualitative outcome plainly. |
| Technical pages (security, how-it-works, model card) | Precise, transparent, never hand-wavy | Cite the metric, the dataset, the test count, the data region. Never let a hedge ("robust", "enterprise-grade") substitute for a number. |
| Product UI (audit cards, findings, encounter details) | Concise, actionable, never vague | Two sentences max per finding. The biller needs to know what is wrong, why, and the next action. |
| Emails (welcome, weekly digest, doctor summary, appeal follow-up) | Warm, helpful, never pushy | The reader is busy and likely anxious about revenue. No urgency language, no fake countdowns, no "we noticed you haven't…" |

---

## 4. Ten do / don't pairs

Each pair shows a Zorva-voice line on the **Do** side and the overclaim we
refuse to ship on the **Don't** side.

| # | Do | Don't |
| --- | --- | --- |
| 1 | "catches 6–7 of 10 real billing errors before submission" | "catches all billing errors" |
| 2 | "identifies an average of $X in missed revenue per month, based on the 10-clinic pilot" | "saves you thousands" |
| 3 | "F1 = 0.690 on the Alberta AHCIP validation set" | "industry-leading accuracy" |
| 4 | "data stays in a Canadian data centre, region confirmed in the BAA" | "your data is 100% secure" |
| 5 | "the biller reviews every finding before the claim goes out" | "AI does the billing for you" |
| 6 | "tested on 791 automated tests + a 10-encounter AHCIP validation set" | "battle-tested on millions of claims" |
| 7 | "60-day no-cost pilot. After that, $499/mo. Cancel any time." | "free trial" |
| 8 | "built for Alberta clinics billing AHCIP. Ontario + BC pilots in development." | "works everywhere" |
| 9 | "see `docs/security` for the full compliance posture" | "HIPAA-certified" *(not true on our current hosting)* |
| 10 | "the model gets more accurate for your clinic over time, as it sees more of your encounters" | "self-improving AI" |

**Reading the pairs:** the Don't column is not "bad copy in general" — each one
is a phrase a writer is plausibly tempted to reach for. The Do column shows the
honest, quantified, or claim-bounded version we ship instead.

**The two anchor pairs we always ship verbatim:**

- Do: *"catches 6–7 of 10 real billing errors"* / Don't: *"catches all billing errors"*
- Do: *"catches 6–7 of 10 real billing errors"* / Don't: *"Saves you thousands"*

---

## 5. Vocabulary: use vs avoid

### Terms to use (technical pages)

- **SOMB** — Schedule of Medical Benefits. Use on `/security`, `/how-it-works`,
  and any model-card style page.
- **AHCIP** — Alberta Health Care Insurance Plan. The default jurisdiction; name
  it whenever we cite a number.
- **F1 / precision / recall** — use the actual numbers, not "high accuracy."
- **Appeal** — for the workflow of disputing a rejected claim.
- **Modifier-25** — the specific billing modifier our audit checks for.
- **Undercode** — when describing the missed-revenue pattern.
- **Validation set** — name the size (e.g. "10-encounter AHCIP validation set")
  alongside any metric.
- **BAA** — Business Associate Agreement. Use on the security page when
  describing PHI handling.
- **Pre-submit** — the moment we operate in; not "real-time" or "live
  monitoring."

### Terms to avoid

The following phrases are banned from Zorva copy. They are vague, they overclaim,
or they import SaaS-marketing language into a medical-tech product.

- **AI-powered** — every AI vendor uses this; it says nothing.
- **Magic** — we are auditable, not magical.
- **Enterprise-grade** — meaningless without a spec.
- **Robust** — use the actual failure rate or test count.
- **Cutting-edge** — name the model version and dataset instead.
- **Best-in-class** — claim this with a benchmark, or don't claim it.
- **Automated** — we assist the biller, we do not replace them.
- **Scalable** — name the throughput number (claims/hour, concurrent billers).
- **Cloud-native** — name the region and the hosting provider.

If a writer reaches for any phrase in the "avoid" list, the fix is almost
always to add a number, a source, or a scope.

---

## 6. Length guidelines

- **Hero headline:** ≤ 60 characters. One sentence, one concrete promise.
- **Sub-headline / hero paragraph:** ≤ 2 sentences, ≤ 200 characters total.
- **CTA button labels:** ≤ 30 characters (e.g. "Start 60-day pilot", "See
  pricing"). No "Get started today!" — no exclamation marks in CTAs.
- **Marketing page body:** ≤ 300 words per page. If it needs more, split the
  page; long marketing copy is a sign the page is doing two jobs.
- **Technical page body:** ≤ 600 words. Link out to `docs/security`,
  `docs/model-card`, etc. for the deep dives.
- **Finding explanations in the UI:** ≤ 2 sentences. Sentence 1 = what is
  wrong. Sentence 2 = what to do about it (or why we are flagging it).
- **Email subject lines:** ≤ 60 characters. No emoji. No all-caps.
- **Email body:** ≤ 250 words. One ask per email.

---

## 7. Sample copy in the Zorva voice

These are reference examples a writer can pattern-match against. All three are
written in the same voice; only the surface differs.

### 7.1 Hero paragraph (marketing)

> Zorva audits your Alberta AHCIP claims before submission and flags the
> modifier-25, undercode, and documentation gaps your biller would have caught
> — in roughly the time it takes to upload the encounter. On the 10-encounter
> validation set, we catch 6–7 of every 10 real errors. The biller reviews
> every finding before the claim goes out.

### 7.2 Pricing card description (marketing)

> **Pilot** — $0 for 60 days. Upload up to 500 AHCIP encounters; we flag
> findings; your biller reviews. After 60 days, the pilot converts to the
> Standard plan at $499/mo unless you cancel. No card required to start.

### 7.3 Finding explanation (product UI)

> **Modifier-25 not supported by the note.** The encounter note documents a
> problem-focused exam and a procedure on the same day, but does not include
> language that clearly supports a separately identifiable E&M. Add a
> statement of medical necessity, or remove the E&M code.

---

## 8. When in doubt

If a claim cannot be backed by a number, a source, or a named scope, **soften
it or cut it**. Zorva's brand promise is that the numbers we publish are the
numbers we can defend in a privacy review, a procurement call, or a regulator's
inbox. The fastest way to break that promise is to publish a claim we cannot
trace back to a file in this repo.
