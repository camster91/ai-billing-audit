# Launch readiness — working TODO

**Created:** 2026-09-21
**Owner:** Cameron Ashley
**Governing plan:** `docs/MASTER_PLAN.md`
**Dated commitment:** `docs/LAUNCH_GOAL_2026-10-20.md` — sign one Alberta
primary-care clinic to a paid pilot by 2026-10-20.

This is the working checklist for shipping a great, working product that people
actually use. It follows the goal→plan→work→verify discipline in
`docs/MASTER_PLAN.md`: **launch gates are not engineering tasks.** Most of what
stands between the current build and a first paid pilot is owner decisions and
external review, not code.

Where this file and the master plan disagree, the master plan wins.

---

## Where the project actually is

**The build is well ahead of the launch.** As of 2026-09-21:

- Both stacks are real and end-to-end exercisable: the FastAPI audit engine and
  the Next.js portal on Postgres, with a public marketing surface, an operator
  workspace (Zorva HQ), a v1 API for EHR integration, and a working backup and
  restore path.
- The portal suite is 247/247 green, with a clean `build`, `lint`, and
  `tsc --noEmit`.
- A full review of both stacks plus the deploy surface was completed on
  2026-09-20 (`docs/CODE_REVIEW_2026-09-20.md`). Findings are ranked, evidenced,
  and tracked as issues.
- Revenue state remains what `docs/INVESTOR_ONEPAGER.md` recorded on 2026-07-01:
  **0 clinics in pilot, $0 ARR, pre-revenue.** That number is the one the launch
  goal exists to move.

**What is actually blocking launch:** three of the four P0 trust gates are open,
counsel has not been engaged on the pilot agreement (longest external lead time,
not under our control), and the critical/high review findings are only partly
closed. See the checklist below.

**What is not blocking:** the product works. Nothing in this list requires a new
feature to reach the first paid pilot.

---

## 1. Close the critical and high review findings

Source: `docs/CODE_REVIEW_2026-09-20.md`. These are the gate items in
`docs/LAUNCH_GOAL_2026-10-20.md` and the definition of done for issue #118.

| # | Item | Where | Issue | State |
| --- | --- | --- | --- | --- |
| 1.1 | Gate `/api/audit/export` behind the `read` capability and log exports | portal route | — | **DONE — PR #124** (build, lint, tsc, 247/247 tests green) |
| 1.2 | Audit chain cannot verify rows written by its own append path | `audit_actions.py`, `audit_log.py`, `feedback.py` | #113 | open — 1–2 d |
| 1.3 | Untrusted clinical note reaches the auditor prompt with no instruction hierarchy | `auditor.py:403-427`, `prompts/v12` | #114 | open — 0.5 d |
| 1.4 | Hallucination guardrail validates quotes only, not suggested codes or rule IDs | `auditor.py:444-488`, `:595-610` | #115 | open — 1 d |
| 1.5 | SSRF: Slack webhook registration accepts arbitrary URLs | `slack_notify.py:158`, `api.py:7957` | #116 | open — 2 h |
| 1.6 | Add per-route RBAC dependencies to state-changing and admin endpoints | ~8 endpoints | #117 | open — 0.5 d |
| 1.7 | Audit writes swallowed by `except Exception: pass`, incl. the tenant purge | 8 sites in `api.py` | new | open |
| 1.8 | Completed v1 audits become unretrievable after a restart | `public_api.py`, `job_queue.py` | new | open |
| 1.9 | `audit_trail` append-only trigger bypassable via null signature | `audit_trail.sql:196-213` | new | open |
| 1.10 | Bearer token value disclosed in six tracked files | `docs/PILOT_DEMO_RECORDING*.md`, `changelogs/`, `qa-bundle/`, `research/` | #10 | open — 0.5 d |
| 1.11 | Eight uploaded `.edi` files committed to git; `uploads/` not ignored | `apps/portal/uploads/` | new | open |
| 1.12 | Python audit chain has no lock (can fork); portal chain is unkeyed | `audit_actions.py`, `apps/portal/src/lib/audit-chain.ts` | #34 | open |

