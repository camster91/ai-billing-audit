# Privacy Incident Response Runbook

> **Audience:** the on-call engineer (technical response) and the
> Privacy Officer / legal lead (regulatory response). **Read §1 first.**
> The decision tree in §1.2 takes 60 seconds; everything else is
> execution detail.
>
> **Scope:** every incident class that touches personal health
> information (PHI), personally identifiable information (PII), the
> VPS, the audit_trail, or the customer-facing portal. This runbook
> applies whether the data leaked, the model emitted it, an attacker
> exfiltrated it, or a misconfigured backup exposed it.
>
> **Related docs:**
> - `SECURITY.md` — how to report a vulnerability to us (inbound).
> - `docs/RUNBOOK.md` — `audit_trail` verification (the evidence-of-record).
> - `docs/BAA_TEMPLATE_PHIPA.md` / `docs/BAA_TEMPLATE_HIPAA.md` /
>   `docs/BAA_TEMPLATE_HIC_AGENT.md` — the contractual notification
>   clauses this runbook operationalises.

---

## 1. Triage (first 15 minutes)

### 1.1 Confirm it's an incident, not a false alarm

| Symptom                                                                                          | Likely class                  | Go to |
|--------------------------------------------------------------------------------------------------|-------------------------------|-------|
| A patient name, DOB, PHN, or MRN appeared in a model output, log, error message, or screenshot.  | **PII / PHI leak**            | §3    |
| Audit_trail `cryptographic_signature` chain returns "BREAK at index I".                          | **Tamper / integrity**        | §4    |
| VPS is responding to SSH from an unknown IP, or `auth.log` shows successful logins we didn't do.| **VPS / account compromise**  | §5    |
| Customer reports "your model flagged a clean claim as missing modifier X" — clinically dangerous. | **Output / safety**           | §6    |
| Ollama, Caddy, or Postgres is returning 5xx for ≥15 minutes; customer data is NOT at risk.        | **Availability** (not privacy) | `docs/RUNBOOK.md` §3 |

When in doubt, treat it as a privacy incident and escalate. The
re-classification cost is low; the under-classification cost is
regulatory.

### 1.2 Decision tree

```
       Is PHI/PII involved, OR is the audit_trail broken,
       OR is the VPS compromised?
                  │
        ┌─────────┴──────────┐
       YES                   NO
        │                    │
        ▼                    ▼
   Severity = ?         Not a privacy incident;
   (§2)                  file under docs/RUNBOOK.md
        │
        ▼
   Contain (§3.1 / §4.1 / §5.1)
   — stop the bleed FIRST —
        │
        ▼
   Notify within SLA (§7)
        │
        ▼
   Preserve evidence (§8)
        │
        ▼
   Post-incident review (§9) within 5 business days
```

### 1.3 First 15 minutes checklist

- [ ] **Stop the bleed.** Apply the §3/§4/§5 containment step for
      the class. Do not investigate before containment — every minute
      of an active leak is a minute of regulatory exposure.
- [ ] **Page the Privacy Officer** (see §7 contact tree) even if you
      think it's "probably nothing." The PO has the regulatory
      authority you do not.
- [ ] **Open a private incident doc.** Use the template in §10. Do
      **not** put PHI in the doc — use the `patient_hash` from
      `audit_trail`, never the plaintext.
- [ ] **Capture the clock.** Note UTC timestamp of detection and UTC
      timestamp of suspected breach start (often "unknown"). The
      72-hour clock starts at the suspected breach start, not at
      detection.

---

## 2. Severity levels

Five levels. The level drives the §7 notification SLA.

| Sev | Name       | Definition                                                                                          | Examples                                                                                       | Notify within |
|-----|------------|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|---------------|
| **S1** | Catastrophic | PHI of ≥1,000 patients confirmed exposed AND/OR VPS root compromise.                                | Database dump leaked to public; container escape giving root on the VPS.                       | **1 hour**   |
| **S2** | High        | PHI of 1–999 patients confirmed exposed AND/OR `audit_trail` chain broken with evidence of tampering. | Single-tenant customer PHI in a public S3 bucket; chain break with retro-edit on findings.    | **4 hours**  |
| **S3** | Medium      | PII (non-PHI) exposed AND/OR model emitted a patient name into a customer-visible summary.          | A clinical note contained an MRN and the LLM echoed it back into the findings summary.        | **24 hours** |
| **S4** | Low         | Internal-only exposure; no customer data.                                                            | An engineer accidentally committed a `.env` with the LLM API key (not patient data).          | **5 business days** |
| **S5** | Near-miss   | Would-have-been-an-incident, caught before any exposure.                                            | A runbook gap that *could* have leaked; phishing email reported and deleted.                   | Next monthly review |

