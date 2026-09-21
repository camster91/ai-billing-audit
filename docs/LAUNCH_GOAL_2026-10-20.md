# Launch goal — first paid pilot

**Status:** active commitment
**Set:** 2026-09-20
**Owner:** Cameron Ashley
**Target date:** 2026-10-20 (Tuesday)
**Review cadence:** weekly, and at every gate transition

This is a dated commitment, subordinate to `docs/MASTER_PLAN.md`. Where the two
conflict, the master plan's constraints win and this goal slips rather than
trading a guardrail away.

## The goal

**Sign one Alberta primary-care clinic to a paid Zorva AHCIP pre-submit audit
pilot by 2026-10-20.**

"Signed" requires all three, not just the first:

1. A pilot agreement is countersigned by the clinic (HIA Information Manager
   Agreement, counsel-reviewed).
2. A first invoice is issued and either paid or committed in writing. Verbal
   interest does not count.
3. One real reviewed audit is complete end to end: real claims uploaded,
   findings reviewed, a decision recorded in the audit trail.

Why "paid" rather than "signed up": `docs/INVESTOR_ONEPAGER.md` records 0 clinics
in pilot, $0 ARR, pre-revenue as of 2026-07-01. A free pilot does not move that
number. Willingness to pay is the only evidence this window is meant to produce.

## Guardrails — these outrank the goal

- No real clinic data before the P0 trust gates close (issues #5, #6, #12, #14).
- No publishing, sending, or clinic contact without owner approval.
- No unsupported claim in any public or sales surface.
- No production platform-role grant or customer-visible pricing change without
  explicit approval.
- PHI stays in the clinic's tenant. Synthetic data until the gate closes.

If the goal can only be reached by breaking one of these, the goal slips. A pilot
that starts by bending its own PHI controls is worse than a pilot that starts in
November.

## Definition of done

| # | Requirement | Evidence |
| --- | --- | --- |
| 1 | All critical and high findings from the 2026-09-20 review closed | Merged commits plus a passing append-to-verify round-trip test for the chain |
| 2 | CI green on `main` with branch protection enabled | Actions run URL and a protection API response that is not 404 |
| 3 | Pilot agreement countersigned | Signed IMA in the pilot record |
| 4 | First invoice issued and paid or committed | Invoice record plus written commitment |
| 5 | One real reviewed audit completed | Encounter, findings, and a verified audit-trail entry |
| 6 | P0 trust gates verified against production | Issue #5, #6, #12, #14 closed with restore-verified backup evidence |

## Gate checklist — critical and high findings

| Item | Location | Effort | Status |
| --- | --- | --- | --- |
| Audit chain cannot verify its own output (reproduced) | `audit_actions.py` / `audit_log.py` / `feedback.py` — issue #34 | 1–2 d | open |
| Untrusted note reaches the LLM with no instruction hierarchy | `auditor.py:403-427`, `prompts/v12` | 0.5 d | open |
| Hallucination guardrail does not constrain output | `auditor.py:444-488`, `:595-610` | 1 d | open |
| Bearer token value disclosed in six tracked files | `docs/PILOT_DEMO_RECORDING*.md`, `changelogs/2026-07-01-p11-ux-sweep.md`, `qa-bundle/05`, `qa-bundle/06`, `research/P11-bug-sweep.md` — pairs with issue #10 | 0.5 d | open |
| SSRF via `register_slack` | `slack_notify.py:158`, reachable from `api.py:7957` | 2 h | open |
| Missing per-route RBAC `Depends(...)` | ~8 endpoints incl. `api.py:5392`, `:5578`, `:7957` | 0.5 d | open |

Estimated 5–6 focused days. Issue #34 currently files the chain defect as P2;
this plan treats it as P0 because the compliance story rests on that chain.

## Decision dependencies — owner action, not engineering

| Decision | Issue | Needed by | State |
| --- | --- | --- | --- |
| Pilot offer: paid or free, term, single fee, inclusions | #76 | 2026-09-22 | **DECIDED 2026-09-20** — paid: 60-day pilot, CAD $1,500 one-time, credited against the first month if the clinic continues, no automatic conversion. Applied across 23 surfaces in PR #121. Qualification boundaries remain open on #76. |
| Pricing, packaging, unit economics | #108 | 2026-09-22 | Partially decided — the pilot fee is set; unit economics and packaging remain open on #108. |
| Counsel engaged on the HIA IMA | #14 | 2026-09-21 | **open — now the critical path.** Longest external lead time and the only item not under our control. |
| GitHub Actions billing restored; branch protection on | — | 2026-09-21 | **open — still the top action.** CI has been failing since 2026-09-02 with zero steps executed, so nothing on this repo is independently verified, including three open PRs. |
| Lead owner named; contact delivery proven | #74 | 2026-10-11 | open |

### Critical path, revised 2026-09-20

The offer decision — originally day 2 — is **done, ahead of schedule**, and it
turned out to be smaller than feared: the pricing tiers themselves were never
in question, only the pilot's terms, and the four contradictory versions are now
one. That removes the largest piece of ambiguity from outreach, the agreement,
and the pricing page.

Two items now dominate:

1. **GitHub Actions billing.** ~~Everything else is unverified until this is
   fixed.~~ **RESOLVED 2026-09-21.** Actions billing is restored; CI runs and is
   green on `main` (verified locally: portal `build`, `lint --max-warnings=0`,
   `tsc --noEmit`, and 247/247 unit tests pass on the audit-export fix in
   PR #124). Remaining on this item is enabling branch protection (DoD #2), which
   is still open.
2. **Counsel on the HIA IMA (#14).** Unchanged and not under our control. If it
   is not engaged during week 1, reset the target to 60 days rather than
   discovering it on day 28.

A related find while applying the offer decision: the Alberta outreach email
templates asserted a completed 60-day pilot at an Ontario clinic, with derived
"what we caught" numbers, while the investor one-pager records 0 clinics in
pilot. That is now removed and locked by `tests/test_offer_consistency.py`. Worth
confirming whether any of those templates were actually sent.

## Weekly checkpoints

| Week | Window | Exit condition |
| --- | --- | --- |
| 1 | Sep 21–27 | CI green and protected; counsel engaged; offer decided; one warm clinic conversation live |
| 2 | Sep 28–Oct 4 | All six gate items closed; pilot path rehearsed on synthetic data; IMA in the clinic's hands |
| 3 | Oct 5–11 | Immutable release cut; P0 trust gates verified against production; alerting live |
| 4 | Oct 12–18 | Agreement countersigned; invoice issued; first real reviewed audit run |
| Close | Oct 19–20 | Written outcome against every requirement, met or missed with a named next action |

## Known risk

Counsel is the long pole and is not under our control. A lawyer-reviewed HIA
Information Manager Agreement, reviewed again by a clinic's privacy officer, is
realistically 2–4 weeks of calendar time. Starting it on day 1 is the only reason
a 30-day target is plausible. **If counsel cannot be engaged in week 1, reset the
target to 60 days immediately rather than discovering it late.**
