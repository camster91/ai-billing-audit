# Zorva — Exhibitor Kit

Status: spec, ready for production. Owner: branding kit, P1 exhibitor-kit
task (`t_58cfe991`). Last updated: 2026-06-24.

This document is the **spec** for Zorva's booth presence at a small
medical-billing or health-IT conference (e.g. the Alberta Medical
Association billing summit, the Canadian Healthcare Informatics
Conference, or a regional MGMA chapter meeting). It defines the
physical footprint, the printed and screen collateral, the staffing
plan, and the leave-behind. Build the booth once, then ship to the
first three conferences with the same kit — the variations across
events should be confined to the banner stand copy and the demo
video QR code.

The spec is deliberately small. We are not staffing a 20×20 island
with a custom-built demo room. We are running a **10×10 inline booth
with two people, one monitor, and a single-stack banner stand** —
the smallest footprint that still lets us show a real audit on a
real-looking claim. Anything bigger doubles our logistics cost and
quadruples the staffing risk without doubling the number of qualified
conversations.

---

## 1. Footprint

- **Booth size**: 10' × 10' inline (single 10×10 carpeted space).
- **Power**: one 15A / 120V outlet, rear-right corner. Bring a
  6-outlet power bar and a 25' extension.
- **Internet**: conference Wi-Fi is the only requirement. We do
  not ship a cellular hotspot — the demo is on the conference Wi-Fi
  or it doesn't run, and the booth staff has a printed fallback
  deck if the network drops.
