-- Retention, legal hold and deletion (#618, spec §16.1). Applied by
-- ../../apply.sh after 003; every statement is idempotent. The two worker
-- passwords arrive as psql variables and may be empty: a role then keeps the
-- password it has, or none, so nobody logs in as it until its worker is
-- deployed, and a later run without them never locks a deployed worker out.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssf_recording_retention') THEN
        CREATE ROLE ssf_recording_retention;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssf_recording_replica') THEN
        CREATE ROLE ssf_recording_replica;
    END IF;
END
$$;

ALTER ROLE ssf_recording_retention WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER ROLE ssf_recording_replica WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
SELECT :'retention_password' <> '' AS retention_password_given,
       :'replica_password' <> '' AS replica_password_given \gset
\if :retention_password_given
ALTER ROLE ssf_recording_retention WITH PASSWORD :'retention_password';
\endif
\if :replica_password_given
ALTER ROLE ssf_recording_replica WITH PASSWORD :'replica_password';
\endif
GRANT CONNECT ON DATABASE :"database" TO ssf_recording_retention, ssf_recording_replica;
GRANT USAGE ON SCHEMA public TO ssf_recording_retention, ssf_recording_replica;

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS shredded_at TIMESTAMPTZ;

-- Every extension, hold change and erasure, with its reason (concept §11,
-- "auditability of retention decisions"). No foreign key: the decisions stay
-- once the conversation's rows are gone, beside its audit events.
CREATE TABLE IF NOT EXISTS retention_decisions (
    tenant_id       TEXT        NOT NULL,
    decision_id     UUID        NOT NULL,
    conversation_id UUID        NOT NULL,
    at              TIMESTAMPTZ NOT NULL,
    actor_sub       TEXT        NOT NULL,
    kind            TEXT        NOT NULL
        CHECK (kind IN ('extend', 'hold_on', 'hold_off', 'erase')),
    retain_until    TIMESTAMPTZ CHECK ((kind = 'extend') = (retain_until IS NOT NULL)),
    reason          TEXT        NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 500),
    PRIMARY KEY (tenant_id, decision_id)
);

-- What each site's worker has confirmed about one stored version.
CREATE TABLE IF NOT EXISTS version_locks (
    tenant_id       TEXT        NOT NULL,
    conversation_id UUID        NOT NULL,
    entry_id        UUID        NOT NULL,
    object_type     TEXT        NOT NULL,
    site            TEXT        NOT NULL CHECK (site IN ('primary', 'replica')),
    version_id      TEXT        NOT NULL,
    checked_at      TIMESTAMPTZ,
    locked_until    TIMESTAMPTZ,
    held            BOOLEAN     NOT NULL DEFAULT FALSE,
    -- When this worker last saw or set the hold: only a later hold_off lifts it.
    held_since      TIMESTAMPTZ,
    deleted_at      TIMESTAMPTZ,
    attempts        INTEGER     NOT NULL DEFAULT 0,
    failing_since   TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, entry_id, object_type, site),
    FOREIGN KEY (tenant_id, entry_id, object_type) REFERENCES stored_objects
);
CREATE INDEX IF NOT EXISTS version_locks_due
    ON version_locks (tenant_id, site, next_attempt_at) WHERE deleted_at IS NULL;

-- A site's worker found nothing left under the conversation's prefix.
CREATE TABLE IF NOT EXISTS site_clearances (
    tenant_id       TEXT        NOT NULL,
    conversation_id UUID        NOT NULL,
    site            TEXT        NOT NULL CHECK (site IN ('primary', 'replica')),
    cleared_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, conversation_id, site),
    FOREIGN KEY (tenant_id, conversation_id) REFERENCES conversations
);

-- One heartbeat row per site; the gateway turns it into gauges.
CREATE TABLE IF NOT EXISTS retention_worker_status (
    site            TEXT             PRIMARY KEY CHECK (site IN ('primary', 'replica')),
    beat_at         TIMESTAMPTZ      NOT NULL,
    failing_seconds DOUBLE PRECISION NOT NULL,
    halted          BOOLEAN          NOT NULL,
    hold_mismatches INTEGER          NOT NULL
);

