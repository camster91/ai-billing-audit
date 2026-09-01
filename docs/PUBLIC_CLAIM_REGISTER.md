# Zorva core public claim register

**Scope:** indexable routes `/`, `/how-it-works`, and `/contact`
**Owner:** Cameron Ashley
**Status:** core positioning reconciled in code; exact-artifact review and release approval pending
**Last reviewed:** 2026-09-01
**Authority:** `docs/MASTER_PLAN.md` and `docs/MARKETING_PUBLIC_LAUNCH_GATES.md`

This register covers the deliberately small public journey. It does not approve
deferred pricing, security, legal, status, demo, case-study, comparison, or
specialty routes. Those routes retain their own evidence and promotion gates.

## Allowed core statements

| ID | Exact bounded statement | Source | Evidence type | Owner | Review state |
| --- | --- | --- | --- | --- | --- |
| PC-001 | Zorva is designed as a human-reviewed, pre-submit AHCIP workflow for Alberta primary-care billing teams. | `docs/MASTER_PLAN.md` product charter and commercial plan | Authoritative positioning; not a performance result | Cameron Ashley | Allowed on core routes; re-review before release |
| PC-002 | The clinic's authorized billing team keeps the final decision about what, if anything, is submitted. | `apps/portal/src/app/how-it-works/page.tsx`; customer finding accept/dismiss workflow | Implemented workflow boundary | Cameron Ashley | Allowed on core routes; re-review before release |
| PC-003 | The workflow is designed to place available billing context and supporting references beside an encounter for assessment. | `apps/portal/src/app/how-it-works/page.tsx`; rendered encounter/finding review surfaces | Qualified capability description; no completeness claim | Cameron Ashley | Allowed on core routes; re-review before release |
| PC-004 | Zorva is initially exploring fit with Alberta primary-care teams using AHCIP, with a named workflow owner and human reviewer. | `docs/MARKETING_PLAN.md` audience and buying group | Explicitly framed qualification hypothesis | Cameron Ashley | Allowed only with “exploring fit” qualification |
| PC-005 | The current public next step is a reviewed request for a conversation, not self-serve production access. | `docs/MASTER_PLAN.md` focused offer; `/contact` implementation | Current conversion boundary | Cameron Ashley | Allowed on core routes; offer terms remain unapproved |
| PC-006 | A first contact should contain non-clinical workflow context, not patient, claim, credential, or production-access data. | `/contact` form contract; `docs/COMPANY_ADMIN_SPEC.md` no-PHI boundary | Data-minimization instruction | Cameron Ashley | Allowed as a safety instruction |

## Illustrative content contract

The homepage review panel is a static workflow illustration. It uses no patient
identity, fee code, dollar amount, result, performance metric, or assertion that
a particular billing change is correct. Its visible label must retain the word
`ILLUSTRATIVE`. It is not a live product response, customer example, benchmark,
or pilot result.

## Explicitly excluded from the core routes

Until separate evidence and accountable approval exist, the core routes must
not state or imply:

- savings, recovery, revenue lift, ROI, denial reduction, accuracy, coverage,
  completeness, or customer outcomes;
- a price, fee model, tier, discount, refund, pilot duration, included volume,
  service level, response time, or guarantee;
- certification, regulatory compliance, legal safe-harbour, data residency,
  region isolation, processor, encryption, retention, or contractual status;
- support for a specific code set, rule family, payer edit, integration,
  autonomous submission, or production availability unless the exact current
  contract and implementation are approved;
- a testimonial, clinic identity, logo, case study, customer count, or adoption
  statement without written permission and claim review.

## Verification contract

`apps/portal/tests/public-homepage-claims.test.ts` prevents known historical
claims from returning to the three core route sources. It also ensures the
homepage links only to `/contact` and `/how-it-works`, keeps the bounded CTA and
safety instructions, and labels the static review without fabricated codes or
dollar outcomes. Search tests are a regression guard, not product, privacy, or
legal approval.