- **Shipping**: one Pelican-style hard case (28" × 18" × 12") with
  the monitor, cables, banner stand, and 500 leave-behind
  one-pagers. Hand-carried to the venue, no freight forwarder.

### Layout (top-down view, looking from the aisle)

```
                  ┌─────────────────────────┐
                  │                         │
                  │   Banner stand (back)   │
                  │                         │
                  │                         │
                  │   Counter / demo desk   │
                  │                         │
                  └─────────────────────────┘
                              ↑
                          aisle traffic
```

- **Back wall (8' wide)**: one retractable banner stand, 33" × 81".
- **Front (aisle side)**: one 6' folding counter with the demo
  monitor (24" 1080p), a keyboard + trackpad, a stack of
  leave-behinds, and a small bowl of branded mints.
- **Side walls**: nothing. The booth is open on both sides; we want
  the aisle to flow through.

## 2. Banner stand — front copy

A single retractable banner stand, 33" × 81" portrait orientation,
printed on 13 oz matte vinyl. The full bleed uses the brand
`primary-700` (`#0F766E`) background; type is white and a single
accent in `secondary-500` (`#F59E0B`).

**Front of banner (the side the aisle sees):**

- Top, 16pt eyebrow: "Pre-submit audit for Alberta clinic billing."
- Center, 72pt headline (3 lines max):

  > Find the revenue
  > your billers are
  > leaving on the table.

- Below the headline, 18pt sub:

  > Zorva reads every AHCIP claim against the SOMB before it leaves
  > your desk. Modifier unlocks, missed procedures, modifier-25 —
  > with the exact rule passage cited.

- Bottom-right, 14pt footer: "zorva.health/demo"

**Back of banner (visible only inside the booth):** a small
reproduction of the dashboard's "Findings" tab as a static image,
with one call-out in 16pt: "This is a real finding from a real
encounter — recovered $38 in modifier-25 alone."

## 3. Demo monitor

- 24" 1080p monitor on a fixed-height stand, set so the screen
  top is 60" off the ground (eye level for a standing adult).
- Connected to a small Mac mini (M2, 16GB) tucked behind the
  monitor arm. The mini runs the live demo in a single Chrome
  kiosk window, full-screen, no other apps.
- The demo is the same 60-second walkthrough that's embedded on
  the home page (see `feat(marketing): demo video embed`). A
  tablet on the counter has a YouTube playlist of the same video
  on a 3-minute loop, in case someone wants to see it without
  sitting at the monitor.

### Demo script (60 seconds, the booth staff talks through it)

1. **0:00–0:10** — "Here's a sample AHCIP claim. The note says
   the patient came in for a moderate-complexity visit with a
   same-day injection. The biller coded 03.01A and the injection.
   Watch what Zorva does."
2. **0:10–0:30** — Upload the claim. The auditor screen shows it
   reading the note, pulling the SOMB rule, and flagging two
   findings: E/M level (03.01A → 03.04A, $32), and modifier-25
   on the E/M (-25 unlock, $40). The screen shows the exact
   rule passage cited.
3. **0:30–0:50** — "Total recovered: $72 on a single encounter.
   Zorva found both — the biller would have missed the modifier
   -25. Every finding has a citation; nothing ships until a
   human signs off."
4. **0:50–0:60** — "Flat monthly fee. No percentage of revenue.
   HIPAA-aligned, HIA-aligned, with data residency confirmed in
   the BAA. Book a 60-day pilot at zorva.ashbi.ca/contact."

The script is on a 4×6 index card taped to the back of the
monitor. Booth staff rehearses it twice before opening.

## 4. Leave-behind one-pager

A single 8.5×11" sheet, printed both sides, on 100lb matte cover.
The front is the same content as the clinic pitch one-pager (see
`docs/CLINIC_PITCH_ONEPAGER.md` — to be created). The back is a
short tear-off card the visitor can fill out and drop in a bowl
on the counter:

```
   ┌────────────────────────────────────────────┐
   │  Yes, I'd like the 60-day pilot.          │
   │                                            │
   │  Name:    _________________________________│
   │  Clinic:  _________________________________│
   │  Email:   _________________________________│
   │                                            │
   │  Drop in bowl. We follow up within 24 hr.  │
   └────────────────────────────────────────────┘
```

500 copies per show, weighed before packing. We track the
conversion rate from card-drop to booked pilot as the primary
booth KPI.

## 5. Staffing

- **Two people per booth shift.** Not one, not three. One is on
  the demo, the other is on the aisle pulling in passers-by and
  qualifying the conversation. They rotate every 90 minutes to
  avoid demo fatigue.
- **Shifts**: a typical two-day show is three 4-hour shifts per
  day, so 6 booth-staff slots total. We budget 3 people per show
  (the founder + one engineer + one billing-ops contractor), so
  one person covers two shifts and nobody works both a morning
  and an evening shift back-to-back.
- **Dress code**: branded polo + lanyard, no suits. The audience
  is clinic billing leads and privacy officers — they are not
  impressed by suits and are actively put off by them.
- **What we do NOT do**: we do not run a giveaway, we do not have
  a prize wheel, we do not have a paid lead-scanner. The only
  call-to-action is the leave-behind and the QR code on the
  banner stand.

## 6. Pre-show checklist

- [ ] Banner stand printed, packed, no creases.
- [ ] 500 leave-behind one-pagers printed, weighed, packed.
- [ ] Demo monitor + Mac mini + cables tested (full 60s script
      runs end-to-end at the office, at the hotel the night
      before, and again at the venue before opening).
- [ ] Conference Wi-Fi credentials confirmed (or the printed
      fallback deck is in the kit).
- [ ] Bowl of mints (yes, this matters — billing leads have a
      reputation for being tired and caffeinated at these shows).
- [ ] 4×6 demo-script index card, taped to the back of the
      monitor.
- [ ] Booth-staff shirts and lanyards.

## 7. Post-show follow-up

- Card-drops are entered into the CRM within 48 hours. The
  follow-up email is sent within 24 hours of the show closing.
- The primary KPI is **card-drop → booked pilot**, target 30%.
  Secondary KPI is **booth conversation → qualified lead**,
  target 40%.
- A short retrospective (1 page, no fluff) is filed in this
  doc under "Show retrospectives" within 7 days of the show.