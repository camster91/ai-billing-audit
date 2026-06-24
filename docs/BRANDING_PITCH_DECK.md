# Zorva — Pitch Deck Template

Status: template spec, ready for slide production.
Owner: branding kit, P5 pitch-deck task (`t_5dae704e`).
Last updated: 2026-06-24.

This document is the **template** for the Zorva pitch deck. It defines
the slide order, the per-slide content guide, the visual rules (which
icons, illustrations, color tokens to use), and the export conventions.
Build it once, then clone and edit for each audience (clinics,
investors, partners).

---

## 1. Slide order (10 slides, 18 minutes)

| #  | Title                          | Time   | Purpose                           |
|----|--------------------------------|--------|-----------------------------------|
| 1  | Cover                          | 0:30   | Brand impression, who we are      |
| 2  | The problem                    | 2:00   | Lost revenue, why it matters      |
| 3  | Why it's hard today            | 1:30   | Current workflow pain             |
| 4  | The Zorva solution             | 2:00   | What we do, in one sentence       |
| 5  | How it works                   | 2:30   | 3-step demo of the product        |
| 6  | Findings gallery               | 2:30   | Social proof: real finding types  |
| 7  | Results                        | 1:30   | Numbers: revenue recovered, time saved |
| 8  | Why now                        | 1:00   | Market timing, regulatory tailwind |
| 9  | Ask / next steps               | 2:00   | Pilot offer, contact              |
| 10 | Thank you / Q&A                | 1:30   | Backup, FAQ                       |

Total: ~17:30 + 30s buffer = 18 minutes.

---

## 2. Visual rules (apply to every slide)

- **16:9** aspect ratio, 1920×1080 native.
- **Brand color background** (slides 1, 4, 9, 10): `primary-700`
  `#0F766E` with white text.
- **Light background** (slides 2, 3, 5, 6, 7, 8): `surface-light`
  `#F8FAFC` with `slate-900` text.
- **Primary accent line** under section titles: 4px, `primary-700`.
- **Type:** primary typeface (Inter / Satoshi per `docs/BRANDING_TYPOGRAPHY.md`).
  - Slide titles: 48–56pt, weight 700.
  - Body: 24–28pt, weight 400.
  - Captions / footnotes: 16pt, weight 400, `slate-500`.
- **Logo** in the bottom-right corner of every content slide (24px tall).
  Top-right of the cover only (40px tall).
- **No more than 6 words on a title slide.** Bullets: max 5 per slide,
  max 8 words per bullet.
- **One illustration or chart per slide max.** Don't mix.

---

## 3. Per-slide content guide

### Slide 1 — Cover

- **Big logo** centered.
- **Tagline:** "Find the revenue your billers are leaving on the table."
- **Sub-line:** "AI pre-submit claim audit for Alberta primary care."
- **Speaker name + date** in the bottom-left.
- Background: `primary-700`.

### Slide 2 — The problem

- **Title:** "Alberta primary care is leaving $40K–$120K per clinician per year unbilled."
- **Three stat callouts** (large numbers, 56pt):
  - 11% — average undercoding rate in primary care (per CMA 2024 data)
  - $58 — average revenue lost per undercoded visit
  - 73% — of AHCIP claim denials are recoverable with a corrected re-submit
- **Source line** at the bottom: "Source: CMA 2024 billing audit, AHCIP SOMB 2025."

### Slide 3 — Why it's hard today

- **Title:** "Today's billers are overworked, under-supported, and reactive."
- **Three pain-point rows** (icon + 1-line):
  - `IconClaims` — "Manual review of every claim is impossible at scale."
  - `IconHigh` — "Denials come back weeks later, when the context is gone."
  - `IconError` — "Payer rules change often enough that training lags."
- **Quote** at the bottom (real, attributed): a 1-sentence quote from a
  pilot-clinic biller (collected during pilot, see
  `docs/PILOT_DEMO_RECORDING.md`).

### Slide 4 — The Zorva solution

- **Big statement:** "Zorva audits every claim, before you submit it."
- **Three pillars** (icon + 1-line + 1-line):
  - `IconShieldCheck` — "Catches denials" — rules engine + LLM explanation
  - `IconBolt` — "Finds missed revenue" — undercode / missing-procedure / -25
  - `IconLock` — "PHI-safe by design" — encrypted, audit-chained, on-shore
- Background: `primary-700`.

### Slide 5 — How it works

