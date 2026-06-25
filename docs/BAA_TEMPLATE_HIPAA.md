# Business Associate Agreement (BAA) — HIPAA

> **DRAFT — LEGAL REVIEW REQUIRED.**
> This template has **not** been reviewed by a lawyer.
> **Do not use for any real pilot until reviewed by qualified US healthcare
> counsel** familiar with HIPAA (45 CFR Parts 160 and 164, Subparts C and E)
> and the relevant state privacy regime (e.g. NY SHIELD, CA CMIA, IL BIPA
> as applicable).
> Replace every `[...]` placeholder before signing. Clauses are intentionally
> short and may require tailoring to the covered entity's specific circumstances.
> The Alberta HIC-Agent version of this agreement lives at
> `docs/BAA_TEMPLATE_HIC_AGENT.md`. The Ontario PHIPA HIC-Agent version
> lives at `docs/BAA_TEMPLATE_PHIPA.md`.

---

## 1. Parties

**Covered Entity ("CE"):** **[Clinic Name]**, a HIPAA-covered health care
provider (the "Covered Entity").

**Business Associate ("BA"):** Ashbi Design Inc., operating the Zorva
pre-submit claim-audit service (the "Business Associate").

**Effective Date:** **[YYYY-MM-DD]**

This Business Associate Agreement ("BAA") is entered into between the
Covered Entity and the Business Associate to comply with the requirements
of the Health Insurance Portability and Accountability Act of 1996
("HIPAA"), the Health Information Technology for Economic and Clinical
Health Act of 2009 (the "HITECH Act"), and their implementing
regulations at 45 CFR Parts 160 and 164 (collectively, "HIPAA Rules").

---

## 2. Definitions

Capitalized terms not otherwise defined have the meanings set forth in
the HIPAA Rules. The following definitions apply:

- **"PHI"** means Protected Health Information, as defined at 45 CFR
  §160.103, limited to the PHI that BA receives from or on behalf of CE
  under this BAA.
- **"Breach"** has the meaning given at 45 CFR §164.402.
- **"Secretary"** means the Secretary of the U.S. Department of Health
  and Human Services or his or her designee.
- **"Subcontractor"** has the meaning given at 45 CFR §160.103.

---

## 3. Permitted Uses and Disclosures of PHI

3.1 BA may use or disclose PHI only as necessary to perform the services
set forth in the underlying services agreement between the parties (the
"Underlying Agreement") or as required by law.

3.2 BA may use PHI for the proper management and administration of BA
or to carry out the legal responsibilities of BA, in accordance with
45 CFR §164.504(e)(4).

3.3 BA may disclose PHI for the proper management and administration of
BA or to carry out the legal responsibilities of BA, provided that any
such disclosure: (a) is required by law; or (b) BA obtains reasonable
assurances from the person to whom the PHI is disclosed that it will be
held confidentially and used or further disclosed only as required by
law or for the purpose for which it was disclosed to the person.

3.4 BA may use PHI to provide data aggregation services to CE, as
defined at 45 CFR §164.501.

3.5 BA may de-identify PHI in accordance with 45 CFR §164.514(a)-(c) and
use such de-identified information for any lawful purpose.

---

## 4. Safeguards for PHI

4.1 BA agrees to implement administrative, physical, and technical
safeguards that reasonably and appropriately protect the
confidentiality, integrity, and availability of electronic PHI that it
creates, receives, maintains, or transmits on behalf of CE, as required
by 45 CFR §164.308, §164.310, and §164.312.

4.2 Specifically, BA shall:

  (a) Encrypt PHI in transit (TLS 1.3 minimum) and at rest
      (AES-256 minimum).
  (b) Maintain access controls that restrict PHI access to workforce
      members who have a business need for such access.
  (c) Maintain an audit log of all PHI access events for a minimum of
      six (6) years.
  (d) Conduct periodic security risk analyses (at minimum annually) and
      remediate identified vulnerabilities within a reasonable
      timeframe.
  (e) Maintain written policies and procedures for HIPAA compliance,
      workforce training, sanctions, and incident response.

4.3 Reference BA's security one-pager at `docs/SECURITY_ONEPAGER.md` for
the full technical safeguards in effect on the Effective Date.

---

## 5. Subcontractors

5.1 BA shall use **no subcontractors** to perform services involving
PHI on behalf of CE under this BAA. All PHI access shall be performed
by BA's direct employees or contractors who have executed BA's
standard HIPAA-confidentiality agreement.

5.2 If BA later engages a Subcontractor that creates, receives,
maintains, or transmits PHI on behalf of CE, BA shall require the
Subcontractor to agree, in writing, to substantially the same
restrictions, conditions, and requirements that apply to BA under
this BAA, in accordance with 45 CFR §164.504(e)(1)(ii).

