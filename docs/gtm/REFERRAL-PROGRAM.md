# Zorva Affiliate / Referral Program — Spec

> **Status:** draft v1. Cameron sign-off pending.
> **Owner:** Marketing (with engineering build in the next sprint).
> **Audience:** any doctor, biller, or clinic admin who refers a new
> paying customer to Zorva.

---

## 1. Why we are doing this

The two channels that have actually moved the needle for us so far
are (a) trade shows (Strathcona PCN, Calgary Health City) and (b)
word-of-mouth between doctors in the same specialty. Word-of-mouth
is higher-trust but slower because there is no incentive and no
tracking. The affiliate program turns that latent signal into a
measurable channel without spending on ads.

## 2. Reward structure

| Referred customer's tier | Reward to referrer | When paid |
|--------------------------|--------------------|-----------|
| Tier 2 (group / multi-specialty) | **$200 Amazon gift card** OR **1 month free on the referrer's tier** | 30 days after the referee's first successful audit |
| Tier 3 (enterprise) | **$500 Amazon gift card** OR **2 months free on the referrer's tier** | 30 days after the referee's first successful audit |
| Tier 1 (solo) | **$50 Amazon gift card** | 30 days after the referee's first successful audit |

**Pick-one rule:** the referrer chooses gift card OR service credit
once, at signup into the program. They cannot switch between
programs mid-stream; they can re-elect at the next annual review.

**Caps:** reward capped at **$5,000/year per referrer** (or 12
months service credit). Beyond the cap, additional referrals still
count toward the dashboard stats but earn no reward.

**No self-referral:** a referrer cannot refer themselves, their own
clinic, or any tenant in the same `tenant_group` they own.

**No stacking:** a referred customer can only be claimed by one
referrer. First-touch attribution.

## 3. Tracking — referral codes in URL params

Every referrer gets a unique code at signup into the program:

```
https://zorva.health/?ref=DRKIRK-7XQ
```

The code is also embeddable in a doctor-to-doctor text:

```
Hey, try Zorva for the SOMB catch rate — use my link:
https://zorva.health/start-pilot?ref=DRKIRK-7XQ
```

**Implementation:**

1. **Capture:** when a visitor lands on any page with `?ref=...`,
   set a first-party cookie `zorva_ref` (90-day TTL,
   `SameSite=Lax`, `Secure`).
2. **Attribution:** on `POST /api/onboarding/redeem` and on the
   first `POST /api/billing/checkout` for a new tenant, the cookie
   is read and stored as `Referral.attributedReferrerCode` on the
   tenant record. The cookie is cleared after first attribution.
3. **First-touch wins:** if the same visitor has multiple `?ref=`
   values over the 90-day window, the earliest wins.
4. **Rejection cases:**
   - Code does not exist or is revoked → silently ignored, lead
     captured normally.
   - Code refers to a tenant in the same `tenant_group` → rejected
     with `409` to the API caller, but the visitor still
     onboards.
5. **Visibility:** the marketing site footer (`/`, `/pricing`,
   `/compare`, `/pilot`) shows a small "Have a referral code?"
   link that pre-fills the field if a `?ref=` is present.

**Why URL params and not, e.g., a third-party affiliate network?**
Because the affiliate network would (a) drop a third-party cookie
which most browsers now block, (b) take 20–30% of the reward,
and (c) make the attribution story harder to explain to a clinic
auditor. Our volume does not justify the network fee yet.

## 4. The referrer dashboard

Built at `/referral/dashboard` (auth-required, role `owner` or
`auditor`).

### 4.1 What the referrer sees

- Their referral code (copy-to-clipboard).
- A share block with three pre-formatted messages:
  - Short SMS (under 160 chars).
  - Email template.
  - QR code (PNG download).
- Stats card:
  - Total clicks on the referral link (last 30 / 90 / 365 days).
  - Sign-ups attributed.
  - Conversions to paying tier.
  - Pending rewards (waiting on the 30-day maturation).
  - Paid rewards (lifetime).
  - Progress to the $5,000 / 12-month cap.
- A table of every attributed signup (de-identified): date,
  referred tenant's first 3 letters + region (so the referrer can
  recognize "Dr. Smith's clinic in Calgary" without us exposing
  the full identity), tier, reward status.

### 4.2 What the referee sees

