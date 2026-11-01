-- Resharing (#617c, spec §9.7): a recovery key's shares move to a new holder
-- set while X, the key ID and every recovery wrap stay. Applied by
-- ../../apply.sh after 007. Every statement is idempotent.

ALTER TABLE recovery_ceremonies ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'generation';
ALTER TABLE recovery_ceremonies ADD COLUMN IF NOT EXISTS recovery_key_id UUID;
ALTER TABLE recovery_ceremonies ADD COLUMN IF NOT EXISTS previous_transcript_hash BYTEA
    CHECK (octet_length(previous_transcript_hash) = 32);
ALTER TABLE recovery_ceremonies DROP CONSTRAINT IF EXISTS recovery_ceremonies_kind;
ALTER TABLE recovery_ceremonies ADD CONSTRAINT recovery_ceremonies_kind CHECK (
    (kind = 'generation' AND recovery_key_id IS NULL AND previous_transcript_hash IS NULL)
    OR (kind = 'resharing' AND recovery_key_id IS NOT NULL
        AND previous_transcript_hash IS NOT NULL)
);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'recovery_ceremonies_key') THEN
        ALTER TABLE recovery_ceremonies ADD CONSTRAINT recovery_ceremonies_key
            FOREIGN KEY (tenant_id, recovery_key_id) REFERENCES recovery_keys;
    END IF;
END
$$;

-- Who deals: a first ceremony's custodians, or k holders of the previous
-- generation under their old index. Their identities resolve there, not among
-- this ceremony's participants, where the same index names someone else.
CREATE TABLE IF NOT EXISTS ceremony_dealers (
    tenant_id    TEXT    NOT NULL,
    ceremony_id  UUID    NOT NULL,
    dealer_index INTEGER NOT NULL CHECK (dealer_index BETWEEN 1 AND 15),
    holder_ref   TEXT    NOT NULL,
    kind         TEXT    NOT NULL CHECK (kind IN ('custodian', 'paper')),
    PRIMARY KEY (tenant_id, ceremony_id, dealer_index),
    FOREIGN KEY (tenant_id, ceremony_id) REFERENCES recovery_ceremonies
);
INSERT INTO ceremony_dealers (tenant_id, ceremony_id, dealer_index, holder_ref, kind)
    SELECT p.tenant_id, p.ceremony_id, p.holder_index, p.holder_ref, p.kind
    FROM ceremony_participants p JOIN recovery_ceremonies c
        ON c.tenant_id = p.tenant_id AND c.ceremony_id = p.ceremony_id
    WHERE p.kind = 'custodian' AND c.kind = 'generation'
    ON CONFLICT DO NOTHING;

ALTER TABLE ceremony_dealings
    DROP CONSTRAINT IF EXISTS ceremony_dealings_tenant_id_ceremony_id_dealer_index_fkey;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ceremony_dealings_dealer') THEN
        ALTER TABLE ceremony_dealings ADD CONSTRAINT ceremony_dealings_dealer
            FOREIGN KEY (tenant_id, ceremony_id, dealer_index) REFERENCES ceremony_dealers;
    END IF;
END
$$;
-- A paper sheet has no signing key; the gateway requires one from every custodian.
ALTER TABLE ceremony_dealings ALTER COLUMN signature DROP NOT NULL;

-- A closed ceremony's sub-shares are a complete sharing that nobody needs any more.
UPDATE ceremony_dealings d SET subshares = '{}'::jsonb
    FROM recovery_ceremonies c
    WHERE c.tenant_id = d.tenant_id AND c.ceremony_id = d.ceremony_id
      AND c.status IN ('active', 'aborted') AND d.subshares <> '{}'::jsonb;

-- A resharing's custodian proves it holds the share it just sealed.
ALTER TABLE ceremony_confirmations ADD COLUMN IF NOT EXISTS share_proof_c BYTEA
    CHECK (octet_length(share_proof_c) = 32);