> **PHI vs PII matters.** Under PHIPA / HIPAA, "PHI" is the
> trigger. An MRN alone is PHI. A name + DOB alone is PHI. A name
> alone is PII but not PHI. The level above uses PHI as the gate.

---

## 3. Class A — PII / PHI leak

### 3.1 Contain (≤30 minutes)

1. **Stop the source.** If the leak is from the auditor model
   output (e.g., the summary echoes the clinical note verbatim):
   - On the VPS: `docker compose -f /opt/projects/ai-billing-audit/docker-compose.yml stop api`
   - Caddy stays up so the `/healthz` 503 propagates to the
     monitor (we want to fail loudly).
2. **Freeze the offending prompt.** Copy
   `prompts/v12/auditor_prompt.txt` to
   `prompts/v12/auditor_prompt.txt.INCIDENT-<id>` and checksum it:

   ```bash
   sha256sum prompts/v12/auditor_prompt.txt.INCIDENT-<id>
   ```

   This is the prompt snapshot for the post-incident review.
3. **Snapshot the audit_trail.** Per `docs/RUNBOOK.md` §1.2, run
   the chain verifier. If intact, save the row count and the
   verifier-script SHA-256 to the incident doc. If broken, jump to
   §4 immediately (Class A and Class B often co-occur).
4. **Snapshot the database.** Do **not** truncate or repair; the
   evidence is in the broken state.

   ```bash
   pg_dump --schema-only --no-owner ai_billing_audit > runs/incidents/<id>/schema.sql
   pg_dump            --no-owner ai_billing_audit > runs/incidents/<id>/dump.sql.gz
   sha256sum runs/incidents/<id>/dump.sql.gz
   ```

5. **If the leak was outbound** (logs shipped to a SaaS, error
   tracker, screenshot tool): revoke the integration's token and
   request the vendor's data-deletion SLA in writing. Track the
   ticket ID in the incident doc.

### 3.2 Scope (≤4 hours)

1. **What data went out?** Pull every audit_trail row with
   `action = 'replay_audit'` or `action = 'submit'` in the window
   between suspected breach start and containment. Use the
   `data_elements` JSONB column — it carries the file SHA-256s.
2. **Who saw it?** Cross-reference the `user_identifier` column.
   Distinguish "the model" from "an external SaaS account" — both
   are PHI exposure, but the notification path differs (§7.2 vs
   §7.3).
3. **Notification scope.** A confirmed leak of `n` patient hashes
   → notify `n` patients (PHIPA s. 12(2)) plus the regulators in
   §7. The BAA template §11 lists the per-customer contractual
   ceiling, which may be stricter than the regulatory floor.

### 3.3 Eradicate & recover

