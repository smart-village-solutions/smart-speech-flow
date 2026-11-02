-- Email confirmation of a re-enrolment (#632, spec §9.9).
-- Applied by ../../apply.sh after 009. Every statement is idempotent.

-- The address a re-enrolment of this key is confirmed through, pinned at enrolment
-- and inherited by every later key; NULL once the key is retired.
ALTER TABLE user_keys ADD COLUMN IF NOT EXISTS email TEXT;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_keys_email_length') THEN
        ALTER TABLE user_keys ADD CONSTRAINT user_keys_email_length
            CHECK (email IS NULL OR char_length(email) BETWEEN 1 AND 254);
    END IF;
END
$$;

-- A new key waiting for its owner to open the mailed link. Only the token's hash is kept.
CREATE TABLE IF NOT EXISTS user_key_reenrolments (
    tenant_id         TEXT        NOT NULL,
    user_sub          TEXT        NOT NULL,
    key_version       INTEGER     NOT NULL CHECK (key_version > 1),
    enc_pub           BYTEA       NOT NULL CHECK (octet_length(enc_pub) = 65),
    sig_pub           BYTEA       NOT NULL CHECK (octet_length(sig_pub) = 65),
    fingerprint       BYTEA       NOT NULL CHECK (octet_length(fingerprint) = 32),
    encrypted_private BYTEA       NOT NULL,
    email             TEXT        NOT NULL CHECK (char_length(email) BETWEEN 1 AND 254),
    replaces_version  INTEGER     NOT NULL CHECK (replaces_version = key_version - 1),
    token_hash        BYTEA       NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
    requested_at      TIMESTAMPTZ NOT NULL,
    expires_at        TIMESTAMPTZ NOT NULL CHECK (expires_at > requested_at),
    PRIMARY KEY (tenant_id, user_sub)
);
CREATE INDEX IF NOT EXISTS user_key_reenrolments_expiry
    ON user_key_reenrolments (tenant_id, expires_at);

ALTER TABLE user_key_reenrolments ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_key_reenrolments FORCE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'user_key_reenrolments'
          AND policyname = 'user_key_reenrolments_tenant_isolation'
    ) THEN
        CREATE POLICY user_key_reenrolments_tenant_isolation ON user_key_reenrolments
            USING (tenant_id = current_setting('ssf.tenant_id', TRUE))
            WITH CHECK (tenant_id = current_setting('ssf.tenant_id', TRUE));
    END IF;
END
$$;
GRANT SELECT, INSERT, DELETE ON user_key_reenrolments TO ssf_recording_app;

-- The link carries no tenant: the token's hash names it, and RLS confines the rest.
CREATE OR REPLACE FUNCTION reenrolment_tenant(hash BYTEA) RETURNS TEXT
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT tenant_id FROM user_key_reenrolments WHERE token_hash = hash
$$;
REVOKE EXECUTE ON FUNCTION reenrolment_tenant(BYTEA) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION reenrolment_tenant(BYTEA) TO ssf_recording_app;
