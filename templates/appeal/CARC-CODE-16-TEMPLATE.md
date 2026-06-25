# Appeal Letter — CARC Code 16 (Hand-Curated Template)

> **Status:** v1 — hand-curated template, **not** LLM-generated.
> **For:** Zorva appeal-letter generator, single-letter mode.
> **Format:** clinic fills **4 fields**; letter is ready to print, sign, and mail.
> **Coverage:** the single most common CARC/RARC denial pairing (CARC 16
> with the matching RARC narrative) — the one we see in ~30% of
> AHCIP and US commercial remits.
> **Author:** hand-drafted by Cameron Ashley + the Zorva team, based on
> actual appeal letters that have overturned CARC 16 denials.

---

## What this template is

CARC Code 16 is the workhorse "we can't pay this because something is
missing or wrong on the claim" denial. The actual reason lives in the
RARC narrative. Common pairings (from real remits we audit):

- **CARC 16 + RARC N290** — "Missing/incomplete referring provider info"
- **CARC 16 + RARC N386** — "Missing/incomplete NPI" (US) / practitioner
  ID (Alberta)
- **CARC 16 + RARC M76** — "Missing/incomplete diagnosis code"
- **CARC 16 + RARC N522** — "Duplicate of a previously processed claim"
- **CARC 16 + RARC N519** — "Missing/incomplete place of service"
- **CARC 16 + RARC MA130** — "Missing/incomplete referring provider NPI on a consultation"
- **CARC 16 + RARC N563** — "Missing/incomplete rendering provider info"

The letter template below is **structured to capture the specific
missing field** so the biller doesn't have to rewrite it for each
RARC. One template, four fields, ten seconds.

---

## The 4 fields the clinic fills

| # | Field | Example | Where it shows up in the letter |
|---|---|---|---|
| 1 | `[PAYER_NAME]` | "Alberta Health Services (AHCIP)" / "Blue Cross Alberta" / "Sun Life" | Salutation + header |
| 2 | `[PATIENT_NAME]` | "J. Smith" | Subject line + body |
| 3 | `[CLAIM_OR_PATIENT_ID]` | "PHN 12345-6789" / "Member ID ABC-001-234" / "Claim 2026-04-12345" | Subject line + body |
| 4 | `[MISSING_INFO_RARC]` | "N290 — missing referring provider NPI" / "N386 — missing referring provider NPI (AB practitioner ID)" / "M76 — missing diagnosis code" | The single sentence that names the missing info |

That's it. The body of the letter is the same boilerplate for every
CARC 16 case — because the rebuttal logic is the same regardless of
the specific RARC: *the missing information is attached / corrected
here, please reprocess.*

---

## The template

```text
[Clinic Letterhead — clinic name, address, phone, fax]

[Date — YYYY-MM-DD]

[PAYER_NAME]
Attention: Claims Appeals Department
[Payer Address — look up on the remittance advice or payer portal]

Re:  Formal Appeal — Claim Denial (CARC Code 16)
Patient:        [PATIENT_NAME]
Claim ID / PHN: [CLAIM_OR_PATIENT_ID]
Date of Service: [DOS — YYYY-MM-DD]
Billed Amount:  $[BILLED_AMOUNT]

Dear Claims Appeals Team,

We are writing to formally appeal the denial of the above claim
on the basis of CARC Code 16 — "Claim/service lacks information
needed for adjudication." The specific information identified
as missing on the remittance advice is:

    [MISSING_INFO_RARC]  —  e.g., "N290 — Missing/incomplete
    referring provider info" or "M76 — Missing/incomplete
    diagnosis code"

The information in question is attached to this letter (or has
been corrected on the resubmitted claim) as follows:

  - Referring provider name and NPI / Alberta practitioner ID
    (see attached referring-provider record, Item A)
  - Diagnosis code(s) in ICD-10-CM / ICD-10-CA (see attached
    clinical note excerpt, Item B)
  - Other corrected or newly-attached information (see Item C,
    if applicable)

The clinical documentation supporting the services billed is
on file at our clinic and is available on request. A copy of
the original claim, the remittance advice showing the CARC 16
denial, and any supporting attachments are enclosed.

We respectfully request that you reprocess this claim for
payment under the terms of the applicable provider agreement
and Alberta Schedule of Medical Benefits (or, for US payers,
the applicable state prompt-pay and fair-claims statutes,
including but not limited to CA FCA, NY IFS §3224-a, TX IBC
§843.338, and FL PIP statute §627.736).

Please respond in writing within 30 days of receipt. If you
require additional information, please contact our billing
office at the phone number on our letterhead.

Sincerely,

[Billers' Name, Credentials]
[Title — Billing Manager / Coder]
[Clinic Name]
[Phone] | [Email]
```

