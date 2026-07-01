# Invitation to Audit Zorva

> **Audience:** a third-party auditor (CPACC, IAPP, SOC 2 assessor),
> a customer's privacy officer, an OIPC / IPC / OPC investigator,
> or any qualified reviewer evaluating whether Zorva is safe to
> process personal health information on behalf of their
> organisation.
>
> **Cost:** free. We pay nothing; you pay nothing. The only ask is
> the acknowledgment at the bottom of this page, signed and returned
> to `audit@ashbi.ca` before access is granted.

---

## Why we publish this

The strongest privacy posture is the one that can be independently
verified. We are a small company, the auditor's independence is the
only thing that makes our claims auditable, and we'd rather do the
work to enable your review than have you take our word for it.

If you find something we missed, we'd genuinely like to know. If
you find something we got right, we'd like to be able to cite it.

---

## What we invite you to look at

The following are **in scope** of an audit. Each item lists where
to start and what "good" looks like.

### 1. The `audit_trail` and its hash chain

**Where:** `docs/RUNBOOK.md` §1 (the chain construction + the
verification command).

**What to check:**

- `audit_trail` table is append-only. There is no `UPDATE` or
  `DELETE` path in the application code.
- `cryptographic_signature_i = SHA-256(previous_signature_i || ...)`.
  Verify the formula matches what the code computes (live code:
  `src/ai_billing_audit/audit_actions.py`, function `append()`).
- Run the chain verifier on a copy of the production database. A
  break at any index is the highest-trust finding the audit can
  produce.

**Evidence you can take:** a row-count, the verifier script's
SHA-256, the exit code, and the timestamp. That's enough to
demonstrate the chain was intact on the day of the audit.

### 2. The `MANIFEST.json` prompt-version ledger

**Where:** `prompts/MANIFEST.json` and
`docs/research/PROMPT-ITERATION-PLAYBOOK.md` §6.

**What to check:**

- Exactly **one** entry has `status: "active"`. All others are
  `archived`.
- The active entry's `version_hash` matches `sha256sum
  prompts/v12/auditor_prompt.txt` on the live VPS.
- The chain `parent_hash` → `version_hash` → `parent_hash` of the
  next entry is unbroken.

This ledger is the answer to "which prompt is running in production
right now?" — the question that, if you can't answer it, makes every
other privacy claim moot.

### 3. The model output redactor

**Where:** `src/ai_billing_audit/auditor.py`
(`RESPONSE_JSON_SCHEMA`) and the test suite
`tests/test_auditor_redaction.py`.

**What to check:**

- The response schema forbids the LLM from emitting free-text that
  echoes the clinical note verbatim. Specifically, the `quote`
  field is a short verbatim span from the **rule reference**, not
  from the clinical note.
- The `_quote_in_note()` validator (same file) rejects any
  proposed finding whose `quote` appears in the clinical note
  unchanged.
- The test suite runs a known-bad input through the auditor and
  asserts the bad output is rejected.

### 4. The data-residency / region posture

**Where:** `deploy-to-vps.sh`, `docker-compose.yml`,
`Dockerfile`, `SECURITY.md`.

**What to check:**

- The LLM provider (`LLM_BASE_URL`) is set to a Canadian / in-region
  endpoint (Minimax US for now, but no EU; configurable per
  customer).
- The VPS region is documented in the deploy script (`grep -i
  region deploy-to-vps.sh`).
- No outbound calls in the running container (`docker exec zorva-api
  sh -c 'cat /etc/resolv.conf && netstat -tunap'`) other than to
  the database and the LLM provider.

### 5. The contractual notification obligations

**Where:** `docs/BAA_TEMPLATE_PHIPA.md` (Ontario PHIPA),
`docs/BAA_TEMPLATE_HIPAA.md` (US HIPAA),
`docs/BAA_TEMPLATE_HIC_AGENT.md` (Alberta HIA).

**What to check:**

- Section 11 of each BAA template specifies breach-notification
  timelines. Verify they line up with
  `docs/operations/INCIDENT-RESPONSE.md` §7.
- The "agent" language (PHIPA) / "business associate" (HIPAA) /
  "HIC agent" (HIA Alberta) is consistent with the technical
  control set (i.e., we actually have the controls the contract
  says we have).

### 6. The test suite as a control

**Where:** `tests/`.

**What to check:**

- The CI pipeline (`.github/workflows/test-on-pr.yml`) runs ruff +
  mypy + pytest + tsc on every PR.
- The pytest suite includes `tests/test_audit_log.py` (chain
  construction) and `tests/test_auditor_redaction.py` (output
  redaction).
- Test count, last green commit, and the count of skipped tests.

A test that doesn't run is not a control. We will show you the
green CI run for `main` as of the day of the audit; the SHA is in
the audit report.

### 7. The incident-response runbook

**Where:** `docs/operations/INCIDENT-RESPONSE.md`.

**What to check:**

- Severity levels (§2) and notification SLAs (§7) match the
  regulatory obligations in §1.2.
- The "first 15 minutes" checklist (§1.3) is actually executable
  on a clean laptop with the documented commands.
- A tabletop drill has been run in the last 90 days (per §11).
  We will produce the drill record from `docs/RUNBOOK_DRILLS/`.

---

## What we invite you NOT to look at

The following are **out of scope** of an audit and will not be
made available, even under NDA. This is not a refusal to be
transparent — it's the difference between an audit (verifiable
claims about behaviour) and a trade-secret review (which is a
different conversation, with a different contract and a price tag).

| Item                                             | Why                                              |
|--------------------------------------------------|--------------------------------------------------|
| **Proprietary model weights** (if any are added later; today we use a hosted LLM only). | Trade secret. The audit-relevant question — "what does the model emit?" — is answered by §3 above. |
| **Customer PHI** in any form, other than redacted summary statistics. | The privacy posture is the audit; the data is not. An auditor can run the chain verifier on a copy of the `audit_trail` we provide *without* seeing the underlying `data_elements` payloads. |
| **Customer business metrics** (claims processed, fees recovered, etc.). | Customer-confidential. Available to that customer on request via their dashboard. |
| **Internal cost / pricing / margins.**            | Not relevant to a privacy or security audit.     |
| **The names of other customers** or pilots.       | Customer-confidential. Available on a need-to-know basis under a counter-signed MNDA. |
| **Our internal kanban / Notion / Slack archives.** | Not relevant to a privacy or security audit, and contains employee personal data. |
| **Employee personnel files.**                     | Outside the auditor's mandate.                   |

If any of the above is something you genuinely need (for example,
a regulator investigating a specific incident), please contact
`audit@ashbi.ca` and we'll discuss the right channel — typically a
subpoena, an information request under PHIPA / HIA / PIPEDA, or
a mutual assistance arrangement with your office.

---

## What the audit will cost

**Free.** For the categories above.

Specifically:

- We provide a sanitised read-only copy of the `audit_trail` (chain
  intact, `data_elements` redacted to rule_ids and patient_hash
  only — no PHI).
- We provide a static export of the relevant source files and the
  prompt manifest.
- We answer written questions within 5 business days.
- We make an engineer available for a 60-minute walkthrough.

What we do not pay for:

- Your time. We won't invoice you, and we won't accept an invoice.
- Legal fees. If your audit requires legal review on your side,
  that's your cost.

What we ask in return:

- A signed acknowledgment (the template is at the bottom of this
  document) that you have read §"What we invite you NOT to look at"
  and agree not to request those items through this audit channel.
- A summary of findings we can publish (anonymised at your option).
  We will not publish findings without your consent, but if you
  give consent, we'd genuinely like to.

---

## How to start

Email `audit@ashbi.ca` with:

1. Your name, role, and organisation.
2. The framework you're auditing against (PHIPA / HIPAA / SOC 2 /
   ISO 27001 / internal policy / etc.).
3. The specific items from §"What we invite you to look at" that
   you want to start with (you don't have to take all seven).
4. The expected duration and any deadlines.

We will reply within 2 business days with:

- The acknowledgment template (§below).
- A read-only PostgreSQL dump of the relevant audit_trail
  partition.
- A tarball of the relevant source files at the SHA we cite in
  the response.

We will not require an NDA for the items in §"What we invite you
to look at." If you need an NDA to receive the dump (some
organisations do), we have a short mutual NDA at
`docs/MUTUAL_NDA_AUDIT.md` — that's a 2-page document, no surprises.

---

## Acknowledgment template

> The auditor returns this signed to `audit@ashbi.ca` before
> access is granted.

```
Subject: Audit acknowledgment — Zorva self-audit invitation

