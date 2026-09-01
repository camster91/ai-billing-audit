# Zorva HQ history operations

**Status:** database mutation guards implemented locally; retention duration and
production procedure require accountable approval

## Scope

`PlatformAuditEvent` records company-operator access and mutations.
`LeadActivity` records field-level commercial lead history. Neither table is the
tenant clinical audit chain, and neither may contain PHI.

## Runtime invariant

The SQLite and PostgreSQL migrations install database triggers that allow
inserts and reject every update or delete. Application code has no bypass flag,
session setting, hidden endpoint, or privileged purge function. A compromised
application credential therefore cannot silently rewrite existing HQ history by
using ordinary SQL permissions.

The guards also mean a lead with activity cannot be hard-deleted through a
cascade. Until an approved retention/deletion policy exists, commercial records
must be deactivated or closed rather than erased.

## Retention decision gate

No retention duration is inferred from clinic PHI, billing, tax, or clinical
record rules. Before production operation, the accountable owner must approve a
policy reviewed for Alberta privacy, contractual, tax, dispute, and security
requirements. The decision must specify:

- separate periods for operator-access events and commercial lead activity;
- the start event for each period;
- legal hold and active-dispute behavior;
- export and customer/privacy-request handling;
- backup expiry and restore implications;
- who may approve and execute a purge;
- evidence retained after a purge without retaining the purged content.

## Approved purge procedure

There is deliberately no routine application purge. A future purge requires all
of the following before any destructive database action:

1. A named owner approval and reviewed change record identify exact record IDs,
   reason, retention rule, database, and backup impact.
2. A read-only export and row counts are stored in the approved evidence
   location; no PHI is introduced into HQ evidence.
3. A tested maintenance migration drops only the relevant mutation guards,
   deletes only the approved IDs in one transaction, and recreates the guards
   before commit.
4. Verification proves the approved rows are absent, all other rows remain, and
   update/delete attempts are blocked again.
5. The change record captures executor, approver, timestamps, counts, migration
   revision, backup expiry, and verification result.

Production execution, retention-policy approval, or destructive purge is not
authorized by this document or by merging the guard migration.
