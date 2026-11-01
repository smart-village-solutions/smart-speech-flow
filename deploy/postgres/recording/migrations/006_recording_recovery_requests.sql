-- Recording mode (#617a): exceptional access through custodian approval
-- (spec §9.5). Applied by ../../apply.sh after 005; every statement is idempotent.
--
-- The gateway is a bulletin board again: it keeps the request its requester
-- signed, each custodian's signed decision and the partials sealed for the
-- requester. It never holds a share or a conversation key.

CREATE TABLE IF NOT EXISTS recovery_requests (
    tenant_id             TEXT        NOT NULL,
    request_id            UUID        NOT NULL,
    -- #617b widens this to 'key_recovery'.
    kind                  TEXT        NOT NULL
        CONSTRAINT recovery_requests_kind CHECK (kind IN ('access')),
    requester_sub         TEXT        NOT NULL,
    requester_key_version INTEGER     NOT NULL,
    recovery_key_id       UUID        NOT NULL,
    reason                TEXT        NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 1000),
    request_signature     BYTEA       NOT NULL CHECK (octet_length(request_signature) = 64),
    status                TEXT        NOT NULL
        CHECK (status IN ('open', 'completed', 'cancelled', 'expired', 'scope_gone')),
    created_at            TIMESTAMPTZ NOT NULL,
    expires_at            TIMESTAMPTZ NOT NULL,
    closed_at             TIMESTAMPTZ,
    CHECK ((status = 'open') = (closed_at IS NULL)),
    PRIMARY KEY (tenant_id, request_id),
    FOREIGN KEY (tenant_id, recovery_key_id) REFERENCES recovery_keys (tenant_id, key_id),
    FOREIGN KEY (tenant_id, requester_sub, requester_key_version)
        REFERENCES user_keys (tenant_id, user_sub, key_version)
);

CREATE INDEX IF NOT EXISTS recovery_requests_open_by_requester
    ON recovery_requests (tenant_id, requester_sub) WHERE status = 'open';

-- The scope, frozen and signed at filing.
CREATE TABLE IF NOT EXISTS recovery_request_keys (
    tenant_id       TEXT NOT NULL,
    request_id      UUID NOT NULL,
    conversation_id UUID NOT NULL,
    key_id          UUID NOT NULL,
    PRIMARY KEY (tenant_id, request_id, key_id),
    FOREIGN KEY (tenant_id, request_id) REFERENCES recovery_requests,
    FOREIGN KEY (tenant_id, key_id) REFERENCES conversation_keys
);

CREATE INDEX IF NOT EXISTS recovery_request_keys_conversation
    ON recovery_request_keys (tenant_id, conversation_id);

-- One row per custodian and attempt: a rejected approval may be followed by another.
CREATE TABLE IF NOT EXISTS recovery_decisions (
    tenant_id          TEXT        NOT NULL,
    request_id         UUID        NOT NULL,
    holder_index       INTEGER     NOT NULL CHECK (holder_index BETWEEN 1 AND 15),
    attempt            INTEGER     NOT NULL CHECK (attempt > 0),
    custodian_sub      TEXT        NOT NULL,
    decision           TEXT        NOT NULL CHECK (decision IN ('approved', 'declined')),
    reason             TEXT        CHECK (char_length(reason) BETWEEN 1 AND 1000),
    -- The signed list of [key_id, SHA-256 of the blob]: what approval_signature covers.
    signed_partials    JSONB,
    approval_signature BYTEA       CHECK (octet_length(approval_signature) = 64),
    decided_at         TIMESTAMPTZ NOT NULL,
    CHECK ((decision = 'declined') = (reason IS NOT NULL)),
    CHECK ((decision = 'approved') = (signed_partials IS NOT NULL AND approval_signature IS NOT NULL)),
    PRIMARY KEY (tenant_id, request_id, holder_index, attempt),
    FOREIGN KEY (tenant_id, request_id) REFERENCES recovery_requests
);

-- Key material like a wrap: deleted when the request closes and at a shred.
CREATE TABLE IF NOT EXISTS recovery_partials (
    tenant_id       TEXT    NOT NULL,
    request_id      UUID    NOT NULL,
    holder_index    INTEGER NOT NULL,
    attempt         INTEGER NOT NULL,
    conversation_id UUID    NOT NULL,
    key_id          UUID    NOT NULL,
    blob            TEXT    NOT NULL CHECK (char_length(blob) <= 1024),
    PRIMARY KEY (tenant_id, request_id, holder_index, attempt, key_id),
    FOREIGN KEY (tenant_id, request_id, holder_index, attempt) REFERENCES recovery_decisions,
    FOREIGN KEY (tenant_id, key_id) REFERENCES conversation_keys
);

CREATE TABLE IF NOT EXISTS recovery_rejections (
    tenant_id    TEXT        NOT NULL,
    request_id   UUID        NOT NULL,
    holder_index INTEGER     NOT NULL,
    attempt      INTEGER     NOT NULL,
    fault        TEXT        NOT NULL CHECK (fault IN ('partial_unreadable', 'proof_invalid')),
    rejected_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, request_id, holder_index, attempt),
    FOREIGN KEY (tenant_id, request_id, holder_index, attempt) REFERENCES recovery_decisions
);

-- refuse_after_shred (004) reads NEW.conversation_id for every table but key_wraps.
CREATE OR REPLACE TRIGGER recovery_partials_after_shred
    BEFORE INSERT ON recovery_partials FOR EACH ROW EXECUTE FUNCTION refuse_after_shred();

GRANT SELECT, INSERT ON recovery_requests, recovery_request_keys, recovery_decisions,
    recovery_rejections TO ssf_recording_app;
GRANT UPDATE (status, closed_at) ON recovery_requests TO ssf_recording_app;
GRANT SELECT, INSERT, DELETE ON recovery_partials TO ssf_recording_app;
GRANT SELECT, DELETE ON recovery_requests, recovery_request_keys, recovery_decisions,
    recovery_partials, recovery_rejections TO ssf_recording_retention;
-- The worker closes requests that lapsed untouched, deleting their partials.
GRANT UPDATE (status, closed_at) ON recovery_requests TO ssf_recording_retention;

DO $$
DECLARE
    tenant_table TEXT;
BEGIN
    FOREACH tenant_table IN ARRAY ARRAY[
        'recovery_requests', 'recovery_request_keys', 'recovery_decisions',
        'recovery_partials', 'recovery_rejections'
    ] LOOP
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
END
$$;
