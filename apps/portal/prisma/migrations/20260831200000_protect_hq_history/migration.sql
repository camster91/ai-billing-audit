-- HQ operator history is evidence-of-operation. Normal application and database
-- writes may append rows, but may not rewrite or delete existing history.
-- An approved retention purge must be performed as a separately reviewed
-- maintenance migration that temporarily removes and then restores these guards.

CREATE TRIGGER "PlatformAuditEvent_immutable_update"
BEFORE UPDATE ON "PlatformAuditEvent"
BEGIN
  SELECT RAISE(ABORT, 'PlatformAuditEvent is append-only');
END;

CREATE TRIGGER "PlatformAuditEvent_immutable_delete"
BEFORE DELETE ON "PlatformAuditEvent"
BEGIN
  SELECT RAISE(ABORT, 'PlatformAuditEvent is append-only');
END;

CREATE TRIGGER "LeadActivity_immutable_update"
BEFORE UPDATE ON "LeadActivity"
BEGIN
  SELECT RAISE(ABORT, 'LeadActivity is append-only');
END;

CREATE TRIGGER "LeadActivity_immutable_delete"
BEFORE DELETE ON "LeadActivity"
BEGIN
  SELECT RAISE(ABORT, 'LeadActivity is append-only');
END;
