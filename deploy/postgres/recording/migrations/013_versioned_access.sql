-- Mark incompatible tenant state exactly once. No recording or key material is deleted.
BEGIN;
DO $$
BEGIN
    IF to_regclass('recording_protocol') IS NULL THEN
        CREATE TABLE recording_protocol (
            tenant_id text PRIMARY KEY,
            generation integer NOT NULL CHECK (generation IN (1,2))
        );
        INSERT INTO recording_protocol
        SELECT tenant_id, 1 FROM (
            SELECT tenant_id FROM user_keys UNION SELECT tenant_id FROM conversations
            UNION SELECT tenant_id FROM recovery_ceremonies UNION SELECT tenant_id FROM recovery_keys
            UNION SELECT tenant_id FROM user_key_reenrolments
        ) legacy;
    END IF;
END $$;
ALTER TABLE user_keys ADD COLUMN IF NOT EXISTS superseded_at timestamptz;
ALTER TABLE user_keys ADD COLUMN IF NOT EXISTS state text GENERATED ALWAYS AS (
    CASE WHEN left_at IS NOT NULL THEN 'left' WHEN retired_at IS NULL THEN 'active'
         WHEN superseded_at IS NOT NULL THEN 'superseded' ELSE 'revoked' END
) STORED;

CREATE TABLE IF NOT EXISTS organisation_keys (
    tenant_id text NOT NULL, key_id uuid NOT NULL, version integer NOT NULL CHECK (version > 0),
    public_key bytea NOT NULL CHECK (octet_length(public_key)=65),
    fingerprint bytea NOT NULL CHECK (octet_length(fingerprint)=32),
    state text NOT NULL CHECK (state IN ('prepared','active','superseded')),
    created_at timestamptz NOT NULL, activated_at timestamptz,
    PRIMARY KEY (tenant_id,key_id), UNIQUE (tenant_id,version)
);
CREATE UNIQUE INDEX IF NOT EXISTS organisation_one_active ON organisation_keys(tenant_id) WHERE state='active';

CREATE TABLE IF NOT EXISTS key_preparations (
    tenant_id text NOT NULL, preparation_id uuid NOT NULL, actor_sub text NOT NULL,
    purpose text NOT NULL CHECK (purpose IN ('activation','transfer')),
    key_id uuid NOT NULL, snapshot jsonb NOT NULL, expires_at timestamptz NOT NULL,
    sealed_nonce bytea, failures integer NOT NULL DEFAULT 0 CHECK (failures BETWEEN 0 AND 5),
    request_digest bytea, receipt jsonb,
    PRIMARY KEY (tenant_id, preparation_id), FOREIGN KEY (tenant_id,key_id) REFERENCES organisation_keys
);

ALTER TABLE key_wraps ADD COLUMN IF NOT EXISTS recipient_version integer NOT NULL DEFAULT 0;
ALTER TABLE key_wraps ADD COLUMN IF NOT EXISTS recipient_fingerprint bytea;
ALTER TABLE key_wraps DROP CONSTRAINT IF EXISTS key_wraps_recipient_kind_check;
ALTER TABLE key_wraps ADD CONSTRAINT key_wraps_recipient_kind_check
    CHECK (recipient_kind IN ('user','recovery','organisation'));
ALTER TABLE key_wraps DROP CONSTRAINT IF EXISTS key_wraps_pkey;
ALTER TABLE key_wraps ADD PRIMARY KEY (tenant_id,key_id,recipient_kind,recipient_ref,recipient_version);

CREATE TABLE IF NOT EXISTS key_grants (
    tenant_id text NOT NULL, key_id uuid NOT NULL, user_sub text NOT NULL, key_version integer NOT NULL,
    reason text NOT NULL CHECK(reason IN ('owner','transfer','review')), grant_ref uuid NOT NULL,
    PRIMARY KEY(tenant_id,key_id,user_sub,key_version,reason,grant_ref),
    FOREIGN KEY(tenant_id,user_sub,key_version) REFERENCES user_keys,
    FOREIGN KEY(tenant_id,key_id) REFERENCES conversation_keys ON DELETE CASCADE
);
GRANT SELECT ON recording_protocol TO ssf_recording_app,ssf_recording_retention,ssf_recording_replica;
GRANT SELECT,INSERT,UPDATE ON organisation_keys,key_preparations TO ssf_recording_app;
GRANT SELECT,INSERT,DELETE ON key_grants TO ssf_recording_app;
GRANT SELECT,DELETE ON key_grants TO ssf_recording_retention;
DO $$
DECLARE item text;
BEGIN
    FOREACH item IN ARRAY ARRAY['recording_protocol','organisation_keys','key_preparations','key_grants'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',item);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',item);
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename=item AND policyname='tenant_isolation') THEN
            EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (tenant_id=current_setting(''ssf.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''ssf.tenant_id'',true))',item);
        END IF;
    END LOOP;
END $$;
-- Sweep orphaned challenges even when their tenant sends no further requests.
CREATE INDEX IF NOT EXISTS key_preparations_unused_expiry ON key_preparations(expires_at)
    WHERE sealed_nonce IS NOT NULL;
CREATE OR REPLACE FUNCTION public.expire_recording_preparation_secrets() RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
    UPDATE public.key_preparations SET sealed_nonce=NULL
    WHERE expires_at <= statement_timestamp() AND sealed_nonce IS NOT NULL;
$$;
REVOKE ALL ON FUNCTION public.expire_recording_preparation_secrets() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.expire_recording_preparation_secrets() TO ssf_recording_app;
COMMIT;
