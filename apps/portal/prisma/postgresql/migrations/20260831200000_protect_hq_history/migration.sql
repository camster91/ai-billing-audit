-- HQ operator history is evidence-of-operation. Normal application and database
-- writes may append rows, but may not rewrite or delete existing history.
-- An approved retention purge must be performed as a separately reviewed
-- maintenance migration that temporarily removes and then restores these guards.

CREATE OR REPLACE FUNCTION "deny_hq_history_mutation"()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION '% is append-only; % is not permitted', TG_TABLE_NAME, TG_OP
    USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER "PlatformAuditEvent_immutable"
BEFORE UPDATE OR DELETE ON "PlatformAuditEvent"
FOR EACH ROW EXECUTE FUNCTION "deny_hq_history_mutation"();

CREATE TRIGGER "LeadActivity_immutable"
BEFORE UPDATE OR DELETE ON "LeadActivity"
FOR EACH ROW EXECUTE FUNCTION "deny_hq_history_mutation"();

COMMENT ON FUNCTION "deny_hq_history_mutation"() IS
'Prevents UPDATE and DELETE of Zorva HQ history. Approved purges require a reviewed maintenance migration.';