To: Ashbi Design Inc. (operating the Zorva pre-submit claim-audit
    service), attn. Privacy Officer

I, [name], acting on behalf of [organisation / office], acknowledge
that:

1. I have read the Zorva self-audit invitation at
   docs/AUDIT-INVITATION.md (commit [SHA], dated [date]).

2. I will limit my review to the items listed under "What we invite
   you to look at" and will not request, through this audit channel,
   any of the items listed under "What we invite you NOT to look at."

3. I will treat the read-only PostgreSQL dump of audit_trail and
   the source-file tarball as confidential to [organisation] and
   will not redistribute them.

4. Findings I produce from this audit may be shared with Zorva for
   the purpose of remediation, and (with my consent) may be cited
   by Zorva in its security and privacy disclosures.

Signed:
   Name:
   Role:
   Organisation:
   Date:
   Signature:
```

---

## What we promise in return

If you find something that is genuinely a bug — a missing control,
a misconfigured default, a documentation gap that creates
ambiguity — we will:

1. Acknowledge the finding within 5 business days.
2. Triage it within 10 business days.
3. Fix critical and high findings within 30 days.
4. Credit you in the fix's CHANGELOG entry (unless you ask not
   to be credited).
5. Not pursue legal action for the act of reporting the finding
   in good faith. (See also `SECURITY.md` — our coordinated
   disclosure policy.)

This is the same commitment we'd want from a vendor we're auditing.

---

## Further reading

- `SECURITY.md` — coordinated disclosure policy.
- `docs/RUNBOOK.md` §1 — the audit_trail chain verifier.
- `docs/operations/INCIDENT-RESPONSE.md` §7 — the notification
  obligations this audit verifies.
- `docs/BAA_TEMPLATE_PHIPA.md` / `docs/BAA_TEMPLATE_HIPAA.md` /
  `docs/BAA_TEMPLATE_HIC_AGENT.md` — the contractual artefacts
  the audit maps to the technical controls.
- `docs/research/PROMPT-ITERATION-PLAYBOOK.md` — the prompt
  iteration discipline that the MANIFEST.json ledger enforces.

---

*This invitation is at v1.0, dated 2026-06-25. The SHA-256 of this
file at the time of audit is part of the audit record.*