- **Title:** "Three steps. Ten seconds per claim."
- **3-column layout**, each column one step with the matching illustration
  from `docs/BRANDING_IMAGERY.md` (asset IDs 2, 3, 4):
  1. **Upload** — claims + clinical notes
  2. **Audit** — Zorva runs the rules + LLM
  3. **Review** — biller accepts or dismisses, submits
- **Live demo CTA** (small): "See it in 90 seconds → [QR code to demo video]"

### Slide 6 — Findings gallery

- **Title:** "What Zorva finds."
- **2×3 grid of finding cards**, each with the matching illustration
  (asset IDs 5, 6, 7 plus 3 placeholders for v1.1):
  - "Missing modifier-25" — `-$50` per encounter
  - "Undercoded E/M visit" — `+$30` per encounter
  - "Unbilled procedure" — `+$45` per encounter
  - "Documentation gap" — `-$80` per encounter
  - "Duplicate service" — `-$120` per encounter
  - "Telehealth premium missed" — `+$15` per encounter
- This is the **most important social-proof slide** of the deck.

### Slide 7 — Results

- **Title:** "What the pilot showed."
- **Big number callout** (96pt): "**$4,200 per clinician per month** in
  recovered + newly captured revenue."
- **Secondary stats** (3 columns):
  - 92% — biller acceptance rate
  - 4 min — average time saved per audited claim
  - 0 — PHI incidents across the pilot
- **Caveat line** (small, slate-500): "Pilot of 3 clinics over 60 days.
  Full case study available on request."

### Slide 8 — Why now

- **Three columns**, icon + 1-line:
  - `IconBolt` — "AHCIP SOMB 2025 update added 14 new billable codes."
  - `IconShieldCheck` — "HIA + PIPEDA review is on the clinic's roadmap,
    not a blocker."
  - `IconStethoscope` — "Primary-care physician shortage is at a 20-year
    high; billers are overworked."
- One-line takeaway at the bottom: "The clinics that adopt pre-submit
audit in 2026 will compound the gains."

### Slide 9 — Ask / next steps

- **Title:** "Pilot with us."
- **Two columns:**
  - **Left:** the pilot offer
    - 60 days, 1 clinic, up to 1,000 claims/mo
    - Free during pilot; standard pricing kicks in at month 3
    - You own the data; we delete it within 30 days of pilot end
  - **Right:** the contact
    - `hello@zorva.ca` / `zorva.ca/book`
    - Calendar QR code (links to Cal.com 10-min slot)
- Background: `primary-700`.

### Slide 10 — Thank you / Q&A

- **Big:** "Thank you."
- **Three small lines:**
  - "We follow up within 24 hours."
  - "Email hello@zorva.ca with any question, any time."
  - "Backup slides on the next pages."
- Background: `primary-700`.
- Append **3 backup slides** (FAQ, security deep-dive, pricing detail)
  after this, same visual rules.

---

## 4. Export conventions

- **Master file:** `templates/pitch-deck.key` (Keynote) +
  `templates/pitch-deck.pptx` (PowerPoint, exported from Keynote).
- **PDF export:** `templates/pitch-deck.pdf` with speaker notes
  included.
- **Per-audience variants:** `templates/pitch-deck-clinics.key`,
  `templates/pitch-deck-investors.key`. Start from the master, swap
  the cover and the results slide, leave the rest.
- **Aspect ratio:** 16:9, never 4:3.
- **File size:** keep the .key under 25 MB. Use linked movies, not
  embedded, for the demo video.

---

## 5. Speaker notes

Every slide has speaker notes. They live in the same .key file under
the notes view. Each note is **1–3 sentences max** — the bullet points
on the slide do the heavy lifting; notes are the verbal transitions and
the timing cues.

A note template:

```
<opening line, the one thing you want them to remember from this slide>
<one supporting fact or anecdote>
<transition to the next slide>
```

---

## 6. Acceptance checklist

When this task is "done":

- [ ] `templates/pitch-deck.key` exists with 10 slides + 3 backups.
- [ ] `.pptx` and `.pdf` exports exist and are byte-stable.
- [ ] All visual rules in **§2** are applied.
- [ ] Every slide has speaker notes per **§5**.
- [ ] Per-audience variants exist for clinics and investors.
- [ ] The deck is rehearsed end-to-end once at 18:00 flat, recorded,
      and the recording lives at `templates/pitch-deck-rehearsal.mp4`
      for the next presenter to study.
