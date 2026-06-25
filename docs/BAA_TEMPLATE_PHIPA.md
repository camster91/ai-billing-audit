# Health Information Custodian (HIC) Agent Agreement — Ontario PHIPA

> **DRAFT — LEGAL REVIEW REQUIRED.**
> This template has **not** been reviewed by a lawyer.
> **Do not use for any real pilot until reviewed by qualified Canadian
> counsel** familiar with Ontario's *Personal Health Information Protection
> Act, 2004* (PHIPA) and the *Personal Information Protection and Electronic
> Documents Act* (PIPEDA), where applicable.
> Replace every `[...]` placeholder before signing.
>
> The HIPAA Business Associate Agreement version of this agreement lives at
> `docs/BAA_TEMPLATE_HIPAA.md`. The Alberta HIA version of this agreement
> lives at `docs/BAA_TEMPLATE_HIC_AGENT.md`.

---

## 1. Parties

**Health Information Custodian ("HIC"):** **[Clinic Name]**, a health
information custodian under PHIPA (the "HIC").

**Agent:** Ashbi Design Inc., operating the Zorva pre-submit claim-audit
service (the "Agent").

**Effective Date:** **[YYYY-MM-DD]**

This Agent Agreement is entered into to comply with the requirements of
PHIPA and its regulations (collectively, the "Act") with respect to
personal health information ("PHI") provided by the HIC to the Agent
in connection with the services described in the underlying services
agreement between the parties (the "Underlying Agreement").

---

## 2. Definitions

- **"Agent"** has the meaning given in section 2 of PHIPA: a person that
  acts on behalf of a HIC with respect to the collection, use,
  disclosure, retention, or disposal of PHI.
- **"Health Information Custodian"** or **"HIC"** has the meaning given
  in section 3 of PHIPA and includes the HIC identified above.
- **"Personal Health Information"** or **"PHI"** has the meaning given in
  section 4 of PHIPA, limited to PHI provided by the HIC to the Agent
  under this Agreement.
- **"Privacy Breach"** has the meaning given in section 12 of PHIPA:
  the theft, loss, or unauthorized use or disclosure of PHI.

---

## 3. Authority and Compliance

3.1 The Agent is authorized to act on behalf of the HIC solely with
respect to the services described in the Underlying Agreement.

3.2 The Agent shall comply with the terms of this Agreement and, in
performing the services, shall comply with the Act as if the Agent
were the HIC, in accordance with section 17 of PHIPA.

3.3 The Agent shall not use or disclose PHI except as necessary to
perform the services or as required by law.

---

## 4. Safeguards

4.1 The Agent shall implement reasonable administrative, technical, and
physical safeguards to protect PHI from unauthorized use, disclosure,
copying, modification, or disposal, in accordance with section 12 of
PHIPA and Ontario Regulation 329/04.

4.2 Specifically, the Agent shall:

  (a) Encrypt PHI in transit (TLS 1.3 minimum) and at rest (AES-256
      minimum).
  (b) Restrict PHI access to workforce members with a business need
      for such access.
  (c) Maintain an audit log of all PHI access events for a minimum of
      ten (10) years (or such longer period required by applicable
      law).
  (d) Conduct periodic security reviews and remediate identified
      vulnerabilities within a reasonable timeframe.
  (e) Maintain written policies for information governance, workforce
      training, and incident response.

4.3 Reference: see `docs/SECURITY_ONEPAGER.md` for the full technical
safeguards in effect on the Effective Date.

---

## 5. Sub-Agents

5.1 The Agent engages **no sub-agents** to perform services involving
PHI on behalf of the HIC. All PHI access shall be performed by the
Agent's direct employees or contractors who have executed the Agent's
standard confidentiality agreement.

5.2 If the Agent later engages a sub-agent, the Agent shall ensure,
in accordance with section 17(3) of PHIPA, that the sub-agent
complies with the same terms and conditions that apply to the Agent
under this Agreement.

---

## 6. Privacy Breach Notification

6.1 The Agent shall notify the HIC of any Privacy Breach without
unreasonable delay and in no case later than five (5) business days
after discovery of the Privacy Breach, in accordance with section 12(2)
of PHIPA.

