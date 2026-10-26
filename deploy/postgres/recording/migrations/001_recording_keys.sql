-- Recording mode (#614): personal keys, the gateway's signing keys and the
-- hash-chained audit log, in the ssf_recording database. Applied by
-- ../../apply.sh; passwords arrive as psql variables, never in this file.
-- Every statement is idempotent, so re-running is safe.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssf_recording_app') THEN
        CREATE ROLE ssf_recording_app;
    END IF;
END
$$;

-- Set unconditionally, so rotating the password is a re-run of this file.
ALTER ROLE ssf_recording_app
    WITH LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

-- Only the recording roles connect here; the feedback roles have no business in it.
REVOKE CONNECT ON DATABASE :"database" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database" TO ssf_recording_app;
GRANT USAGE ON SCHEMA public TO ssf_recording_app;

-- One active key pair per user. The private keys are stored only as the
-- passphrase-sealed blob inside the gateway's server-layer envelope.
CREATE TABLE IF NOT EXISTS user_keys (
    tenant_id         TEXT        NOT NULL,
    user_sub          TEXT        NOT NULL,
    key_version       INTEGER     NOT NULL CHECK (key_version > 0),
    enc_pub           BYTEA       NOT NULL CHECK (octet_length(enc_pub) = 65),
    sig_pub           BYTEA       NOT NULL CHECK (octet_length(sig_pub) = 65),
    fingerprint       BYTEA       NOT NULL CHECK (octet_length(fingerprint) = 32),
    -- NULL once deleted (a leaver); the public keys stay to verify old signatures.
    encrypted_private BYTEA,
    created_at        TIMESTAMPTZ NOT NULL,
    retired_at        TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, user_sub, key_version)
);

CREATE UNIQUE INDEX IF NOT EXISTS user_keys_one_active
    ON user_keys (tenant_id, user_sub) WHERE retired_at IS NULL;

-- Deployment-wide, not tenant data: every gateway key that ever signed,
-- so chain entries and wraps stay verifiable after a rotation.
CREATE TABLE IF NOT EXISTS gateway_signing_keys (
    key_id        TEXT        PRIMARY KEY,
    public_key    BYTEA       NOT NULL CHECK (octet_length(public_key) = 65),
    first_seen_at TIMESTAMPTZ NOT NULL
);

-- Append-only: the application role may SELECT and INSERT, nothing else.
-- Each row's hash covers its fields and prev_hash (recording/audit.py).
CREATE TABLE IF NOT EXISTS audit_events (
    tenant_id  TEXT        NOT NULL,
    seq        BIGINT      NOT NULL CHECK (seq > 0),
    at         TIMESTAMPTZ NOT NULL,
    actor_sub  TEXT        NOT NULL,
    event_type TEXT        NOT NULL,
    object_ref TEXT        NOT NULL,
    prev_hash  BYTEA       NOT NULL CHECK (octet_length(prev_hash) = 32),
    hash       BYTEA       NOT NULL CHECK (octet_length(hash) = 32),
    PRIMARY KEY (tenant_id, seq)
);

GRANT SELECT, INSERT, UPDATE ON user_keys TO ssf_recording_app;
GRANT SELECT, INSERT ON gateway_signing_keys TO ssf_recording_app;
GRANT SELECT, INSERT ON audit_events TO ssf_recording_app;

ALTER TABLE user_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_keys FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'user_keys' AND policyname = 'user_keys_tenant_isolation'
    ) THEN
        CREATE POLICY user_keys_tenant_isolation ON user_keys
            USING (tenant_id = current_setting('ssf.tenant_id', TRUE))
            WITH CHECK (tenant_id = current_setting('ssf.tenant_id', TRUE));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'audit_events' AND policyname = 'audit_events_tenant_isolation'
    ) THEN
        CREATE POLICY audit_events_tenant_isolation ON audit_events
            USING (tenant_id = current_setting('ssf.tenant_id', TRUE))
            WITH CHECK (tenant_id = current_setting('ssf.tenant_id', TRUE));
    END IF;
END
$$;