---

## 6. Breach Notification

6.1 BA shall report to CE any Breach of Unsecured PHI, and any
security incident involving PHI, in accordance with 45 CFR §164.410.

6.2 BA shall provide such notification **without unreasonable delay**
and in no case later than **sixty (60) calendar days** after discovery
of the Breach. Such notification shall include, to the extent
reasonably possible:

  (a) The identification of each individual whose Unsecured PHI was,
      or is reasonably believed to have been, accessed, acquired,
      used, or disclosed during the Breach.
  (b) A description of the PHI involved in the Breach.
  (c) The date of the Breach (if known) and the date of discovery of
      the Breach.
  (d) A description of the unauthorized persons known or reasonably
      believed to have used or disclosed the PHI.
  (e) A description of the actions taken by BA to mitigate the Breach
      and protect against further unauthorized use or disclosure.
  (f) Any steps CE should take to mitigate potential harm.

6.3 BA shall reimburse CE for reasonable costs incurred by CE in
providing breach notification to affected individuals, the Secretary,
and (if applicable) the media, to the extent such Breach was caused by
the negligence or willful misconduct of BA.

---

## 7. Access, Amendment, and Accounting

7.1 **Access.** Within fifteen (15) business days of a written request
from CE, BA shall make PHI available to CE as required by 45 CFR §164.524
to permit CE to fulfill an individual's request for access to PHI.

7.2 **Amendment.** Within thirty (30) business days of a written request
from CE, BA shall make any amendment to PHI that CE directs or agrees
to, in accordance with 45 CFR §164.526.

7.3 **Accounting of Disclosures.** Within thirty (30) business days of a
written request from CE, BA shall provide to CE information necessary
for CE to respond to a request by an individual for an accounting of
disclosures of PHI, in accordance with 45 CFR §164.528.

---

## 8. Term and Termination

8.1 **Term.** This BAA shall be effective on the Effective Date and
shall continue in effect until the earlier of (a) the termination of
the Underlying Agreement, or (b) the termination of this BAA as
provided herein.

8.2 **Termination for Cause.** Upon CE's knowledge of a material breach
by BA of this BAA, CE shall either (a) provide BA an opportunity to
cure the breach within thirty (30) days, or (b) terminate this BAA and
the Underlying Agreement immediately if cure is not feasible. CE shall
report the breach to the Secretary as required by 45 CFR §164.504(e)(1)(ii).

8.3 **Effect of Termination.** Upon termination of this BAA for any
reason, BA shall, at the written direction of CE:

  (a) Return to CE all PHI received from CE or created, received,
      maintained, or transmitted by BA on behalf of CE; or
  (b) Destroy all such PHI (and retain no copies).

If such return or destruction is not feasible, BA shall extend the
protections of this BAA to the PHI and limit further uses and
disclosures to those purposes that make the return or destruction
infeasible, in accordance with 45 CFR §164.504(e)(2)(ii)(J).

---

## 9. State Law Addenda

9.1 To the extent CE is subject to state privacy laws that impose
additional requirements on the handling of PHI (including but not
limited to the New York SHIELD Act, California CMIA, Illinois BIPA,
and Texas HB 300), BA agrees to comply with such additional
requirements to the extent they apply to the PHI handled under this
BAA.

9.2 Specific state addenda (e.g. for NY, CA) may be appended as
exhibits to this BAA before execution.

---

## 10. Miscellaneous

10.1 **Regulatory Changes.** The parties agree to negotiate in good
faith to amend this BAA from time to time to the extent necessary to
comply with the requirements of HIPAA, the HITECH Act, and any other
applicable law.

10.2 **Survival.** The respective rights and obligations of the
parties under Sections 3, 6, 7.3, 8.3, 9, and 10 shall survive any
termination or expiration of this BAA.

10.3 **Governing Law.** This BAA shall be governed by and construed in
accordance with the laws of the jurisdiction in which the CE is
located, without regard to its conflict of laws principles.

10.4 **Order of Precedence.** In the event of a conflict between this
BAA and the Underlying Agreement, the terms of this BAA shall control
with respect to PHI.

---

## Signatures

**COVERED ENTITY:**

By:  ______________________________
Name:  ____________________________
Title:  ____________________________
Date:  ____________________________

**BUSINESS ASSOCIATE (Ashbi Design Inc.):**

By:  Cameron Ashley
Name:  Cameron Ashley
Title:  Founder / CEO
Date:  ____________________________

---

> Reviewer checklist before signing:
>
> - [ ] All `[...]` placeholders replaced.
> - [ ] State law addenda (if any) appended as exhibits.
> - [ ] Effective Date agreed and entered.
> - [ ] Both parties sign and date the signature block.
> - [ ] A qualified HIPAA attorney has reviewed the executed copy.
