# Information Manager Agreement — Alberta HIA

> **DRAFT — LEGAL REVIEW REQUIRED.**
> This template has **not** been reviewed by a lawyer.
> **Do not use for any real pilot until reviewed by qualified Alberta
> counsel** familiar with the *Health Information Act*, RSA 2000, c H-5
> ("HIA"), the *Health Information Regulation*, Alta Reg 70/2001, the
> *Personal Information Protection Act*, SA 2003, c P-6.5 ("PIPA
> Alberta"), and the *Personal Information Protection and Electronic
> Documents Act* (PIPEDA), where applicable.
> Replace every `[...]` placeholder before signing.
>
> The Ontario PHIPA version of this agreement (which uses the "HIC
> Agent" terminology that HIA does not) lives at
> `docs/BAA_TEMPLATE_PHIPA.md`. The US HIPAA Business Associate
> Agreement version lives at `docs/BAA_TEMPLATE_HIPAA.md`.

---

## Why HIA does NOT use "agent" terminology

Under Ontario's PHIPA, a service provider that handles PHI on behalf
of a Health Information Custodian is the custodian's **"agent"** (PHIPA
s. 2). The custodian remains responsible for the agent's actions
(PHIPA s. 17), and the practical legal instrument is an
**HIC Agent Agreement**.

Alberta's HIA does not use "agent" terminology. HIA regulates
**custodians** directly and uses **"affiliate"** to refer to persons
who exercise certain rights on behalf of a custodian (HIA s. 1(1)(a),
s. 56). The practical legal instrument for a service provider that
stores, processes, or transmits health information on a custodian's
behalf is an **Information Manager Agreement (IMA)** under HIA s. 65,
or a written undertaking to the custodian if no formal IMA is
required.

This template is therefore framed as an IMA, not an "agent
agreement." If the Alberta clinic's counsel prefers a different
form, the substantive provisions below translate cleanly to a
non-IMA written undertaking.

---

## 1. Parties

**Health Information Custodian ("Custodian"):** **[Clinic Name]**,
a health information custodian under the *Health Information Act*,
RSA 2000, c H-5 (the "Act").

**Information Manager:** Ashbi Design Inc., operating the Zorva
pre-submit claim-audit service (the "Information Manager" or
"Manager").

**Effective Date:** **[YYYY-MM-DD]**

This Information Manager Agreement is entered into to comply with the
requirements of the Act and its regulations (collectively, the
"Act") with respect to individually identifying health information
("Health Information") provided by the Custodian to the Manager in
connection with the services described in the underlying services
agreement between the parties (the "Underlying Agreement").

---

## 2. Definitions

- **"Act"** means the *Health Information Act*, RSA 2000, c H-5,
  including the *Health Information Regulation*, Alta Reg 70/2001.
- **"Commissioner"** means the Office of the Information and Privacy
  Commissioner of Alberta (OIPC) or its successor.
- **"Custodian"** has the meaning given in section 1(1)(f) of the
  Act and includes the Custodian identified above.
- **"Health Information"** has the meaning given in section 1(1)(i)
  of the Act: individually identifying information about an
  individual's physical or mental health, including
  - the individual's health history,
  - the nature of the individual's health condition(s),
  - the health services provided to the individual,
  - the individual's registration information, and
  - any other information about the individual's health,
  limited to Health Information provided by the Custodian to the
  Manager under this Agreement.
- **"Privacy Breach"** has the meaning given in section 67.1(1) of
  the Act: the theft, loss, or unauthorized use or disclosure of
  Health Information, or any other incident that results in
  unauthorized access to Health Information.
- **"Real Risk of Significant Harm"** has the meaning given in
  section 67.1(2) of the Act: a reasonable belief that the Privacy
  Breach creates a real risk of significant harm to an individual.

---

## 3. Authority and Compliance

3.1 The Manager is authorized to act on behalf of the Custodian
solely with respect to the services described in the Underlying
Agreement and only to the extent permitted by sections 56 to 65 of
the Act.

3.2 The Manager shall comply with the terms of this Agreement and,
in performing the services, shall comply with the Act as if the
Manager were the Custodian, in accordance with section 65(1) of the
Act.

3.3 The Manager shall not use or disclose Health Information except
as necessary to perform the services, as required by law, or as
otherwise authorized in writing by the Custodian.

3.4 The Manager shall not combine Health Information provided by
the Custodian with any other record except as expressly authorized
in writing by the Custodian (HIA s. 30).

---

## 4. Cross-Border Data Handling

4.1 The Manager shall not disclose Health Information outside
Alberta, or to a non-custodian inside Alberta, without the prior
express written consent of the Custodian (HIA s. 64(1)).

4.2 Specifically:

  (a) The Manager's audit service runs on a Hostinger VPS located
      outside Canada. Cross-border disclosure requires the
      Custodian's express consent under HIA s. 64(1). The
      Custodian's countersignature on this Agreement constitutes
      such consent for the duration of the pilot period.

  (b) The Manager's automated reasoning engine (the auditor)
      transmits Health Information to a third-party LLM provider
      (currently ollama/minimax-m3:cloud; details in the
      Underlying Agreement) for processing. This is a disclosure
      outside Alberta. The Manager will maintain a current list of
      LLM providers in Appendix A and notify the Custodian at
      least 30 days before adding a new provider.

  (c) The Manager shall not store Health Information outside Canada
      without the prior express written consent of the Custodian.

4.3 The Manager shall maintain a record of every cross-border
disclosure made under this Agreement, including the date, recipient,
type of Health Information disclosed, and the Custodian's written
authorization for that disclosure.

---

## 5. Safeguards

5.1 The Manager shall implement reasonable administrative, technical,
and physical safeguards to protect Health Information from
unauthorized use, disclosure, copying, modification, or disposal, in
accordance with sections 60 and 65 of the Act and the Health
Information Regulation.

5.2 Specifically, the Manager shall:

  (a) Encrypt Health Information in transit (TLS 1.3 minimum) and at
      rest (AES-256 minimum).
  (b) Restrict Health Information access to workforce members with
      a documented business need for such access.
  (c) Maintain an audit log of all Health Information access events
      for a minimum of **ten (10) years** following the date of
      access, in accordance with section 8 of the Act and the
      Health Information Regulation. Where Health Information
      relates to a minor, the retention period runs from the
      individual's 18th birthday.
  (d) Conduct periodic security reviews (at minimum annually) and
      remediate identified vulnerabilities within a documented
      timeframe.
  (e) Maintain a written information security policy and a written
      incident response plan.
  (f) Conduct workforce training on the safeguards at hire and
      annually thereafter.

5.3 The safeguards shall meet or exceed the controls described in
the Manager's then-current `docs/AUDIT_SECURITY.md` (the "Security
Posture Document"), as updated from time to time. Material changes
to the Security Posture Document that weaken a control will be
notified to the Custodian at least 30 days in advance.

---

## 6. Subcontractors

6.1 The Manager shall not engage any subcontractor to perform
services under this Agreement that involve the collection, use,
disclosure, storage, or disposal of Health Information without the
prior express written consent of the Custodian.

6.2 Where the Manager engages an authorized subcontractor, the
Manager shall impose written obligations on the subcontractor that
are at least equivalent to those imposed on the Manager under this
Agreement.

---

## 7. Privacy Breach Notification

7.1 The Manager shall notify the Custodian in writing as soon as
practicable, and in any event within **seventy-two (72) hours**,
after becoming aware of a Privacy Breach (HIA s. 67.2).

7.2 The Manager's notification shall include, to the extent known at
the time:

  (a) A description of the Privacy Breach, including the date,
      duration, and scope of the incident.
  (b) The type of Health Information involved.
  (c) The number of individuals whose Health Information was
      involved.
  (d) The steps the Manager has taken or proposes to take to
      mitigate the harm and prevent recurrence.
  (e) A contact person at the Manager for follow-up.

7.3 The Manager shall provide updates to the Custodian as
additional information becomes available. The Custodian, not the
Manager, is responsible for notifying the Commissioner under HIA
s. 67.2 and for any notification to affected individuals under HIA
s. 67.3 if there is a Real Risk of Significant Harm. The Manager
shall cooperate with the Custodian in providing the information
needed for those notifications.

---

## 8. Access, Correction, and Complaints

8.1 The Manager shall respond to a Custodian request to access,
correct, or annotate Health Information within **thirty (30) days**
of receipt of the request, in accordance with sections 14, 23, and
27 of the Act.

8.2 Where an individual makes a complaint to the Manager about the
Manager's handling of Health Information, the Manager shall:

  (a) Acknowledge receipt of the complaint within five (5) business
      days.
  (b) Investigate the complaint and respond substantively within
      thirty (30) days.
  (c) Cooperate with any complaint to the Commissioner concerning
      the Manager's handling of the Health Information.

---

## 9. Retention and Destruction

9.1 On termination of this Agreement or the Underlying Agreement,
whichever is sooner, the Manager shall, at the Custodian's option:

  (a) Return all Health Information to the Custodian in a commonly
      used electronic format; or
  (b) Securely destroy all Health Information in the Manager's
      custody or control.

9.2 The Manager shall complete the return or destruction within
**thirty (30) days** of the effective date of termination, and
shall provide the Custodian with a written certification of
destruction within seven (7) days of completion.

9.3 The audit log retention period in section 5.2(c) survives
termination of this Agreement.

---

## 10. Amendment

10.1 This Agreement may be amended only by a written instrument
signed by both parties. Material amendments that weaken a control
require the Custodian's prior written consent.

10.2 The Manager may amend Appendix A (LLM provider list) on thirty
(30) days' prior written notice to the Custodian, as provided in
section 4.2(b).

---

## 11. Term and Termination

11.1 This Agreement is effective on the Effective Date and continues
in effect until the earlier of (a) termination of the Underlying
Agreement, or (b) termination under section 11.2.

11.2 Either party may terminate this Agreement for cause on thirty
(30) days' written notice if the other party materially breaches
this Agreement and fails to cure the breach within that period. The
Manager shall terminate immediately on notice from the Custodian
if the Custodian determines, in its sole discretion, that continued
provision of the services would violate the Act.

---

## 12. General

12.1 This Agreement is governed by the laws of the Province of
Alberta and the laws of Canada applicable therein.

12.2 The Manager's obligations under this Agreement survive any
change in the Manager's corporate structure, including a sale,
merger, or change of control.

12.3 Nothing in this Agreement creates any obligation on the part
of the Manager that is inconsistent with the Act. Where a
provision of this Agreement conflicts with the Act, the Act
prevails.

---

## Appendix A — Authorized LLM Providers

The Manager's automated reasoning engine transmits Health Information
to the following LLM providers for processing. The Manager will
provide 30 days' prior written notice before adding or replacing a
provider.

| Provider | Service URL | Data region | Subprocessor agreement on file |
|---|---|---|---|
| ollama/minimax-m3:cloud | (configured via `LLM_BASE_URL`) | (see provider) | yes — `docs/SEC_REVIEW_deps.md` |

---

## Appendix B — Cross-Border Disclosures Log

The Manager maintains a record of every cross-border disclosure
under section 4.3. On request from the Custodian (which the
Custodian may make no more than quarterly), the Manager shall
provide the current log within ten (10) business days.