-- Applies a decision to its conversation under the conversation's row lock,
-- so a hold set while the worker shreds is either seen or waits (spec §16.1).
-- BEFORE triggers run ahead of the policies' WITH CHECK, hence the tenant test.
CREATE OR REPLACE FUNCTION apply_retention_decision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    target conversations%ROWTYPE;
BEGIN
    SELECT * INTO target FROM conversations
    WHERE tenant_id = NEW.tenant_id AND conversation_id = NEW.conversation_id
    FOR UPDATE;
    IF NOT FOUND OR NEW.tenant_id IS DISTINCT FROM current_setting('ssf.tenant_id', TRUE) THEN
        RAISE EXCEPTION 'no_conversation' USING ERRCODE = 'P0002';
    END IF;
    IF target.shredded_at IS NOT NULL THEN
        RAISE EXCEPTION 'conversation_shredded';
    END IF;
    IF NEW.kind = 'extend' THEN
        IF NEW.retain_until <= target.retention_until THEN
            RAISE EXCEPTION 'retention_not_extended';
        END IF;
        UPDATE conversations SET retention_until = NEW.retain_until
        WHERE tenant_id = NEW.tenant_id AND conversation_id = NEW.conversation_id;
    ELSIF NEW.kind IN ('hold_on', 'hold_off') THEN
        UPDATE conversations SET legal_hold = (NEW.kind = 'hold_on')
        WHERE tenant_id = NEW.tenant_id AND conversation_id = NEW.conversation_id;
    ELSE
        IF target.legal_hold THEN
            RAISE EXCEPTION 'legal_hold_set';
        END IF;
        IF target.ended_at IS NULL THEN
            RAISE EXCEPTION 'conversation_live';
        END IF;
    END IF;
    -- Both sites' workers look at this conversation's versions again now, by
    -- the database's clock: a decision's own time comes from the gateway.
    UPDATE version_locks SET next_attempt_at = now()
    WHERE tenant_id = NEW.tenant_id AND conversation_id = NEW.conversation_id
        AND deleted_at IS NULL;
    RETURN NEW;
END
$$;

CREATE OR REPLACE TRIGGER retention_decisions_apply
    BEFORE INSERT ON retention_decisions
    FOR EACH ROW EXECUTE FUNCTION apply_retention_decision();

-- A shredded conversation never gains a key wrap or an entry again. The share
-- lock orders the insert against a shred, which holds the row for update: an
-- insert waits for a shred in progress and then sees it, and a shred waits for
-- an insert in progress and then deletes what it inserted.
CREATE OR REPLACE FUNCTION refuse_after_shred() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    target UUID;
    shredded TIMESTAMPTZ;
BEGIN
    IF TG_TABLE_NAME = 'key_wraps' THEN
        SELECT conversation_id INTO target FROM conversation_keys
        WHERE tenant_id = NEW.tenant_id AND key_id = NEW.key_id;
    ELSE
        target := NEW.conversation_id;
    END IF;
    SELECT shredded_at INTO shredded FROM conversations
    WHERE tenant_id = NEW.tenant_id AND conversation_id = target
    FOR SHARE;
    IF shredded IS NOT NULL THEN
        RAISE EXCEPTION 'conversation_shredded';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE TRIGGER key_wraps_after_shred
    BEFORE INSERT ON key_wraps FOR EACH ROW EXECUTE FUNCTION refuse_after_shred();
CREATE OR REPLACE TRIGGER chain_entries_after_shred
    BEFORE INSERT ON chain_entries FOR EACH ROW EXECUTE FUNCTION refuse_after_shred();

-- Workers learn the tenants without writer secrets or BYPASSRLS. Audit events
-- name every tenant that ever recorded, even once its conversations are gone.
CREATE OR REPLACE FUNCTION recording_tenants() RETURNS SETOF TEXT
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT tenant_id FROM conversations
    UNION
    SELECT tenant_id FROM audit_events
    ORDER BY 1
