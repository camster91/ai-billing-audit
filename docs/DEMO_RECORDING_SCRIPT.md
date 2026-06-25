# Zorva Demo Recording — Script

> Kanban: t_b1cd534a (E5) on board 'pilot-ready'.
> Target length: 2 minutes. Format: Loom recording over the live Zorva
> dashboard. No slides, no intro animation — straight into the product.
> This doc is the **script**, not the rendered video. Cam records the
> actual Loom; this doc is the shot list + narration for the recording.

## Pre-recording checklist (60 seconds, before hitting record)

- [ ] Two browser tabs open: one on `/encounters`, one on `/encounter/<id>`.
- [ ] The val set has been uploaded to the staging tenant; at least one
      encounter has findings (so the demo has something to show).
- [ ] The dashboard is in "split-screen" mode (the post-C5 layout).
- [ ] Your mic is at a reasonable level; quiet room; no notifications.
- [ ] Loom is set to 1080p, no camera (just screen + voice).
- [ ] Start a 2-minute countdown timer; hard stop at 0:00.

## Shot list (with timing)

### Shot 1 — Dashboard overview (0:00 – 0:20)

**On screen:** the `/encounters` list with a flagged encounter at the top.

**Narration:**

> "This is Zorva. Every claim that comes in from your billing system
> gets audited before it goes to the payer. Here on the dashboard you
> can see the encounter queue — flagged encounters are at the top,
> clean ones are below the fold."

### Shot 2 — Click into a flagged encounter (0:20 – 0:50)

**Action:** click the top flagged encounter.

**On screen:** the `/encounter/<id>` split-screen view.

**Narration:**

> "Click into a flagged encounter and you see the clinical note on
> the left, the findings on the right. Each finding has the rule
> citation, the suggested code change, and the quote from the note
> that supports the finding. The biller can accept or dismiss each
> one. No silent auto-correction — the biller is always the human
> in the loop."

### Shot 3 — Highlight a specific finding (0:50 – 1:20)

**Action:** hover or click on one finding; the corresponding text in the
clinical note should highlight.

**Narration:**

> "Each finding is anchored to a quote in the note — the highlighted
> span on the left is what the auditor based this finding on. You
> see the rule, the current code, the suggested code, and the
> estimated financial impact."

### Shot 4 — Accept one, dismiss one (1:20 – 1:50)

**Action:** click Accept on one finding, click Dismiss on another. The
audit chain row will be appended silently in the background.

**Narration:**

> "Accepting or dismissing a finding takes one click. Behind the
> scenes, every action is appended to a tamper-evident audit chain
> — the privacy officer can verify the chain at any time. The
> biller reviews; the biller decides."

### Shot 5 — Wrap-up (1:50 – 2:00)

**On screen:** zoom out to the encounter detail or the dashboard.

**Narration:**

> "That's the 30-day pilot in 90 seconds. We don't submit claims,
> we don't store your clinical notes long-term, and we don't replace
> your biller's judgment. Book a 10-minute walkthrough at
> zorva.example.com — link in the description."

## Recording settings

- **Resolution:** 1920x1080.
- **Frame rate:** 30 fps.
- **Audio:** mono mic, no background music.
- **Length:** hard cap at 2:00. Cut the recording if you overshoot —
  the value of the demo is its brevity, not its completeness.
- **Title (Loom):** "Zorva — pre-submit claims audit in 90 seconds".
- **Description:** the cold-outreach blurb from
  `templates/email/cold_outreach_v1.txt` plus the
  `docs/ONE_PAGER_WHAT_WE_DO.md` link.

## What NOT to do

- **Don't read from a script.** The narration above is a shot list,
  not a teleprompter. Talk naturally; if you lose your place, cut
  and re-record that shot.
- **Don't show real clinical notes.** If the staging tenant has
  real data, blur the patient identifiers before recording. The
  val-set synthetic notes are fine.
- **Don't mention pricing** in the recording. Pricing is for the
  one-pager and the follow-up email, not the 2-minute demo.
- **Don't apologize for bugs.** If something breaks during recording,
  cut, fix, re-record. Demo recordings are not the place to show
  debugging.
- **Don't go longer than 2 minutes.** A 2-minute demo that runs to
  2:30 becomes a 3-minute demo. Cut earlier, not later.

## Where to host the recording

Upload to Loom with the title and description above. Also export an
MP4 and drop it at `docs/ZORVA_DEMO_2MIN.mp4` so the link doesn't
rot when the Loom URL changes. Reference both in:

- `apps/portal/src/app/page.tsx` (homepage hero CTA)
- `templates/email/cold_outreach_v1.txt` (under the call-to-action)
- `docs/ONE_PAGER_WHAT_WE_DO.md` (link in the "Book a 15-minute
  walkthrough" line)

## Acceptance

The recording is acceptable when:

- [ ] Length is 1:45 – 2:00.
- [ ] Audio is clear at default laptop volume.
- [ ] The dashboard renders without layout shift.
- [ ] All patient identifiers are blurred or absent.
- [ ] The "We don't submit claims" line lands cleanly in shot 5.
- [ ] The MP4 is committed to the repo at `docs/ZORVA_DEMO_2MIN.mp4`.
- [ ] The Loom link is added to the homepage hero CTA.
