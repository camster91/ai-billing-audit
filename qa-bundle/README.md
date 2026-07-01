# Zorva — QA Bundle (2026-07-01)

For: a friend QA-pass on the cold outreach drafts and the marketing
surface before the first pilot goes out.

This bundle is **read-only context for review**. The originals live
in the `ai-billing-audit` repo at the paths listed below. Nothing in
this folder is the source of truth — if your friend has feedback,
file it against the original files.

---

## What's in here

| File | What it is | Why it matters for QA |
|------|------------|----------------------|
| `01-cold-email-red-deer-pcn.txt` | Cold email #1 — Red Deer PCN operations director | Draft #1 of 3. Lead with audit findings (3 SOMB patterns), low-commitment CTA ("happy to send a 1-page report — no fee, no follow-up unless useful"). |
| `02-cold-email-strathcona-pcn.txt` | Cold email #2 — Strathcona / Sherwood Park PCN ops lead | Same template, TELUS Med Access context for Sherwood Park. |
| `03-cold-email-west-springs.txt` | Cold email #3 — West Springs Medical office manager | Locum trigger event moved to middle paragraph (was opening line — would've matched the event-recap pattern Cameron's style rule bans). |
| `04-privacy-officer-brief.md` | One-page non-technical pre-flight for Alberta privacy officers | The thing that gets sent alongside any pilot, so the prospect's privacy officer can self-validate before signing the IMA. |
| `05-p11-changelog.md` | Cumulative changelog for the P11 sweep (8 commits, 2026-06-30 → 2026-07-01) | Context on what's been fixed and what was deferred. |
| `06-p11-bug-sweep.md` | Full research doc for the P11 sweep — swarm composition, findings, deferred rationale, re-spawn instructions | Deeper context on the 22 critical + 18 high-priority bugs the swarm caught. |

---

## What to QA (priority order)

### Priority 1 — the cold emails (PRIMARY)

For each email, check:

1. **Audit-first opener.** Does the first 2-3 paragraphs lead with concrete, verifiable SOMB-pattern findings rather than flattery / event-recap / generic intros? The 3 SOMB patterns per email are: modifier-25 missing, CMGP modifier missed, EM undercode (West Springs/Strathcona) or annual physical billed as insured / same-day 03.04A+03.05A conflict (Red Deer).
2. **12th-grade English.** Is each sentence one idea? Are banned phrases present? Banned list: "dilutes authority", "confuses search engines", "Google weights the mismatch", "leak / bounce / weight" as verbs in SEO sense, "dilute / leverage / robust / synergy / holistic / unlock" anywhere.
3. **Numbers are honest.** The F1=0.690 number is real (cleaned AHCIP validation set, 10 encounters, 13 gold findings). The SOMB dollar amounts are estimates, not guarantees. None of the percentages (e.g. "modifier-25 capture rate lift") are claimed in the emails — only the per-occurrence dollar estimates which are defensible.
4. **Low-commitment CTA.** Should not say "schedule a 15-min call" or "book a demo." Should be a pull-not-push: "happy to send a 1-page report — no fee, no follow-up unless useful."
5. **P.S. → privacy officer brief.** All 3 emails end with a P.S. pointing to `docs/PRIVACY_OFFICER_BRIEF.md` (file `04` in this bundle) so the prospect's privacy officer can self-validate before any contract goes out.
6. **Trigger event handling.** West Springs email has a locum posting as the trigger; check that the trigger is in the middle (framing the offer timing), NOT in the opening line.

### Priority 2 — privacy officer brief (file 04)

This is what gets sent alongside any pilot. The privacy officer reading it should be able to:
- Understand what data Zorva processes (in plain English)
- Know the legal framework that applies (HIA for Alberta, PIPEDA federally, HIPAA for US pilots)
- Know where data lives (Canadian-region Postgres, document in IMA)
- Know how to escalate concerns
- Verify the technical claims (salt SHA-256 patient hash, hash-chain audit trail, no model training on customer data)

5 plain-English questions are listed at the bottom — those are the questions the privacy officer should be able to answer after reading the brief.

### Priority 3 — P11 changelog (file 05)

Cumulative changelog for the 8-commit P11 sweep. Just context for what changed. If the QA friend is technical, this is the TL;DR; otherwise skim and move on.

### Priority 4 — P11 bug sweep (file 06)

Deep dive. Only read if you want to understand what the swarm found. Has the swarm composition, every deferred item with rationale, and re-spawn instructions if we want to run another sweep.

---

## What NOT to worry about in QA

- **Code quality / Python / TypeScript** — the swarm already audited that and fixed 22 critical + 18 high-priority bugs. The 5 new api-errors tests are passing.
- **Live VPS deploy** — all 8 commits are deployed and verified. Viewport meta, portal pages, error boundaries, etc. all live.
- **Pricing tiers** — unified at 1,000 / 3,000 / 3,000+ across all 5 sources (was a 5-way conflict before P11).
- **The "Maya Okafor" / example.com URLs** — removed from /press (was a fictional founder fabricated for placeholder coverage). Page now honestly says "No third-party coverage yet."

---

## Quick style reference (if QA wants context)

Cameron's cold-outreach style is captured in user memory as 8 rules. The most QA-relevant:

1. **Audit-first, not intro-first.** Lead with 2-4 concrete, verifiable findings from the target's actual website / product / public footprint. No vibes, only receipts.
2. **12th-grade English.** Short sentences, one idea each. No compound business jargon.
3. **Low-commitment CTA.** "Happy to send over a short PDF with the rest of what I noticed — no charge, no follow-up if it isn't useful." Lets them pull instead of being pushed.
4. **No event-recap opener.** Never start with "Saw [company] [launched/raised/expanded/rebranded] — congrats on the [growth/news]."
5. **Concrete credentials in one line max.** "Top Rated on Upwork, 80+ projects, $100K+ earned" — once, not paragraph-form.

The 3 drafts in this bundle all follow these rules.

---

## Original file paths

For editing or citing in any feedback:

```
/Users/biancabienaime/projects/ai-billing-audit/templates/email/zorva_pcn_red_deer_v1.txt
/Users/biancabienaime/projects/ai-billing-audit/templates/email/zorva_pcn_strathcona_v1.txt
/Users/biancabienaime/projects/ai-billing-audit/templates/email/zorva_clinic_west_springs_v1.txt
/Users/biancabienaime/projects/ai-billing-audit/docs/PRIVACY_OFFICER_BRIEF.md
/Users/biancabienaime/projects/ai-billing-audit/changelogs/2026-07-01-p11-ux-sweep.md
/Users/biancabienaime/projects/ai-billing-audit/research/P11-bug-sweep.md
```

---

## How to share with a friend

The `qa-bundle/` folder is self-contained. Options:

1. **Dropbox / Google Drive / iCloud Drive** — copy the folder to your synced Drive. Friend gets read access.
2. **GitHub gist** — `gh gist create qa-bundle/*` will push all 6 files as a single secret gist.
3. **Email** — zip the folder: `cd ai-billing-audit && zip -r qa-bundle.zip qa-bundle/`, attach.
4. **Direct message** — share the files one at a time as text attachments.

If your friend wants to leave feedback inline, ask them to use the `01-`/`02-`/`03-` file names so it's clear which draft the comment is on.