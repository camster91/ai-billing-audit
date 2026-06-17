-- audit_trail.sql
-- Phase 4 — tamper-evident hash-chained audit log.
-- Author: Phase-4 dashboard worker (kanban t_165297e9)
-- Compliance: PHIPA (Ontario) / HIA (Alberta) evidence-of-record,
--             Zorva Unified Self-Hosted Master Spec §9.D
--
-- Apply with:
--   psql -v ON_ERROR_STOP=1 -d ai_billing_audit -f audit_trail.sql
--
-- Idempotent: re-running is a no-op.  The trigger and trigger function
-- are created with IF NOT EXISTS; the column is added with ADD COLUMN
-- IF NOT EXISTS; the backfill UPDATE is guarded by a NOT NULL check
-- so a previously-backfilled table re-runs cleanly.
--
-- The chain: each row's ``cryptographic_signature`` is
--   SHA-256(previous_signature || event_id || timestamp ||
--           user_identifier || action || patient_hash ||
--           data_elements || model_run_id)
-- computed in src/audit_log.py:compute_signature().  The genesis row
-- (oldest by ``timestamp``) has ``previous_signature`` = 64 ASCII
-- zeros.  The verifier in src/audit_log.py:verify_chain() walks the
-- table ordered by ``timestamp`` and reports the first break.

BEGIN;

-- -------------------------------------------------------------------
-- 1. audit_trail table
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_trail (
    -- Internal surrogate key.  Not part of the chain hash, but useful
    -- as a stable handle for the verifier's "row N is broken" report.
    id              BIGSERIAL PRIMARY KEY,

    -- Chain payload
    event_id        TEXT        NOT NULL,
    "timestamp"     TIMESTAMPTZ NOT NULL,
    user_identifier TEXT        NOT NULL,
    action          TEXT        NOT NULL,
    patient_hash    TEXT        NOT NULL,
    data_elements   JSONB       NOT NULL,
    model_run_id    TEXT        NOT NULL,

    -- Chain link fields.  ``previous_signature`` is the immediately
    -- prior row's ``cryptographic_signature`` (64 zeros for the
    -- genesis row).  ``cryptographic_signature`` is the row's own
    -- SHA-256 digest over (previous_signature || <chain fields>).
    previous_signature     TEXT NOT NULL DEFAULT REPEAT('0', 64),
    cryptographic_signature TEXT NOT NULL,

    -- Bookkeeping for the backfill / verifier runbook
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT audit_trail_signature_hex     CHECK (cryptographic_signature ~ '^[0-9a-f]{64}$'),
    CONSTRAINT audit_trail_previous_hex      CHECK (previous_signature     ~ '^[0-9a-f]{64}$'),
    CONSTRAINT audit_trail_event_id_unique   UNIQUE (event_id)
);

-- -------------------------------------------------------------------
-- 2. Idempotent column add for existing audit_trail tables that
--    pre-date this migration.  ADD COLUMN IF NOT EXISTS is
--    PostgreSQL 9.6+; safe to no-op on a fresh install.
-- -------------------------------------------------------------------
ALTER TABLE audit_trail
    ADD COLUMN IF NOT EXISTS previous_signature      TEXT NOT NULL DEFAULT REPEAT('0', 64);
ALTER TABLE audit_trail
    ADD COLUMN IF NOT EXISTS cryptographic_signature  TEXT;

-- Now enforce NOT NULL on cryptographic_signature.  The backfill in
-- step 4 must run before this ALTER fires on a populated table.
-- On a fresh install the column is already NOT NULL from the CREATE.

-- -------------------------------------------------------------------
-- 3. Chain-order index.  The verifier walks (timestamp ASC, event_id
--    ASC) and the backfill does too.  A composite btree index on
--    those two columns gives us the canonical order in O(n) without
--    a sort.
-- -------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS audit_trail_chain_order_idx
    ON audit_trail ("timestamp" ASC, event_id ASC);