6.2 Such notification shall include, to the extent reasonably possible:

  (a) The date and time of the Privacy Breach (if known).
  (b) A description of the PHI involved.
  (c) The number of individuals affected (or an estimate).
  (d) The cause of the Privacy Breach, to the extent known.
  (e) The steps taken or proposed to be taken to contain the Privacy
      Breach and prevent further unauthorized access or use.
  (f) The steps the HIC may need to take to comply with the
      notification obligations under section 12(2) of PHIPA, including
      notification to the Information and Privacy Commissioner of
      Ontario and to affected individuals.

6.3 The Agent shall cooperate with the HIC in connection with the
investigation and remediation of any Privacy Breach, and shall
reimburse the HIC for reasonable costs incurred by the HIC in
providing notice to the Commissioner and to affected individuals, to
the extent such Privacy Breach was caused by the negligence or
willful misconduct of the Agent.

---

## 7. Access and Correction

7.1 **Access.** Within thirty (30) days of a written request from the
HIC, the Agent shall make PHI available to the HIC as required by
section 52 of PHIPA.

7.2 **Correction.** Within thirty (30) days of a written request from
the HIC, the Agent shall make any correction to PHI that the HIC
directs or agrees to, in accordance with section 55 of PHIPA.

---

## 8. Retention and Disposal

8.1 The Agent shall retain PHI only for as long as necessary to perform
the services or as required by law, and shall securely dispose of PHI
at the earliest of (a) the HIC's written instruction, (b) the end of
the retention period required by law, or (c) termination of this
Agreement.

8.2 Disposal shall be by methods that prevent the recovery or
reconstruction of PHI, including cryptographic erasure of encrypted
records and physical destruction of any non-electronic records.

---

## 9. Term and Termination

9.1 **Term.** This Agreement shall be effective on the Effective Date
and shall continue in effect until the earlier of (a) the termination
of the Underlying Agreement, or (b) the termination of this Agreement
as provided herein.

9.2 **Termination for Cause.** Upon the HIC's knowledge of a material
breach by the Agent of this Agreement, the HIC may terminate this
Agreement and the Underlying Agreement upon written notice if the
Agent fails to cure the breach within thirty (30) days of receiving
written notice from the HIC.

9.3 **Effect of Termination.** Upon termination, the Agent shall, at
the HIC's written direction, return all PHI to the HIC or securely
dispose of such PHI in accordance with Section 8.

---

## 10. Audit

10.1 The HIC may, upon thirty (30) days' written notice and not more
than once per year (except in the event of a Privacy Breach), audit
the Agent's compliance with this Agreement. The Agent shall provide
reasonable cooperation and access to records, personnel, and systems
necessary to conduct such audit.

---

## 11. Miscellaneous

11.1 **Regulatory Changes.** The parties shall negotiate in good faith
to amend this Agreement from time to time to the extent necessary to
comply with the Act and any other applicable law.

11.2 **Survival.** The rights and obligations of the parties under
Sections 3, 6, 7, 8, 10, and 11 shall survive termination.

11.3 **Governing Law.** This Agreement shall be governed by and
construed in accordance with the laws of the Province of Ontario and
the federal laws of Canada applicable therein.

11.4 **Order of Precedence.** In the event of a conflict between this
Agreement and the Underlying Agreement, the terms of this Agreement
shall control with respect to PHI.

---

## Signatures

**HEALTH INFORMATION CUSTODIAN:**

By:  ______________________________
Name:  ____________________________
Title:  ____________________________
Date:  ____________________________

**AGENT (Ashbi Design Inc.):**

By:  Cameron Ashley
Name:  Cameron Ashley
Title:  Founder / CEO
Date:  ____________________________

---

> Reviewer checklist before signing:
>
> - [ ] All `[...]` placeholders replaced.
> - [ ] Effective Date agreed and entered.
> - [ ] Both parties sign and date the signature block.
> - [ ] A qualified Ontario (Canadian) privacy attorney has reviewed the executed copy.