Items 1.3–1.6 are the same set referenced in `docs/LAUNCH_GOAL_2026-10-20.md`;
that document estimates 5–6 focused days for the group. Items 1.7–1.9 and 1.11
were added by the 2026-09-20 review and are not yet issue-tracked.

**Done when:** every critical and high finding is merged, and the chain has a
passing append-to-verify round-trip test (not just a passing QA harness).

---

## 2. Clear the P0 trust gates

These outrank the launch goal. No real clinic data before they close.

| # | Gate | Issue | State |
| --- | --- | --- | --- |
| 2.1 | Protect PHI in durable storage and enforce retention and deletion | #5 | open |
| 2.2 | Replace placeholder FastAPI identity and tenant scoping with verified authorization | #6 | open |
| 2.3 | Back up and restore all production databases and durable state | #12 | open |
| 2.4 | Verify deployment controls and approve compliance claims before pilots | #14 | open — decision |
| 2.5 | Rotate the documented compromised LLM credential and verify the incident | #10 | open |
| 2.6 | Verify production contact delivery and assign lead ownership | #74 | open |

**Done when:** each is closed with evidence against production, and a
restore-verified backup is recorded for the release.

---

## 3. Owner decisions on the critical path

Engineering cannot start these. They gate outreach, the agreement, and the
pricing page.

| # | Decision | Issue | Needed by | State |
| --- | --- | --- | --- | --- |
| 3.1 | Pilot offer: paid or free, term, single fee, inclusions | #76 | — | **DECIDED 2026-09-20** — paid: 60-day pilot, CAD $1,500 one-time, credited against first month, no automatic conversion. Qualification boundaries still open. |
| 3.2 | Pricing, packaging, sustainable unit economics | #108 | — | partial — pilot fee set; unit economics and packaging open |
| 3.3 | Engage counsel on the HIA Information Manager Agreement | #14 | immediately | **open — the critical path.** Longest external lead time. If not engaged in week 1, reset the target to 60 days. |
| 3.4 | Enable branch protection on `main` | — | — | open — CI itself is now working; only the protection rule remains |

**Done when:** counsel is engaged, unit economics are decided, and branch
protection is on. Item 3.3 is the single most likely cause of a missed date and
it is the only gate not under our control — treat it as day one.

---

## 4. Reach a genuinely working product for humans

This is the part the first paid pilot will actually test. It is ordered by what
a clinic's billing lead and privacy reviewer will notice.

### 4.1 The clinic team can complete the core job without help

