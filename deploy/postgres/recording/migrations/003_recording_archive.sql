-- Recording mode (#615): recorded conversations, their windows, keys and
-- wraps, the signed chain and its timestamps (spec §11, §13). Applied by
-- ../../apply.sh after 002; every statement is idempotent.
--
-- What a reader needs to list and retain conversations is in clear (times,
-- statuses, the employee's sub); everything said is in the archive store,
-- encrypted under keys this database holds only wrapped.

CREATE TABLE IF NOT EXISTS conversations (
    tenant_id               TEXT        NOT NULL,
    conversation_id         UUID        NOT NULL,
    -- An HMAC of the session ID in its own domain: not telemetry's reference.
    session_ref             TEXT        NOT NULL,
    employee_sub            TEXT        NOT NULL,
    legal_basis             TEXT        NOT NULL CHECK (legal_basis IN ('consent', 'statutory')),
    -- Fixed at the first yes, like the retention date, so stamping needs no policy read.
    timestamp_authority_url TEXT        NOT NULL,
    started_at              TIMESTAMPTZ NOT NULL,
    retention_until         TIMESTAMPTZ NOT NULL,
    legal_hold              BOOLEAN     NOT NULL DEFAULT FALSE,
    ended_at                TIMESTAMPTZ,
    -- A pause, a failed message or an entry whose objects never arrived (§10.5).
    incomplete              BOOLEAN     NOT NULL DEFAULT FALSE,
    PRIMARY KEY (tenant_id, conversation_id)
);

CREATE TABLE IF NOT EXISTS recording_windows (
    tenant_id       TEXT        NOT NULL,
    window_id       UUID        NOT NULL,
    conversation_id UUID        NOT NULL,
    opened_at       TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ,
    close_reason    TEXT,
    -- [{"at", "reason", "resumed_at"}], in order.
    pauses          JSONB       NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (tenant_id, window_id),
    FOREIGN KEY (tenant_id, conversation_id) REFERENCES conversations
);

-- A new epoch after every gateway restart: the key itself never leaves memory.
CREATE TABLE IF NOT EXISTS conversation_keys (
    tenant_id       TEXT        NOT NULL,
    key_id          UUID        NOT NULL,
    conversation_id UUID        NOT NULL,
    epoch           INTEGER     NOT NULL CHECK (epoch > 0),
    created_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, key_id),
    UNIQUE (tenant_id, conversation_id, epoch),
    FOREIGN KEY (tenant_id, conversation_id) REFERENCES conversations
);

CREATE TABLE IF NOT EXISTS key_wraps (
    tenant_id         TEXT        NOT NULL,
    key_id            UUID        NOT NULL,
    recipient_kind    TEXT        NOT NULL CHECK (recipient_kind IN ('user', 'recovery')),
    recipient_ref     TEXT        NOT NULL,
    blob              TEXT        NOT NULL,
    creator_ref       TEXT        NOT NULL,
    creator_signature BYTEA       NOT NULL CHECK (octet_length(creator_signature) = 64),
    granted_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, key_id, recipient_kind, recipient_ref),
    FOREIGN KEY (tenant_id, key_id) REFERENCES conversation_keys
);

-- Append-only. `objects` is the exact text the signature covers.
CREATE TABLE IF NOT EXISTS chain_entries (
    tenant_id       TEXT        NOT NULL,
    conversation_id UUID        NOT NULL,
    seq             BIGINT      NOT NULL CHECK (seq > 0),
    entry_id        UUID        NOT NULL,
    kind            TEXT        NOT NULL
        CHECK (kind IN ('message', 'failed', 'consent', 'playback', 'amendment')),
    window_id       UUID,
    key_id          UUID        NOT NULL,
    objects         TEXT        NOT NULL,
    prev_hash       BYTEA       NOT NULL CHECK (octet_length(prev_hash) = 32),
    hash            BYTEA       NOT NULL CHECK (octet_length(hash) = 32),
    signer_key_id   TEXT        NOT NULL REFERENCES gateway_signing_keys (key_id),
    signature       BYTEA       NOT NULL CHECK (octet_length(signature) = 64),
    created_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, conversation_id, seq),
    UNIQUE (tenant_id, entry_id),
    FOREIGN KEY (tenant_id, conversation_id) REFERENCES conversations,
    FOREIGN KEY (tenant_id, key_id) REFERENCES conversation_keys
);

-- One row per object the store confirmed, with the version ID it assigned.
-- An entry is `stored` once each object it lists has a row, else `pending_upload`.
CREATE TABLE IF NOT EXISTS stored_objects (
    tenant_id   TEXT        NOT NULL,
    entry_id    UUID        NOT NULL,
    object_type TEXT        NOT NULL,
    version_id  TEXT        NOT NULL,
    stored_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, entry_id, object_type),
    FOREIGN KEY (tenant_id, entry_id) REFERENCES chain_entries (tenant_id, entry_id)
);

-- A chain head waiting for, or holding, its RFC 3161 token (§11.2).
CREATE TABLE IF NOT EXISTS chain_stamps (
    tenant_id       TEXT        NOT NULL,
    conversation_id UUID        NOT NULL,
    head_seq        BIGINT      NOT NULL,
    head_hash       BYTEA       NOT NULL CHECK (octet_length(head_hash) = 32),
    requested_at    TIMESTAMPTZ NOT NULL,
    attempts        INTEGER     NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL,
    tsa_token       BYTEA,
    stamped_at      TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, conversation_id, head_seq),
    FOREIGN KEY (tenant_id, conversation_id, head_seq) REFERENCES chain_entries
);

-- Only the columns that record what happened later may change; the chain may not.
GRANT SELECT, INSERT ON conversations, recording_windows, conversation_keys, key_wraps,
    chain_entries, stored_objects, chain_stamps TO ssf_recording_app;
GRANT UPDATE (ended_at, incomplete) ON conversations TO ssf_recording_app;
GRANT UPDATE (closed_at, close_reason, pauses) ON recording_windows TO ssf_recording_app;
GRANT UPDATE (attempts, next_attempt_at, tsa_token, stamped_at) ON chain_stamps
    TO ssf_recording_app;

DO $$
DECLARE
    tenant_table TEXT;
BEGIN
    FOREACH tenant_table IN ARRAY ARRAY[
        'conversations', 'recording_windows', 'conversation_keys', 'key_wraps',
        'chain_entries', 'stored_objects', 'chain_stamps'
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