$$;
REVOKE EXECUTE ON FUNCTION recording_tenants() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION recording_tenants() TO ssf_recording_retention, ssf_recording_replica;

GRANT SELECT, INSERT ON retention_decisions TO ssf_recording_app;
GRANT SELECT ON retention_worker_status TO ssf_recording_app;

GRANT SELECT ON conversations, recording_windows, conversation_keys, key_wraps,
    chain_entries, stored_objects, chain_stamps, retention_decisions, audit_events
    TO ssf_recording_retention;
GRANT INSERT ON retention_decisions, audit_events TO ssf_recording_retention;
GRANT UPDATE (shredded_at) ON conversations TO ssf_recording_retention;
GRANT DELETE ON conversations, recording_windows, conversation_keys, key_wraps,
    chain_entries, stored_objects, chain_stamps TO ssf_recording_retention;
GRANT SELECT, INSERT, UPDATE, DELETE ON version_locks, site_clearances
    TO ssf_recording_retention;
GRANT SELECT, INSERT, UPDATE ON retention_worker_status TO ssf_recording_retention;

GRANT SELECT ON conversations, chain_entries, stored_objects, retention_decisions, audit_events
    TO ssf_recording_replica;
GRANT SELECT, INSERT, UPDATE ON version_locks, site_clearances TO ssf_recording_replica;
GRANT SELECT, INSERT, UPDATE ON retention_worker_status TO ssf_recording_replica;

DO $$
DECLARE
    tenant_table TEXT;
BEGIN
    FOREACH tenant_table IN ARRAY ARRAY['retention_decisions', 'version_locks', 'site_clearances']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tenant_table);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tenant_table);
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE tablename = tenant_table AND policyname = tenant_table || '_tenant_isolation'
        ) THEN
            EXECUTE format(
                'CREATE POLICY %I ON %I'
                ' USING (tenant_id = current_setting(''ssf.tenant_id'', TRUE))'
                ' WITH CHECK (tenant_id = current_setting(''ssf.tenant_id'', TRUE))',
                tenant_table || '_tenant_isolation',
                tenant_table
            );
        END IF;
    END LOOP;

    -- The replica's worker sees and writes its own site's rows only.
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'version_locks_replica_site') THEN
        CREATE POLICY version_locks_replica_site ON version_locks AS RESTRICTIVE
            TO ssf_recording_replica USING (site = 'replica') WITH CHECK (site = 'replica');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'site_clearances_replica_site') THEN
        CREATE POLICY site_clearances_replica_site ON site_clearances AS RESTRICTIVE
            TO ssf_recording_replica USING (site = 'replica') WITH CHECK (site = 'replica');
    END IF;
    -- Only the operator's command, run as the primary worker, erases.
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'retention_decisions_app_kinds') THEN
        CREATE POLICY retention_decisions_app_kinds ON retention_decisions AS RESTRICTIVE
            FOR INSERT TO ssf_recording_app WITH CHECK (kind <> 'erase');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'retention_decisions_worker_kinds') THEN
        CREATE POLICY retention_decisions_worker_kinds ON retention_decisions AS RESTRICTIVE
            FOR INSERT TO ssf_recording_retention WITH CHECK (kind = 'erase');
    END IF;

    ALTER TABLE retention_worker_status ENABLE ROW LEVEL SECURITY;
    ALTER TABLE retention_worker_status FORCE ROW LEVEL SECURITY;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'retention_worker_status_read') THEN
        CREATE POLICY retention_worker_status_read ON retention_worker_status
            FOR SELECT USING (TRUE);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'retention_worker_status_primary') THEN
        CREATE POLICY retention_worker_status_primary ON retention_worker_status
            TO ssf_recording_retention USING (site = 'primary') WITH CHECK (site = 'primary');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'retention_worker_status_replica') THEN
        CREATE POLICY retention_worker_status_replica ON retention_worker_status
            TO ssf_recording_replica USING (site = 'replica') WITH CHECK (site = 'replica');
    END IF;
END
$$;
