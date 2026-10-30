-- Employee key recovery (#617b, spec §9.6): a second request kind, user-wrap
-- deletion at re-enrolment, and keys a requester reported unrecoverable.
-- Applied by ../../apply.sh after 006. Every statement is idempotent.

ALTER TABLE recovery_requests DROP CONSTRAINT IF EXISTS recovery_requests_kind;
ALTER TABLE recovery_requests ADD CONSTRAINT recovery_requests_kind
    CHECK (kind IN ('access', 'key_recovery'));

-- Re-enrolment deletes the caller's user wraps, sealed to a key nobody can open
-- again. A recovery wrap is the authority's access and must never go this way.
GRANT DELETE ON key_wraps TO ssf_recording_app;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'key_wraps' AND policyname = 'key_wraps_app_deletes_user_only'
    ) THEN
        CREATE POLICY key_wraps_app_deletes_user_only ON key_wraps
            AS RESTRICTIVE FOR DELETE TO ssf_recording_app
            USING (recipient_kind = 'user');
    END IF;
END
$$;

-- A recovery wrap the requester's browser could not use: its signature failed,
-- or it did not open despite valid proofs. It only ever narrows the requester's
-- own access, so their report is trusted.
CREATE TABLE IF NOT EXISTS recovery_unrecoverable_keys (
    tenant_id       TEXT        NOT NULL,
    request_id      UUID        NOT NULL,
    conversation_id UUID        NOT NULL,
    key_id          UUID        NOT NULL,
    stage           TEXT        NOT NULL CHECK (stage IN ('wrap_signature', 'wrap_damaged')),
    reported_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, request_id, key_id),
    FOREIGN KEY (tenant_id, request_id) REFERENCES recovery_requests,
    FOREIGN KEY (tenant_id, key_id) REFERENCES conversation_keys
);

CREATE OR REPLACE TRIGGER recovery_unrecoverable_keys_after_shred
    BEFORE INSERT ON recovery_unrecoverable_keys
    FOR EACH ROW EXECUTE FUNCTION refuse_after_shred();

GRANT SELECT, INSERT ON recovery_unrecoverable_keys TO ssf_recording_app;
GRANT SELECT, DELETE ON recovery_unrecoverable_keys TO ssf_recording_retention;

ALTER TABLE recovery_unrecoverable_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery_unrecoverable_keys FORCE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'recovery_unrecoverable_keys'
          AND policyname = 'recovery_unrecoverable_keys_tenant_isolation'
    ) THEN
        CREATE POLICY recovery_unrecoverable_keys_tenant_isolation
            ON recovery_unrecoverable_keys
            USING (tenant_id = current_setting('ssf.tenant_id', TRUE))
            WITH CHECK (tenant_id = current_setting('ssf.tenant_id', TRUE));
    END IF;
END
$$;