- [ ] Onboarding is one completable, recovery-safe flow (#38)
- [ ] Active-clinic context and switching are verified (#37)
- [ ] Encounter review preserves queue context and navigation (#39)
- [ ] Hidden encounter selections cannot leak across list changes (#40)
- [ ] Team role changes are transactional and confirm privilege elevation (#42)
- [ ] Prorated billing tier changes are reviewed and confirmed (#41)
- [ ] Clinic settings are validated and announced at field level (#43)

### 4.2 The product behaves predictably when something goes wrong

- [ ] A user-facing status, error, recovery, and support contract exists (#46)
- [ ] `/readyz` asserts a real dependency round-trip, not just config presence
- [ ] The v1 API survives a restart without losing a completed audit (1.8)

### 4.3 It is accessible and fast enough to trust

- [ ] WCAG 2.2 AA on the FastAPI public navigation (#29)
- [ ] Reproducible WCAG 2.2 AA responsive browser and performance gates (#30)
- [ ] The render-blocking CSS bundle is reduced and cached with measured budgets (#33)
- [ ] Safari, Firefox, and assistive-technology checks on the public routes
      (currently Chrome-only per `docs/MARKETING_PUBLIC_LAUNCH_GATES.md`)

### 4.4 The marketing surface can say something true and useful

- [ ] Approved claim register with a source and re-review date per claim
- [ ] Deferred routes (`/pricing`, `/security`, `/case-studies`, `/pilot`, …)
      either approved for indexing or clearly held back
- [ ] Approved privacy policy, terms, and pilot agreement language
- [ ] Contact and email delivery, bounce handling, retention, and response
      ownership verified (pairs with 2.6)
- [ ] Monitoring has a real alert destination, incident owner, and public update
      process (currently a five-minute cron probe with no alert destination)

### 4.5 The operator workspace works

- [ ] Zorva HQ platform-admin and operator foundation (#89)
- [ ] The complete authenticated HQ operator journey is verified (#106)

**Done when:** a clinic team can sign in, get their claims audited, review every
finding, act on it, and export an action plan — and a privacy reviewer can read
the public claims and the agreement without finding an overreach.

---

## 5. Land the first paid pilot

Target: **2026-10-20**. "Signed" means all three of: a countersigned HIA IMA, a
first invoice issued and paid or committed in writing, and one real reviewed
audit completed end to end.

| # | Step | Issue | State |
| --- | --- | --- | --- |
| 5.1 | Approve the pilot offer and qualification boundaries | #76 | partial |
| 5.2 | Prepare and run the controlled Alberta clinic outreach pilot | #78 | open |
| 5.3 | Produce the evidence-safe launch kit (drafts exist; none approved for use) | #77 | open — all assets "Prohibited" for external use |
| 5.4 | Run the Alberta clinic customer-validation and learning loop | #109 | open |
| 5.5 | Complete and validate the conversion-focused marketing website | #107 | open |
| 5.6 | Qualify the real audit provider and AI review journey | #105 | open |

**Sequence that actually works:** counsel first (3.3, longest lead time) →
approve the launch kit and qualification boundaries (5.1, 5.3) → outreach
(5.2) → pilot (5.4). Outreach before counsel is engaged risks a signed-intent
clinic that cannot be onboarded.

**Done when:** a real clinic has paid or committed in writing and one real
reviewed audit is complete with a verified audit-trail entry.

---

## Sequencing summary

| Phase | Focus | Gate to leave the phase |
| --- | --- | --- |
| Now | 1.2–1.6 (chain, guardrails, SSRF, RBAC) + 3.3 (engage counsel) | Critical/high findings closed; counsel engaged |
| Next | 2.1–2.3 (PHI, identity, backups) + 1.9 (trigger) | All P0 trust gates closed with production evidence |
| Then | 4.1–4.5 (product polish, a11y, marketing, HQ) | Core journey verifiable by a clinic team and a privacy reviewer |
| Finally | 5.1–5.6 (kit, outreach, pilot) | Countersigned IMA + invoice + one real reviewed audit |

---

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Counsel is not engaged in week 1 | Misses 2026-10-20; pilot slips to November | Engage immediately (3.3); reset the target to 60 days rather than discovering it late |
| Real clinic data reaches the product before the P0 gates close | Breaks the guardrails the launch goal is subordinate to | Synthetic data only until 2.1–2.3 close |
| The audit chain is used as evidence while 1.2 is open | A compliance claim rests on a verifier that fails its own append path | Close 1.2 before any pilot evidence is shown to a clinic |
| Outreach goes out before the launch kit is approved | Unsupported or fabricated claims reach prospects | Every launch-kit asset is currently "Prohibited"; approve before send |
| Branch protection stays off | `main` can regress without a gate | Enable it; CI is already green |
| Solo-operator bandwidth | Several phases need the same person | The sequence above is strictly ordered so one phase is active at a time |

---

## Next safe action

**Engage counsel on the HIA Information Manager Agreement (#14)** — it is the
longest external lead time and the only critical-path item not under our
control. In parallel, close the chain defect (**1.2 / #113**), because a
compliance product cannot present evidence from a chain that fails its own
verification.
