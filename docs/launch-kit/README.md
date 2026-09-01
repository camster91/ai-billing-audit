# Zorva controlled launch kit

**Status:** draft; not approved for publication, sending, or prospect use
**Owner:** Cameron Ashley
**Last reviewed:** 2026-09-01
**Governing plan:** `docs/MASTER_PLAN.md`
**Tracker:** GitHub issue #77

This folder is the versioned source for Zorva's controlled Alberta launch
materials. It turns one approved positioning direction into reusable drafts
without inventing customer proof, pricing, service levels, compliance claims,
or performance outcomes.

Nothing here authorizes outreach. Before any asset is used externally, the
owner must approve the exact asset, the pilot offer in issue #76, every claim
referenced by the asset, the audience, and the send or publication action.

## Common message contract

- **Audience:** Alberta primary-care clinic owners, practice managers, and
  billing leads; privacy and IT reviewers are a required trust audience.
- **Category:** human-reviewed, pre-submit AHCIP claim review.
- **Promise:** help a billing team review potential claim problems before
  submission while keeping the final decision with the clinic.
- **Primary CTA:** `Start a conversation`.
- **Canonical journey:** `https://zorva.ashbi.ca/` ->
  `https://zorva.ashbi.ca/how-it-works` ->
  `https://zorva.ashbi.ca/contact`.
- **Boundary:** Zorva does not submit claims, replace billing judgment, promise
  savings, or represent itself as a certified compliance system.

## Asset register

| Asset | Owner | Approval state | External use | Claim IDs |
| --- | --- | --- | --- | --- |
| `ONE_PAGE_OVERVIEW.md` and exported PDF | Cameron Ashley | Draft - owner and claim review required | Prohibited | ZC-001 through ZC-005 |
| `FOUNDER_ANNOUNCEMENT.md` | Cameron Ashley | Draft - owner and claim review required | Prohibited | ZC-001 through ZC-004 |
| `LINKEDIN_DRAFTS.md` | Cameron Ashley | Draft - owner and claim review required | Prohibited | ZC-001 through ZC-004 |
| `OUTREACH_SEQUENCE.md` | Cameron Ashley | Draft - offer, audience, and send approval required | Prohibited | ZC-001 through ZC-005 |
| `WARM_INTRO_REQUEST.md` | Cameron Ashley | Draft - offer and send approval required | Prohibited | ZC-001, ZC-002, ZC-004 |
| `DISCOVERY_CALL.md` | Cameron Ashley | Draft - operating review required | Internal preparation only | ZC-001 through ZC-005 |
| `OBJECTIONS_FAQ.md` | Cameron Ashley | Draft - claim and privacy review required | Prohibited | ZC-001 through ZC-005 |

`CLAIM_MANIFEST.json` is the machine-readable claim/source and asset register.
`scripts/validate-launch-kit.mjs` fails if a draft loses its approval banner,
uses an unregistered claim, links to an unapproved public route, omits campaign
attribution from an external CTA, or introduces known unsafe claim language.

## Attribution convention

Private-share and outreach links use only `utm_source`, `utm_medium`, and
`utm_campaign`. They must never contain a person's name, email, clinic, message,
or another stable personal identifier. The campaign value for this kit is
`controlled_alberta_launch_v1`; the source and medium identify the asset, not
the recipient.

## Approval checklist

- [ ] Issue #76 contains the approved pilot duration, scope, inclusions,
  qualification boundaries, success/stop criteria, and commercial terms.
- [ ] Each claim in `CLAIM_MANIFEST.json` has an accountable approver,
  approval date, review date, and public-use permission.
- [ ] The exact asset and exact recipient or publication surface are approved.
- [ ] Contact delivery and named lead ownership are verified in production.
- [ ] Canonical routes and UTM persistence pass the current browser gate.
- [ ] The one-page PDF passes text extraction, single-page, link, and rendered
  visual QA after its final edit.
- [ ] No clinic identity, testimonial, logo, result, PHI, or prospect PII is
  present without written permission and a separate claim review.
