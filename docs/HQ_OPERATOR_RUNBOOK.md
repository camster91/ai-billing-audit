# Zorva HQ operator runbook

**Status:** repository-backed operating procedure; production verification and
named role grants remain approval-gated

**Audience:** accountable owner and explicitly authorized Zorva operators

**Scope:** commercial and company operations only; never a clinical-record console

## Non-negotiable boundaries

- Sign in through the normal portal flow and use a separately granted active
  platform role. A clinic tenant role does not grant HQ access.
- Do not enter patient names, health numbers, diagnoses, encounter content,
  findings, claim lines, or clinical notes into HQ.
- HQ records work and evidence. It does not send outreach or support replies,
  publish content, launch campaigns, spend funds, change pricing or SLAs,
  provision a clinic tenant, or grant production roles.
- Every such external or privileged action needs its own named approval and
  must be performed through the separately approved channel.
- Treat `Unknown` as missing measurement and `Unavailable` as no approved data
  source. Never replace either with zero.

## Start-of-day review

1. Open `/hq`. Confirm the role shown is the intended platform role and record
   the generated timestamp before acting on Today counts.
2. Triage new and unowned leads. Assign only active owner/sales users and set a
   dated commercial next action. Log a contact only after it actually happened.
3. Review overdue company tasks and onboarding blockers. Store a reference to
   approved business evidence, not copied customer or clinical material.
4. Review open/high-priority support cases. Assign an eligible operator and use
   internal target dates only; they are not customer-visible SLA promises.
5. Open `/hq/reports` as an owner or analyst. Check metric state, source, period,
   and definition before using a number in a decision or external artifact.

If a count cannot be opened to its underlying records, its freshness is absent,
or the source contradicts the displayed value, stop using that metric and open
an internal no-PHI support/product issue. Do not repair the database manually.

## Lead-to-client operation

1. In Leads, confirm the clinic/contact is not an obvious duplicate. Current
   software does not perform automated deduplication, so apparent duplicates
   must remain separate until an approved merge procedure exists.
2. Progress stages only when the recorded commercial event occurred. A lost
   lead requires a safe loss reason; terminal stages cannot retain next actions.
3. Convert only a `pilot_signed` lead. Conversion creates a commercial
   engagement and onboarding tasks; it does not create a tenant or send a
   welcome message.
4. Record privacy approval, pilot dates, first value, health, task evidence, and
   the pilot decision as they occur. Tenant linkage and real-data onboarding
   remain separately approved customer actions.

On a version conflict, reload and compare the newer record. Never resubmit by
changing the mutation ID until the operator has confirmed whether the first
logical action succeeded. Retrying the same action uses the same mutation ID.

## Marketing operation

1. Draft the exact claim and attach its evidence and allowed surfaces.
2. Obtain owner approval before marking a claim approved. Customer-derived
   evidence also requires the written-permission reference.
3. Link claim-bearing content to a current approved claim for the exact channel.
4. Plan a campaign with a stable source key and landing/UTM identity. Approved
   budget or recorded spend needs its approval reference.
5. Record `observed_active` only after the owner has evidence that an externally
   approved launch occurred. HQ itself does not launch it.
6. Add attribution snapshots from named source exports. Enter zero only when the
   source measured zero; leave absent metrics null/unknown.

Do not add attributed campaign rows together unless their periods and population
are proven non-overlapping. The report intentionally shows one latest row per
campaign rather than manufacturing a company revenue total.

## Support operation

1. Create only an internal no-PHI summary linked to an existing engagement.
2. Set category, severity, owner, and internal target. Use the separately
   approved customer channel for any reply, then update HQ only with safe
   operational state.
3. `acknowledgedAt` and `resolvedAt` are derived from workflow status. Do not
   backdate them to improve reporting.
4. Link a product issue by safe reference. Duplicate linking, reopen policy,
   customer intake, and post-incident follow-up are not yet automated.
5. If patient or clinical content is exposed, stop normal support handling and
   follow `docs/operations/INCIDENT-RESPONSE.md`.

## Weekly company review

- Review the trailing-30-day acquisition, closed-decision pilot rate,
  engagements, first-value milestones, support load, and campaign evidence.
- Inspect definitions before comparing periods. Current open-client, at-risk,
  and urgent-support values are snapshots, not historical period totals.
- Company recognized revenue and cost to serve remain unavailable until approved
  accounting and cost-allocation sources exist. Campaign-attributed revenue is
  evidence from a marketing source, not recognized accounting revenue.
- Record decisions and owners in the governing project/issue. Do not change
  public pricing, customer SLAs, campaign spend, or external copy from the
  report alone.

## Access, incident, and recovery

- Production role grant/revoke uses `pnpm hq:manage-role` only after normal
  sign-in and exact approval. Follow `docs/COMPANY_ADMIN_SPEC.md`; never create a
  user or edit role tables directly.
- A missing HQ page for a signed-in user normally means the platform capability
  denied access. Verify the role through the approved administrative path; do
  not weaken server authorization or add an email allowlist.
- Preserve request IDs, timestamps, record IDs, deployed commit, and safe error
  text when reporting a failure. Never paste secrets or PHI into an issue.
- For application or database recovery use `docs/OPERATIONS_RUNBOOK.md` and the
  approved backup/restore process. HQ history is append-only; do not delete or
  rewrite events as a recovery shortcut.

## Readiness evidence still required

This runbook does not prove production readiness. Before HQ is used to operate a
real pilot, verify on the exact deployed artifact: owner login, tenant-only and
role-denial cases, lead-to-client workflow, support workflow, reporting access,
append-only history, backup/restore, representative keyboard/mobile behavior,
monitoring, retention/export decisions, and Canadian/Alberta data-handling
evidence. Each production role grant and release remains separately approved.