-- -------------------------------------------------------------------
-- 4. Backfill: for any row where ``cryptographic_signature`` IS NULL
--    (i.e. inserted before this migration), compute the chained
--    signature using src/audit_log.py:compute_signature() and
--    UPDATE in place.  Runs in a single statement using a window
--    function so the genesis row picks up 64 zeros and every
--    subsequent row picks up the previous row's stored value.
--
--    On a fresh install the UPDATE matches zero rows and is a no-op.
--
--    To run against a populated database, first export the rows to
--    a temp table, compute signatures in Python, and COPY back —
--    the SQL-only approach below is the fallback for tiny tables
--    (<10k rows).  For larger tables, use:
--
--        psql -At -c "SELECT id, previous_signature, event_id,
--                            to_char(timestamp AT TIME ZONE 'UTC',
--                                    'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),
--                            user_identifier, action, patient_hash,
--                            data_elements::text, model_run_id
--                     FROM audit_trail
--                     WHERE cryptographic_signature IS NULL
--                     ORDER BY timestamp ASC, event_id ASC" \
--             | python -m ai_billing_audit.audit_trail_backfill \
--             | psql -v ON_ERROR_STOP=1
--
--    The Python helper is intentionally out of scope for this card
--    (see Zorva §9.D "out of scope: external signing/HSM integration").
-- -------------------------------------------------------------------
DO $$
DECLARE
    prev_sig TEXT := REPEAT('0', 64);
    rec      RECORD;
    digest   TEXT;
BEGIN
    FOR rec IN
        SELECT id,
               event_id,
               to_char("timestamp" AT TIME ZONE 'UTC',
                       'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS ts_iso,
               user_identifier,
               action,
               patient_hash,
               data_elements::text AS data_elements_text,
               model_run_id
        FROM audit_trail
        WHERE cryptographic_signature IS NULL
        ORDER BY "timestamp" ASC, event_id ASC
    LOOP
        digest := encode(
            digest(
                prev_sig
                || rec.event_id
                || rec.ts_iso
                || rec.user_identifier
                || rec.action
                || rec.patient_hash
                || rec.data_elements_text
                || rec.model_run_id,
                'sha256'
            ),
            'hex'
        );

        UPDATE audit_trail
        SET previous_signature     = prev_sig,
            cryptographic_signature = digest
        WHERE id = rec.id;

        prev_sig := digest;
    END LOOP;
END $$;

-- Now that the backfill has run, enforce NOT NULL on
-- ``cryptographic_signature`` for any table that pre-dated the
-- column-add above.  Safe to re-run: the constraint is added with
-- IF NOT EXISTS semantics via DO block.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'audit_trail'
          AND column_name = 'cryptographic_signature'
          AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE audit_trail
            ALTER COLUMN cryptographic_signature SET NOT NULL;
    END IF;
END $$;

-- -------------------------------------------------------------------
-- 5. Append-only trigger.  Once the chain is in place, an UPDATE
--    or DELETE on a row whose ``cryptographic_signature`` is set
--    raises an exception.  INSERTs are always allowed (the chain
--    forward-walks naturally as new rows append).
-- -------------------------------------------------------------------
CREATE OR REPLACE FUNCTION audit_trail_block_mutation()
RETURNS TRIGGER AS $$
BEGIN
    -- Allow the backfill to UPDATE rows whose signature is still
    -- NULL (those are the rows the DO block above just finished
    -- processing, so this branch is a defensive double-check).
    IF OLD.cryptographic_signature IS NULL
       AND NEW.cryptographic_signature IS NOT NULL THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION
        'audit_trail is append-only: % on row id=% with non-null '
        'cryptographic_signature is not permitted (PHIPA / HIA '
        'evidence-of-record)', TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_trail_no_mutation ON audit_trail;
CREATE TRIGGER audit_trail_no_mutation
    BEFORE UPDATE OR DELETE ON audit_trail
    FOR EACH ROW
    EXECUTE FUNCTION audit_trail_block_mutation();

COMMIT;
