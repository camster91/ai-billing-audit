# Sales Demo Runbook

Print this page. Keep it next to the laptop on the call. Walk sections in order.

## 1. Open the live product

Go to **https://ai-billing-audit.ashbi.ca**. Sign in with the demo account Cam set up for the call. The home page is the audit dashboard — let the prospect see real numbers, not a screenshot.

## 2. The Stripe test card

When you click **Upgrade** on any plan, Stripe opens a checkout. Use this card — it always succeeds in test mode:

- Card number: **4242 4242 4242 4242**
- Expiry: any future date
- CVC: any 3 digits
- Postal code: anything

Tell the prospect: "This is a sandbox charge. No money moves. We use it so you can see the full checkout flow without paying."

## 3. The three plans

There are three flat monthly tiers — no per-claim fees, no percentage of collections:

| Tier | Price (CAD) | Audits / month |
|------|-------------|----------------|
| Small practice | $499 | 500 |
| Mid clinic | **$1,499** | 2,000 |
| Large practice | $2,999 | 5,000 |

**Pick the mid tier.** It covers 2,000 audits a month, includes up to 5 user seats, and carries the "Most clinics" badge on the pricing page. If the prospect is single-provider, start them on Small and let them upgrade after 30 days.

## 4. Sample claims to show

Open **`data/val.json`** in the repo (or the three canned 837P fixture files if that file is gone). These are the same claims the auditor scored during QA — easy / medium / hard. Pick one of each:

- **Easy** — clean claim, no findings. Shows the "we don't flag noise" story.
- **Medium** — one missing modifier, one diagnosis-code mismatch. Shows the typical 60-second win.
- **Hard** — unbundled procedure plus a payer-specific rule. Shows depth.

Pull the JSON into a tab so the prospect can see the raw input on the left, the auditor output on the right.

## 5. What to show in the split-screen review

Four steps. Slow down here — this is the moment they decide.

1. **Pick the medium-tier claim** from the list on the left.
2. **Click Run audit.** Watch the timer — typical run is under five seconds.
3. **Read the findings panel** out loud: "Missing modifier 25 on the E/M code, and the secondary diagnosis doesn't support medical necessity for the imaging." Point to the rule ID next to each finding.
4. **Click Export action plan (CSV).** Show that the deliverable drops straight into a billing-staff queue — no reformatting.

If they ask "what if the claim is clean?" — switch to the easy sample, run it, show the empty findings panel, say "and we don't invent problems to justify our fee."

## 6. The audit log (one sentence)

Every action the auditor takes is recorded in a permanent, signed log the prospect's privacy officer can hand to a regulator.

## 7. Do NOT promise

- No real patient data — every demo claim is synthetic.
- No "99% accuracy" or "99% recall" claim. We don't quote numbers we haven't measured.
- No "5-minute setup." Real onboarding is a half-day conversation with the prospect's billing lead.
- No per-claim pricing, no revenue share, no commission. The fee is a flat monthly rate.
- No Enterprise tier, no customer-managed keys. If they ask, say "not yet, tell us what you need."