- **Eradicate** = fix the prompt bug (often a missing "do not echo
  the clinical note verbatim" rule). Add a regression test to
  `tests/test_auditor_redaction.py`.
- **Recover** = re-deploy with the fixed prompt, replay every
  submission since the breach start (see
  `docs/operations/SUBMISSION-REPLAY.md` §3), and confirm the
  re-run output does not echo.

---

## 4. Class B — `audit_trail` tamper

This is the highest-trust signal we have. Treat a chain break as a
**S2 at minimum** and as a **S1** if any tampered row references a
real customer submission.

### 4.1 Contain

1. **Stop accepting new writes** to `audit_trail` until you've
   snapshotted:

   ```sql
   -- Connect as the application role, then:
   ALTER TABLE audit_trail RENAME TO audit_trail_INCIDENT_<id>;
   CREATE VIEW audit_trail AS SELECT * FROM audit_trail_INCIDENT_<id>;
   ```

   The view is read-only. The application continues to insert (it
   won't, because containment stopped the API per §3.1) but you
   retain the rows verbatim.

2. **Snapshot the database** as in §3.1 step 4.

### 4.2 Investigate

Run the chain verifier (`docs/RUNBOOK.md` §1.2). Capture:
- the break index `I`;
- the row's `event_id`, `timestamp`, `user_identifier`, `action`;
- the stored vs recomputed `cryptographic_signature`.

Then answer, in order:

1. **Is the break at row 0?** If `previous_signature = "0"*64` does
   not match the genesis, the entire chain is suspect. S1.
2. **Is the break inside the deploy window?** Compare the row's
   `timestamp` against the last `git log --format=%cI deploy-to-vps.sh`
   on the VPS. If inside, the migration script is the prime
   suspect, not an attacker.
3. **Is `user_identifier` a service account?** Then it's almost
   certainly a migration bug, not a breach. S4 unless §1.2's "is
   the row referencing a real customer submission?" is yes.

### 4.3 Recover

If the break is **recoverable** (migration bug, schema change):
1. Document the migration that introduced the bug.
2. Compute what the row's signature *should have been* under the
   new hash function. Add a *forward-only* correction: append a new
   row with `action = 'chain_correction'` and a `data_elements`
   payload pointing at the original `event_id`. **Never edit the
   original row** — that's the difference between "data correction"
   and "evidence tampering."
3. Re-verify the chain. The break remains (the original row is
   unchanged), but the appended correction row is admissible as
   evidence of the correction.

If the break is **unrecoverable** (truly unknown cause, evidence
of malicious edit): S1. Page the Privacy Officer and legal counsel
immediately.

---

## 5. Class C — VPS / account compromise

### 5.1 Contain

1. **Lock SSH.** Edit `/etc/ssh/sshd_config` to set
   `PasswordAuthentication no` and `PermitRootLogin prohibit-password`,
   then `systemctl restart sshd`. This does not kick the attacker
   off an active session.
2. **Kill active sessions.** `pkill -u <user>` for every user the
   attacker could have accessed. **Before this**, capture
   `ps -ef`, `w`, `last -F`, and `ss -tunap` to the incident dir.
3. **Rotate every credential** the VPS had: SSH keys
   (in `~/.ssh/authorized_keys`), `.env` file (LLM_API_KEY,
   AUDIT_BEARER_TOKEN, DATABASE_URL password), Caddy admin
   password, Postgres password.
4. **Snapshot the disk** before any reboot:

   ```bash
   dd if=/dev/vda of=/tmp/disk.img bs=4M status=progress
   sha256sum /tmp/disk.img
   gzip /tmp/disk.img
   ```

   This is *forensic*, not operational. Copy it to a write-once
   store immediately.

### 5.2 Scope

The question is: what did the attacker *read*? Check:

- `audit_trail` for any rows with `action = 'sql_query'` or
  unusual `user_identifier` (the application role should be the
  only writer).
- `auth.log` for the IP and timestamp range.
- `docker logs zorva-api` for any outbound connections to IPs
  other than the LLM provider and the database.

If `audit_trail` was read but not written, the breach is
**metadata exposure** (who-submitted-what, when) — S3. If rows
were written, treat as §4 (tamper) on top.

### 5.3 Recover

Rebuild the VPS from the `deploy-to-vps.sh` image (it is
**idempotent** — see the script header). Restore only the database
from the snapshot taken in §4.1 / §3.1 — never the .env file, never
the SSH keys.

---

## 6. Class D — Output / safety

The model emitted a finding that, if acted on, would harm a patient
(e.g., told the clinic not to bill a claim they should have, or
vice versa). This is a **safety** incident, not a **privacy** one —
the regulatory path is different (typically no OIPC notification
unless the output also leaked PHI).

### 6.1 Contain

1. Revert the prompt per
   `docs/research/PROMPT-ITERATION-PLAYBOOK.md` §8.
2. Open a `docs/BUGS_<date>.md` entry with:
   - the encounter_id;
   - the finding text (paraphrased, no PHI);
   - the rule_id;
   - the prompt SHA-256 that produced it.

### 6.2 Scope

For a 100-claim pilot batch, a single bad finding is normal noise
(F1 = 0.690 means 31% of findings are wrong on the val set). For
production, **any** customer-reported safety finding is S3 minimum.

---

## 7. Notification

### 7.1 Regulatory SLAs (clock starts at "suspected breach start")

| Jurisdiction | Statute       | Notification to regulator | Notification to individuals |
|--------------|---------------|---------------------------|------------------------------|
| **Alberta**  | HIA           | **72 hours** to the OIPC  | "Without unreasonable delay" |
| **Ontario**  | PHIPA         | **Immediately** to the IPC; report in writing "as soon as practicable" | "Without unreasonable delay" |
| **Federal**  | PIPEDA        | **As soon as feasible** to the OPC | "As soon as feasible" |
| **US (HIPAA)** | 45 CFR §164.408 | **60 days** to HHS (≤500) or **60 days** to media + HHS (>500) | **60 days** to individuals |

> The 72-hour clock is a *regulatory ceiling*, not a target. Zorva's
> internal SLA is to notify the Privacy Officer within **1 hour of
> detection** for S1/S2; the PO then has the remaining regulatory
> window to file.

### 7.2 OIPC (Alberta) — notification template

To: `privacy.officer@oipc.ab.ca`
Subject: `HIA s. 32(2) breach report — Zorva / [Tenant Name] / [Date]`

```
To the Office of the Information and Privacy Commissioner of Alberta,

Pursuant to section 32(2) of the Health Information Act (Alberta),
[Ashbi Design Inc. operating the Zorva pre-submit claim-audit service]
reports a breach of safeguards involving the personal health
information of approximately [N] individuals held on behalf of
[Custodian Name].

1. Description of the breach
   [Factual, dated, no PHI. E.g., "On 2026-06-25 at 14:32 UTC, a
   configuration error caused the model output of one (1) clinical
   audit summary to be written to a publicly readable log index."]

2. Date(s) of the breach
   Suspected start: [YYYY-MM-DDTHH:MMZ]
   Containment:      [YYYY-MM-DDTHH:MMZ]

3. Description of the PHI involved
   [E.g., "Patient names, dates of birth, and Alberta Personal
   Health Numbers. No diagnostic or clinical-note content was
   exposed."]

4. Number of individuals affected
   [N]

5. Steps taken to contain and recover
   [Bullets, no internal jargon. E.g., "Service stopped within 30
   minutes; configuration corrected; affected logs purged from the
   third-party indexer; verification sweep completed."]

6. Steps taken or planned to reduce the risk of future breaches
   [Bullets.]

7. Contact
   [Privacy Officer name, email, phone]

We will provide an updated report within 30 days if the investigation
yields materially different information.

[Signed]
[Privacy Officer, Ashbi Design Inc.]
```

### 7.3 IPC (Ontario) — notification template

To: `info@ipc.on.ca`
Subject: `PHIPA breach report — Zorva / [Tenant Name] / [Date]`

Use the IPC's online form at <https://www.ipc.on.ca/health-individuals/file-health-privacy-complaint/>,
or email the same 7-point structure as §7.2. PHIPA does not specify a
hard deadline for the regulator; the practical expectation is
"immediately," which Zorva interprets as **≤24 hours**.

### 7.4 Customer / HIC notification

Per the BAA / HIC-Agent agreement §11 (see `docs/BAA_TEMPLATE_*.md`),
the customer must be notified **before** or **concurrently** with
the regulator. The customer then has their own obligation to notify
their patients.

```
To: [Customer Privacy Officer]
Subject: [CONFIDENTIAL] Zorva incident notification — [Incident ID]

[Customer Name] is receiving this notice pursuant to Section [11]
of our [BAA / HIC-Agent Agreement] dated [Effective Date].

We identified a [severity] incident affecting approximately [N]
encounters submitted by your organization between [Start] and
[Containment].

What happened:    [...]
What was exposed: [PHI categories; e.g., names, DOBs, PHNs]
What we did:      [Containment + eradication steps]
What you need to do: [Notify affected patients; review your access logs;
                    coordinate with your privacy officer]

We are available for a 30-minute call at your convenience. The
post-incident review will be shared within 5 business days.

[Signed]
[Zorva Privacy Officer]
```

### 7.5 OPC (federal, PIPEDA)

PIPEDA s. 10.1 only requires notification when there is a **real
risk of significant harm**. The default for Zorva incidents is to
report conservatively (i.e., report if in doubt). Template: OPC's
online breach report form at <https://www.priv.gc.ca/en/report-a-concern/>.

### 7.6 HHS / OCR (US, HIPAA)

The 60-day clock starts at breach discovery. For a breach affecting
≤500 individuals, file the OCR breach portal entry within 60 days.
For >500, also notify prominent media serving the affected
individuals. Zorva's HIPAA customers are notified per the BAA
template §11 first; OCR notification is then a *joint* action.

---

## 8. Evidence preservation

Throughout the incident, the chain of custody must be intact. The
Privacy Officer signs off on every handoff.

```bash
# Per-step snapshot pattern (run for every containment / scope step):
INCIDENT_ID="2026-06-25-phi-leak-001"
SNAPSHOT_DIR="runs/incidents/$INCIDENT_ID"
mkdir -p "$SNAPSHOT_DIR"

# Capture the state, hash it, and timestamp it.
tar czf - /opt/projects/ai-billing-audit | sha256sum > "$SNAPSHOT_DIR/tree.sha256"
date -u +%Y-%m-%dT%H:%M:%SZ > "$SNAPSHOT_DIR/tree.timestamp"
```

Snapshots go in `runs/incidents/<id>/`. The directory is **append-only**
— never delete a snapshot, only add new ones. The Privacy Officer
reviews the directory at the post-incident review (§9).

---

## 9. Post-incident review

Within **5 business days** of containment, the Privacy Officer
facilitates a review with the on-call engineer, an engineering lead,
and (for S1/S2) legal counsel. The deliverable is a single markdown
file committed to `docs/POST_INCIDENT_REVIEWS/<id>.md`.

Template:

```markdown
# Post-Incident Review — [Incident ID]

## Summary
- **Severity:**         [S1 / S2 / S3 / S4 / S5]
- **Detection time:**   [UTC]
- **Containment time:** [UTC]
- **Detection-to-containment:** [minutes]
- **Suspected breach start:** [UTC or "unknown"]

## Timeline (UTC)
- HH:MM  …
- HH:MM  …

## Root cause
[One paragraph. Cite the code or config change.]

## What went well
- …

## What went poorly
- …

## Where we got lucky
- …

## Action items (each: owner, due date, severity)
- [ ] [owner] [due] — [action]
- [ ] …

## Lessons for the runbook
- [Concrete change to this file, with the section number to edit.]
```

Action items must each have an owner and a due date. Items without
both are not action items; they are observations.

---

## 10. Incident doc template (private, during the incident)

```markdown
# Incident — [ID] — [Severity]

## Snapshot
- Detected at:    [UTC]
- By:             [engineer name / monitor alert / customer report]
- Severity (TBD): [S1 / S2 / S3 / S4 / S5]

## Containment (in progress)
- [ ] Step 1 (cite runbook section)
- [ ] Step 2
- [ ] Step 3

## Scope (TBD)
- Patients affected: [N or "unknown"]
- Data classes:      [PHI / PII / metadata only]
- Outbound channels: [none / logs SaaS / public S3 / email]

## Notifications (TBD)
- [ ] Privacy Officer (≤1h for S1/S2)
- [ ] OIPC / IPC / OPC / OCR (per §7.1)
- [ ] Customer (per BAA §11)
- [ ] Patients (per regulator instruction)

## Evidence
- [paths to snapshots in runs/incidents/<id>/]

## Open questions
- …

## Decisions log
- [UTC] [decision] [decided by]
```

This doc is **internal-only**. Do not paste it into customer-facing
channels. Customer-facing summaries are written from the
post-incident review (§9), never from this doc.

---

## 11. Drills

Quarterly, the Privacy Officer runs a **tabletop drill**: pick a
random §1.1 scenario, time the team from detection to containment
on paper, score against the §7 SLA. Record outcomes in
`docs/RUNBOOK_DRILLS/<date>.md`.

Drill requirement for S1/S2 scenarios: detection-to-containment
≤15 minutes on paper. If the team can't, the runbook needs
updating before the next quarter.

---

## 12. Further reading

- `SECURITY.md` — inbound vulnerability reports (this runbook is
  *outbound*, from our side).
- `docs/RUNBOOK.md` §1 — the `audit_trail` chain verifier.
- `docs/BAA_TEMPLATE_PHIPA.md` / `docs/BAA_TEMPLATE_HIPAA.md` /
  `docs/BAA_TEMPLATE_HIC_AGENT.md` §11 — contractual notification
  obligations this runbook operationalises.
- `docs/research/PROMPT-ITERATION-PLAYBOOK.md` §8 — prompt rollback
  (the recovery step for §3 / §6).
- `docs/operations/SUBMISSION-REPLAY.md` §3 — re-running the affected
  batch after a prompt fix.
- `docs/operations/DAILY-CHECKLIST.md` — the daily checklist whose
  findings feed the §1.1 triage.