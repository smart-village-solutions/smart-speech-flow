-- Recording mode (#614): the recovery-key ceremony (spec §9.2) and the
-- recovery keys it produces. Applied by ../../apply.sh after 001; every
-- statement is idempotent.
--
-- The gateway is a bulletin board here: it stores what custodians publish
-- (commitments, proofs, sub-shares sealed for each holder, signatures) and
-- re-checks every public value, but never sees a share or the recovery key.

CREATE TABLE IF NOT EXISTS recovery_ceremonies (
    tenant_id          TEXT        NOT NULL,
    ceremony_id        UUID        NOT NULL,
    k                  INTEGER     NOT NULL CHECK (k BETWEEN 1 AND 5),
    started_by         TEXT        NOT NULL,
    started_at         TIMESTAMPTZ NOT NULL,
    expires_at         TIMESTAMPTZ NOT NULL,
    status             TEXT        NOT NULL
        CHECK (status IN ('dealing', 'confirming', 'active', 'aborted')),
    -- The gateway keys the transcript lists, fixed when the ceremony starts.
    gateway_keys       JSONB       NOT NULL,
    transcript_hash    BYTEA       CHECK (octet_length(transcript_hash) = 32),
    paper_confirmed_at TIMESTAMPTZ,
    closed_at          TIMESTAMPTZ,
    close_reason       TEXT,
    PRIMARY KEY (tenant_id, ceremony_id)
);

-- At most one ceremony in progress per tenant.
CREATE UNIQUE INDEX IF NOT EXISTS recovery_ceremonies_one_open
    ON recovery_ceremonies (tenant_id) WHERE status IN ('dealing', 'confirming');

-- Custodians are holders 1..c, paper shares c+1..n. A paper holder has the
-- ceremony device's encryption key and no signing key.
CREATE TABLE IF NOT EXISTS ceremony_participants (
    tenant_id    TEXT    NOT NULL,
    ceremony_id  UUID    NOT NULL,
    holder_index INTEGER NOT NULL CHECK (holder_index BETWEEN 1 AND 15),
    holder_ref   TEXT    NOT NULL,
    kind         TEXT    NOT NULL CHECK (kind IN ('custodian', 'paper')),
    display_name TEXT,
    enc_pub      BYTEA   NOT NULL CHECK (octet_length(enc_pub) = 65),
    sig_pub      BYTEA   CHECK (octet_length(sig_pub) = 65),
    fingerprint  BYTEA   NOT NULL CHECK (octet_length(fingerprint) = 32),
    CHECK ((kind = 'custodian') = (sig_pub IS NOT NULL)),
    PRIMARY KEY (tenant_id, ceremony_id, holder_index),
    UNIQUE (tenant_id, ceremony_id, holder_ref),
    FOREIGN KEY (tenant_id, ceremony_id) REFERENCES recovery_ceremonies
);

-- One dealing per custodian: Feldman commitments, the Schnorr proof, the
-- dealer's signature over both, and a sealed sub-share per holder index.
CREATE TABLE IF NOT EXISTS ceremony_dealings (
    tenant_id    TEXT        NOT NULL,
    ceremony_id  UUID        NOT NULL,
    dealer_index INTEGER     NOT NULL,
    commitments  BYTEA[]     NOT NULL,
    proof_c      BYTEA       NOT NULL CHECK (octet_length(proof_c) = 32),
    proof_s      BYTEA       NOT NULL CHECK (octet_length(proof_s) = 32),
    signature    BYTEA       NOT NULL CHECK (octet_length(signature) = 64),
    subshares    JSONB       NOT NULL,
    dealt_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, ceremony_id, dealer_index),
    FOREIGN KEY (tenant_id, ceremony_id, dealer_index) REFERENCES ceremony_participants
);

-- A custodian's signature over the transcript hash and its own share,
-- sealed for its own key.
CREATE TABLE IF NOT EXISTS ceremony_confirmations (
    tenant_id            TEXT        NOT NULL,
    ceremony_id          UUID        NOT NULL,
    holder_index         INTEGER     NOT NULL,
    transcript_signature BYTEA       NOT NULL CHECK (octet_length(transcript_signature) = 64),
    encrypted_share      TEXT        NOT NULL,
    confirmed_at         TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, ceremony_id, holder_index),
    FOREIGN KEY (tenant_id, ceremony_id, holder_index) REFERENCES ceremony_participants
);

-- The key ID is the ID of the ceremony that created it.
CREATE TABLE IF NOT EXISTS recovery_keys (
    tenant_id            TEXT        NOT NULL,
    key_id               UUID        NOT NULL,
    recovery_public_key  BYTEA       NOT NULL CHECK (octet_length(recovery_public_key) = 65),
    k                    INTEGER     NOT NULL,
    n                    INTEGER     NOT NULL CHECK (n >= k),
    mode                 TEXT        NOT NULL CHECK (mode IN ('standard', 'enhanced')),
    transcript_hash      BYTEA       NOT NULL CHECK (octet_length(transcript_hash) = 32),
    canary_wrap          TEXT        NOT NULL,
    canary_signature     BYTEA       NOT NULL CHECK (octet_length(canary_signature) = 64),
    canary_signer_key_id TEXT        NOT NULL,
    status               TEXT        NOT NULL CHECK (status IN ('active', 'retired')),
    activated_at         TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, key_id),
    FOREIGN KEY (tenant_id, key_id) REFERENCES recovery_ceremonies (tenant_id, ceremony_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS recovery_keys_one_active
    ON recovery_keys (tenant_id) WHERE status = 'active';

-- Paper shares exist only on paper: their row keeps X_i, never a share.
CREATE TABLE IF NOT EXISTS recovery_shares (
    tenant_id           TEXT    NOT NULL,
    key_id              UUID    NOT NULL,
    holder_index        INTEGER NOT NULL,
    holder_ref          TEXT    NOT NULL,
    holder_public_share BYTEA   NOT NULL CHECK (octet_length(holder_public_share) = 65),
    encrypted_share     TEXT,
    PRIMARY KEY (tenant_id, key_id, holder_index),
    FOREIGN KEY (tenant_id, key_id) REFERENCES recovery_keys
);

-- Only a ceremony's status columns ever change; everything else is append-only.
GRANT SELECT, INSERT, UPDATE ON recovery_ceremonies TO ssf_recording_app;
GRANT SELECT, INSERT ON ceremony_participants, ceremony_dealings, ceremony_confirmations,
    recovery_keys, recovery_shares TO ssf_recording_app;

DO $$
DECLARE
    tenant_table TEXT;
BEGIN
    FOREACH tenant_table IN ARRAY ARRAY[
        'recovery_ceremonies', 'ceremony_participants', 'ceremony_dealings',
        'ceremony_confirmations', 'recovery_keys', 'recovery_shares'
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
