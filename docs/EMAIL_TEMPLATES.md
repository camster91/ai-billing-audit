# Zorva — Email Templates

Status: spec, ready for the next template implementations.
Owner: branding kit, P5 email-template task (`t_a0c1f833`).
Last updated: 2026-06-24.

This document defines the **visual + content style** for every HTML
email Zorva sends. It complements `apps/portal/src/lib/email.ts` (the
shared dispatcher) and `apps/portal/src/lib/emails/` (the existing
template implementations). New templates follow the rules below; old
templates get refactored to match during the next email-system pass.

---

## 1. Existing templates

Already implemented (see `apps/portal/src/lib/emails/`):

| File                        | Kind               | Cadence        |
|-----------------------------|--------------------|----------------|
| `trigger.ts`                | trigger (welcome)  | on signup      |
| `team-invite.ts`            | transactional      | on invite      |
| `password-reset.ts`         | security           | on request     |
| `first-audit-complete.ts`   | operational        | on first audit |
| `weekly-digest.ts`          | marketing-adjacent | weekly cron    |

This doc unifies their visual style and adds the specs for the four
templates still on the board:

1. **Pilot invitation** (one-time, on pilot sign-up)
2. **Doctor summary** (per-physician weekly summary)
3. **Appeal outcome notification** (one-time, when appeal is filed)
4. **Past-due / billing-failed** (transactional, on Stripe failure)

---

## 2. HTML / CSS rules

Every Zorva email is a single HTML file with inline CSS. No external
stylesheets, no `<style>` blocks (most clients strip them), no
JavaScript. Maximum width 600px.

### 2.1 Layout

- **Container:** 600px wide, centered, `background: #F8FAFC`
  (`surface-light`).
- **Card:** 560px wide, `background: #FFFFFF`, 1px border `slate-200`,
  border-radius 8px, padding 32px.
- **Header:** 80px tall, `background: #0F766E` (`primary-700`),
  centered logo (white version, 32px tall).
- **Footer:** 200px tall, `background: #0F172A` (`slate-900`),
  white-on-dark links.
- **Vertical rhythm:** 16px between blocks, 24px between sections.

### 2.2 Typography

Use the same type system as the portal (see `docs/BRANDING_TYPOGRAPHY.md`):

- **Headings:** Inter / system sans, weight 700, `color: #0F172A`
  (`slate-900`).
  - H1: 28px, line-height 1.2
  - H2: 22px, line-height 1.25
  - H3: 18px, line-height 1.3
- **Body:** Inter / system sans, weight 400, 16px, line-height 1.5,
  `color: #334155` (`slate-700`).
- **Captions:** 14px, `color: #64748B` (`slate-500`).
- **Links:** `color: #0D9488` (`primary`), `text-decoration: underline`.

Webfont fallback chain (Gmail strips `<link>` tags, so the fallback is
critical):

```css
font-family: 'Inter', -apple-system, BlinkMacSystemFont,
             'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
```

### 2.3 Color usage in email

| Element                | Token            | Hex       |
|------------------------|------------------|-----------|
| Page background        | `surface-light`  | `#F8FAFC` |
| Card background        | `surface-white`  | `#FFFFFF` |
| Header background      | `primary-700`    | `#0F766E` |
| Footer background      | `slate-900`      | `#0F172A` |
| Body text              | `slate-700`      | `#334155` |
| Headings               | `slate-900`      | `#0F172A` |
| Primary CTA button     | `primary-600`    | `#0D9488` |
| Warning / denial line  | `amber-600`      | `#D97706` |
| Error / past-due       | `red-600`        | `#DC2626` |
| Success / recovered    | `emerald-600`    | `#059669` |
| Caption / footer text  | `slate-500`      | `#64748B` |

Buttons are 44px tall, 8px corner radius, white text on `primary-600`,
with a 1px `primary-700` border for clients that drop shadows.

### 2.4 What NOT to do