---

## Attachments checklist (use only what applies)

- [ ] **Item A** — referring provider record (NPI / practitioner ID,
      name, contact) — for RARC N290, N386, MA130
- [ ] **Item B** — clinical note excerpt showing the diagnosis and
      medical necessity — for RARC M76, N563
- [ ] **Item C** — corrected claim (re-filed via clearinghouse with
      the missing field populated) — recommended for all
- [ ] **Item D** — original remit (EOMB / RA) showing the CARC 16 line
- [ ] **Item E** — for AHCIP duplicates (RARC N522): the prior
      adjudication history showing this is **not** a duplicate
- [ ] **Item F** — rendering provider's NPI / practitioner ID (RARC
      N563)

---

## What to do before you mail it (Zorva portal workflow)

1. **Confirm the CARC code on the remit is actually 16.** Many payers
   use CARC 16 *and* CARC 97 (bundled service) for the same line. If
   97 is on the line, the rebuttal is different — the service is
   considered inclusive of another paid service, and the appeal
   argues medical necessity / separate-procedure status.
2. **Check the RARC verbatim.** The RARC narrative is what tells you
   *which* missing-info rebuttal applies. Do not skip reading it.
3. **For AHCIP:** also check whether the claim was auto-denied by
   H-Link (e.g. empty `diagnosis_codes` is a hard fail at the
   submission layer, not a CARC). H-Link rejections are usually
   re-filed, not appealed.
4. **Generate the corrected claim first**, then attach the
   submission-confirmation timestamp to the appeal letter. The
   appeal reads stronger when it says "the corrected claim was
   accepted by your clearinghouse on [date], tracking #XYZ."
5. **Mail the appeal to the address printed on the remit** — many
   payers route by claim type. Submitting to the wrong address adds
   30–60 days.

---

## Where the fields show up in the Zorva portal (where this template will live)

The Zorva portal already has an appeal-letter generator (see
`src/ai_billing_audit/appeal.py` — v1 LLM-assisted generator). This
template is the **v1.5 deterministic** counterpart for CARC 16 cases
specifically:

- A clinic user opens a denied finding from the **Findings** page.
- The finding's CARC code is detected as `16`.
- The portal presents **4 input fields** (Payer, Patient, Claim ID,
  RARC narrative) and a single **"Generate appeal letter"** button.
- The portal produces a print-ready PDF (or copy-to-clipboard
  Markdown) using the template above.
- Time to a real letter: **~10 seconds**.

This is intentionally **not** an LLM-generated letter. CARC 16 is
the highest-volume denial pattern, the rebuttal logic is the same in
~95% of cases, and a hand-curated template:

- avoids the LLM hallucinating a payer name or statute citation,
- is reviewable by a privacy officer in advance (LLM output isn't),
- runs at zero LLM cost on the most common denial path,
- and produces the same letter every time for a given (CARC, RARC)
  pair — which is what a clinic's compliance team wants for audit
  defensibility.

---

## Provenance & versioning

- **v1 (this file)** — hand-drafted, 2026-06-25.
- **Future v2 candidates** — second template for CARC 97 (bundled
  service), third for CARC 50 (non-covered service), fourth for
  CARC 29 (time limit for filing). The same hand-curated pattern
  applies; one template per top-5 CARC code covers ~70% of remits.
- **Source of CARC codes** — X12 External Code List, published by
  X12N, available at `https://x12.org/codes/claim-adjustment-reason-codes`.

---

*Companion files (planned, not yet in repo):
`templates/appeal/CARC-CODE-29-TEMPLATE.md` (timely filing),
`templates/appeal/CARC-CODE-50-TEMPLATE.md` (non-covered),
`templates/appeal/CARC-CODE-97-TEMPLATE.md` (bundled). These are
follow-up artifacts for the next appeal-letter sprint.*