- During onboarding, after the `redeem` step: "Referred by
  Dr. Kirk." No further UI; the referral is invisible to the
  referee from then on.

### 4.3 What the Zorva team sees

An internal-only `/admin/referrals` view with the full table,
filterable by referrer, by month, by reward status, and by tier.
Used for monthly payout reconciliation.

## 5. Reward fulfillment

- **Amazon gift card path:** Operations sends the gift-card code
  via the email on the referrer's account on the 30th day after
  the referee's first successful audit. Codes are purchased from
  Amazon Business in batches; we do not auto-email Amazon codes
  (no API integration with Amazon).
- **Service-credit path:** Operations extends the referrer's
  current subscription by 1 or 2 months via Stripe's
  `subscription.update` with `proration_behavior: "none"` so no
  proration is created. Recorded as a memo entry in the billing
  ledger.
- **Tax handling:** gift cards over $500/yr trigger a 1099-NEC /
  T4A slip at year-end (US/CA). The referrer dashboard shows
  running total YTD.
- **Refunds:** if the referee refunds within 30 days, the reward
  is reversed. If already paid, Operations claws back by reversing
  the next month's service credit, or by invoicing the referrer
  for the gift-card amount if no further credit is available.

## 6. Anti-abuse

- New tenant + new payment method within 7 days of `?ref=` click is
  flagged for Operations manual review.
- Two or more referred tenants sharing the same bank-card last4
  → flag.
- Referrer who refers 5+ tenants in any 30-day window → manual
  review before next payout.
- Tenants in the same `tenant_group` (corporate family) as the
  referrer are auto-excluded.

## 7. Build plan (engineering)

| Sprint | Deliverable | Notes |
|--------|-------------|-------|
| Sprint 1 (current next) | `Referral` Prisma model + cookie capture + `redeem` hook | Schema-only change; no UI yet |
| Sprint 2 | `/referral` public landing + signup-into-program flow | Marketing page + simple form |
| Sprint 3 | `/referral/dashboard` for referrers | Stats + share block + de-identified table |
| Sprint 4 | `/admin/referrals` + reward-fulfillment workflow | Operations-facing |
| Sprint 5 | Cap enforcement + tax tracking + Stripe service-credit integration | Hardens the program |

The `Referral` model:

```prisma
model Referral {
  id                String   @id @default(cuid())
  code              String   @unique          // e.g. "DRKIRK-7XQ"
  referrerUserId    String
  referrerTenantId  String
  createdAt         DateTime @default(now())
  revokedAt         DateTime?

  attributions      ReferralAttribution[]

  @@index([referrerUserId])
}

model ReferralAttribution {
  id                    String   @id @default(cuid())
  referralId            String
  referredTenantId      String   @unique       // first-touch wins
  attributedAt          DateTime @default(now())
  firstAuditCompletedAt DateTime?
  tierAtAttribution     String?               // tier2 / tier3 captured when referee upgrades
  rewardStatus          String   @default("pending")  // pending | eligible | paid | reversed
  rewardKind            String?                // amazon_card | service_credit
  rewardPaidAt          DateTime?
  rewardAmountCents     Int?
}
```

## 8. Disclosures / legal

- Referrers are not Zorva employees and are not acting as agents.
  Nothing in this program creates an employment, partnership, or
  agency relationship.
- Referrers must not make claims about Zorva beyond what is in our
  public marketing pages. No "Zorva will increase your revenue by
  X%" claims.
- Referrers in jurisdictions that require affiliate disclosure
  (FTC, Competition Act CA) must include "#ad" or "#referral" in
  social posts. The dashboard's share block includes the
  disclosure text by default.
- We reserve the right to revoke any referral code and claw back
  rewards for abusive behavior.

## 9. Open questions

- [ ] Cameron: confirm $200 / $500 / $50 numbers vs. 1-2 months
      credit.
- [ ] Legal: do we need to register the affiliate program in any
      US state? (Probably no, since we do not pay per "sale" in the
      network-marketing sense, but get it on the record.)
- [ ] Operations: who owns the gift-card batch purchase? New SOP
      or piggyback on the existing Amazon Business account?
- [ ] Engineering: confirm Sprint 1 capacity for the Prisma
      migration + cookie hook.

## 10. Changelog

- **2026-06-25** — v1 draft by Marketing.