- **No background images** in the body (Outlook desktop strips them).
- **No CSS grid or flexbox** (Outlook 2007–2019 uses Word's renderer).
  Use nested `<table>` for layout.
- **No web fonts as the only option** — always include a system fallback
  (see §2.2).
- **No emoji in subject lines** (deliverability hit + looks spammy).
- **No more than one CTA per email** (multiple CTAs dilute clicks and
  trigger Gmail's "this is a promo" classifier).
- **No attachments** for transactional sends; link to the portal
  instead.
- **No images bigger than 600px wide** and always include `alt` text.

---

## 3. Subject line rules

- **Length:** 30–50 characters. Mobile clients truncate after ~35.
- **Personalize with the tenant name** when it's a marketing-adjacent
  send: `Your weekly digest — Acme Family Clinic`. Skip personalization
  for security/operational sends.
- **No all-caps**, no multiple exclamation points, no emoji.
- **Test prefix:** every test/dev send gets a `[Zorva TEST]` prefix
  in the subject so it's obvious in the inbox and never confused
  with production mail.
- **Re-send prefix:** manual re-sends (from the support tool) get
  `[Zorva resend]` so the recipient knows why they're seeing it again.

---

## 4. Preheader text

The preheader is the 40–130 char preview text that shows next to the
subject in the inbox. Set it explicitly via a hidden `<span>` after
the opening `<body>`:

```html
<span style="display:none;font-size:1px;color:#0F766E;line-height:1px;
max-height:0px;max-width:0px;opacity:0;overflow:hidden;">
This week's audits, denials prevented, and revenue recovered.
</span>
```

Rules:

- **Never start the preheader with "View in browser"** or "Email not
  displaying correctly" — that wastes the 100 chars of preview.
- **Reinforce the subject** with a different angle, don't repeat it.
- **Include one number or fact** when possible (open rates go up).

---

## 5. The four new templates

### 5.1 Pilot invitation

- **Trigger:** clinic signs the pilot agreement (Stripe checkout
  completes with `mode: subscription` and a `pilot` metadata flag).
- **Audience:** the clinic's billing contact (the email they entered
  on the sign-up form).
- **Subject:** `Welcome to the Zorva pilot — let's set up your first audit`
- **Preheader:** `Three steps before your first audit on Monday.`
- **Body sections:**
  1. Hero: "Welcome — you're one of 5 clinics on the Q3 pilot."
  2. Three-step setup checklist (icon + 1-line + link):
     - Connect your EMR (or upload your first 50 claims)
     - Invite the rest of your billers
     - Pick a 10-min kickoff call
  3. CTA: "Book your kickoff call" → Cal.com link
  4. Reminder: "We delete your data within 30 days of pilot end, per
     the agreement."
- **Kind:** transactional (1:1 response to an action they took).

### 5.2 Doctor summary

- **Trigger:** weekly cron, Tuesday 8am local, per active physician
  in the tenant (not per tenant — per doctor).
- **Audience:** the physician themselves (collected from the encounter
  metadata).
- **Subject:** `Your audits this week — Dr. {{lastName}}`
- **Preheader:** `{{n}} encounters audited, {{amount}} in upsell found.`
- **Body sections:**
  1. Hero: "Your audits, {{date range}}."
  2. KPI row (3 cells):
     - Encounters audited: {{n}}
     - Findings produced: {{n}}
     - Estimated impact: {{$amount}}
  3. "Your top 3 finding types" — small table, 3 rows max
  4. "What your biller accepted vs dismissed" — 1 line summary
  5. CTA: "Review your findings" → `/encounters?physician={{id}}`
- **Kind:** marketing-adjacent (scheduled, not action-triggered).
  Include the `List-Unsubscribe` header.

### 5.3 Appeal outcome notification

- **Trigger:** the biller marks an appeal as "filed" in the encounter
  detail view, then later the appeal outcome is recorded (won / lost /
  withdrawn / partial).
- **Audience:** the biller who filed it, plus the clinic owner (CC).
- **Subject:** `Appeal outcome: {{encounter_id}} — {{outcome}}`
- **Preheader:** `Filed {{date}}. Result: {{outcome}}.`
- **Body sections:**
  1. Hero: "Your appeal on encounter {{encounter_id}} is {{outcome}}."
  2. Outcome detail (varies):
     - **won:** amount recovered, expected payout date
     - **lost:** denial reason, suggested next step (modify + resubmit?
       write-off?)
     - **withdrawn:** note from the biller
     - **partial:** amount recovered vs amount billed
  3. CTA: "View the encounter" → `/encounters/{{id}}`
- **Kind:** transactional (response to a tracked action).

### 5.4 Past-due / billing-failed

- **Trigger:** Stripe webhook posts `invoice.payment_failed` for a
  subscription (already wired per `apps/portal/src/lib/billing-webhook.ts`).
- **Audience:** the tenant owner.
- **Subject:** `Your Zorva subscription is past due`
- **Preheader:** `Update your card to keep auditing. {{days}} days left.`
- **Body sections:**
  1. Hero: "Your subscription is past due."
  2. What's blocked: "New audits will pause in {{days}} days."
  3. What's not blocked: "Existing audit history is still accessible."
  4. CTA: "Update your card" → Stripe billing portal
  5. Support: "Reply to this email or chat with us at zorva.ca."
- **Kind:** transactional (operational, not marketing). **Do not**
  include `List-Unsubscribe` — this is a billing-critical message.

---

## 6. Plain-text fallback

Every email has a plain-text version. Rules:

- **Same content, same order, no markup.**
- Wrap at 72 characters (Gmail does this anyway, but pre-wrap for
  clients that don't).
- Use `formatMoney` and `formatNumber` for currency and numbers — no
  raw floats.
- URLs in angle brackets: `<https://zorva.ca/...>` so mail clients
  don't chop them.

---

## 7. Test matrix

Every new template must pass these tests before merge:

1. **HTML renders** in:
   - Gmail (web, iOS, Android)
   - Outlook (2016, 2019, 365, web)
   - Apple Mail (macOS, iOS)
   - Yahoo Mail (web)
2. **Dark mode** is acceptable: the `surface-white` card becomes
   `#1E293B` (`surface-dark-2`) automatically via the
   `prefers-color-scheme: dark` media query. Text color flips to
   `slate-100`. The `primary-700` header stays the same (it's already
   dark).
3. **Unsubscribe** works in one click (List-Unsubscribe-Post is
   present for marketing-adjacent templates).
4. **Suppress list** is checked: an unsubscribed address gets the
   dev-mock log but no Resend call.
5. **Plain-text version** has the same content and no broken URLs.
6. **Subject line** fits in 50 characters and contains no emoji or
   spam-trigger words ("FREE", "ACT NOW", etc.).

Use Litmus or Email on Acid for the cross-client test. The CI runs
just the `pilot-invitation` template in Email on Acid on every PR
that touches `apps/portal/src/lib/emails/`.

---

## 8. Acceptance checklist

When this task is "done":

- [ ] All 4 new templates implemented under
      `apps/portal/src/lib/emails/<name>.ts` with `subject`, `text`,
      and `html` renderers.
- [ ] Each uses the layout + typography rules in **§2**.
- [ ] Each has a plain-text version per **§6**.
- [ ] Each passes the test matrix in **§7**.
- [ ] The three existing marketing-adjacent templates
      (`trigger`, `weekly-digest`, `first-audit-complete`) are
      refactored to match this style guide (background color, footer
      block, button shape).
- [ ] This document is referenced from `docs/BRAND_BOOK.pdf`
      (when compiled, `t_270224ab`).