ALTER TABLE ceremony_confirmations ADD COLUMN IF NOT EXISTS share_proof_s BYTEA
    CHECK (octet_length(share_proof_s) = 32);
ALTER TABLE ceremony_confirmations DROP CONSTRAINT IF EXISTS ceremony_confirmations_share_proof;
ALTER TABLE ceremony_confirmations ADD CONSTRAINT ceremony_confirmations_share_proof
    CHECK ((share_proof_c IS NULL) = (share_proof_s IS NULL));

ALTER TABLE recovery_shares ADD COLUMN IF NOT EXISTS ceremony_id UUID;
UPDATE recovery_shares SET ceremony_id = key_id WHERE ceremony_id IS NULL;
ALTER TABLE recovery_shares ALTER COLUMN ceremony_id SET NOT NULL;

-- The key keeps its ID and first transcript, which every recovery wrap signs;
-- its holders are those of the latest completed generation.
ALTER TABLE recovery_keys ADD COLUMN IF NOT EXISTS holders_ceremony_id UUID;
ALTER TABLE recovery_keys ADD COLUMN IF NOT EXISTS holders_transcript_hash BYTEA
    CHECK (octet_length(holders_transcript_hash) = 32);
UPDATE recovery_keys SET holders_ceremony_id = key_id, holders_transcript_hash = transcript_hash
    WHERE holders_ceremony_id IS NULL OR holders_transcript_hash IS NULL;
ALTER TABLE recovery_keys ALTER COLUMN holders_ceremony_id SET NOT NULL;
ALTER TABLE recovery_keys ALTER COLUMN holders_transcript_hash SET NOT NULL;

-- A request is decided by the holders it was filed under, and counts their k.
ALTER TABLE recovery_requests ADD COLUMN IF NOT EXISTS holders_ceremony_id UUID;
UPDATE recovery_requests r SET holders_ceremony_id = k.holders_ceremony_id
    FROM recovery_keys k
    WHERE k.tenant_id = r.tenant_id AND k.key_id = r.recovery_key_id
      AND r.holders_ceremony_id IS NULL;
ALTER TABLE recovery_requests ALTER COLUMN holders_ceremony_id SET NOT NULL;

-- Each generation column names a ceremony that exists.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'recovery_shares_generation') THEN
        ALTER TABLE recovery_shares ADD CONSTRAINT recovery_shares_generation
            FOREIGN KEY (tenant_id, ceremony_id) REFERENCES recovery_ceremonies;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'recovery_keys_holders') THEN
        ALTER TABLE recovery_keys ADD CONSTRAINT recovery_keys_holders
            FOREIGN KEY (tenant_id, holders_ceremony_id) REFERENCES recovery_ceremonies;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'recovery_requests_generation') THEN
        ALTER TABLE recovery_requests ADD CONSTRAINT recovery_requests_generation
            FOREIGN KEY (tenant_id, holders_ceremony_id) REFERENCES recovery_ceremonies;
    END IF;
END
$$;

GRANT SELECT, INSERT ON ceremony_dealers TO ssf_recording_app;
GRANT UPDATE (subshares) ON ceremony_dealings TO ssf_recording_app;
GRANT DELETE ON recovery_shares TO ssf_recording_app;
GRANT UPDATE (holders_ceremony_id, holders_transcript_hash, k, n, mode)
    ON recovery_keys TO ssf_recording_app;

ALTER TABLE ceremony_dealers ENABLE ROW LEVEL SECURITY;
ALTER TABLE ceremony_dealers FORCE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'ceremony_dealers' AND policyname = 'ceremony_dealers_tenant_isolation'
    ) THEN
        CREATE POLICY ceremony_dealers_tenant_isolation ON ceremony_dealers
            USING (tenant_id = current_setting('ssf.tenant_id', TRUE))
            WITH CHECK (tenant_id = current_setting('ssf.tenant_id', TRUE));
    END IF;
END
$$;
