-- Verification of archived conversations by assigned reviewers (#619, spec §10.7).
-- Applied by ../../apply.sh after 010. Every statement is idempotent.

CREATE TABLE IF NOT EXISTS verifications (
    tenant_id             TEXT        NOT NULL,
    verification_id       UUID        NOT NULL,
    conversation_id       UUID        NOT NULL,
    status                TEXT        NOT NULL CHECK (status IN
        ('awaiting', 'in_review', 'approved', 'not_approved', 'declined', 'withdrawn')),
    requested_by          TEXT        NOT NULL,
    requester_key_version INTEGER     NOT NULL,
    requested_at          TIMESTAMPTZ NOT NULL,
    directory_read_at     TIMESTAMPTZ NOT NULL,
    reviewer_sub          TEXT        NOT NULL CHECK (reviewer_sub <> requested_by),
    reviewer_key_version  INTEGER     NOT NULL,
    reviewer_fingerprint  BYTEA       NOT NULL CHECK (octet_length(reviewer_fingerprint) = 32),
    started_at            TIMESTAMPTZ,
    reviewed_head_seq     BIGINT,
    reviewed_head         BYTEA CHECK (reviewed_head IS NULL OR octet_length(reviewed_head) = 32),
    permission_snapshot   TEXT[],
    outcome               TEXT CHECK (outcome IN ('approved', 'not_approved')),
    overall_note          BYTEA CHECK (overall_note IS NULL
        OR octet_length(overall_note) BETWEEN 29 AND 32797),
    notes_digest          BYTEA CHECK (notes_digest IS NULL OR octet_length(notes_digest) = 32),
    signature             BYTEA CHECK (signature IS NULL OR octet_length(signature) = 64),
    signer_key_version    INTEGER,
    decided_at            TIMESTAMPTZ,
    closed_at             TIMESTAMPTZ,
    close_reason          TEXT CHECK (close_reason IN
        ('declined', 'key_retired', 'permission_revoked')),
    stamp_requested_at    TIMESTAMPTZ,
    stamp_next_attempt_at TIMESTAMPTZ,
    stamp_attempts        INTEGER     NOT NULL DEFAULT 0,
    tsa_token             BYTEA,
    stamped_at            TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, verification_id),
    FOREIGN KEY (tenant_id, conversation_id) REFERENCES conversations,
    CHECK ((status IN ('approved', 'not_approved')) = (outcome IS NOT NULL)),
    CHECK (outcome IS NULL OR outcome = status),
    CHECK (outcome IS NULL OR (signature IS NOT NULL AND notes_digest IS NOT NULL
        AND decided_at IS NOT NULL AND reviewed_head IS NOT NULL
        AND permission_snapshot IS NOT NULL)),
    CHECK ((status IN ('declined', 'withdrawn')) = (close_reason IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS verifications_one_open
    ON verifications (tenant_id, conversation_id, reviewer_sub)
    WHERE status IN ('awaiting', 'in_review');
CREATE INDEX IF NOT EXISTS verifications_reviewer
    ON verifications (tenant_id, reviewer_sub, status);
CREATE INDEX IF NOT EXISTS verifications_conversation
    ON verifications (tenant_id, conversation_id);
CREATE INDEX IF NOT EXISTS verifications_stamp_due
    ON verifications (tenant_id, stamp_next_attempt_at)
    WHERE tsa_token IS NULL AND stamp_requested_at IS NOT NULL;

-- One encrypted note per message of a record: its draft until decided, then final.
CREATE TABLE IF NOT EXISTS verification_notes (
    tenant_id       TEXT  NOT NULL,
    verification_id UUID  NOT NULL,
    entry_id        UUID  NOT NULL,
    key_id          UUID  NOT NULL,
    ciphertext      BYTEA NOT NULL CHECK (octet_length(ciphertext) BETWEEN 29 AND 65565),
    PRIMARY KEY (tenant_id, verification_id, entry_id),
    FOREIGN KEY (tenant_id, verification_id) REFERENCES verifications,
    FOREIGN KEY (tenant_id, entry_id) REFERENCES chain_entries (tenant_id, entry_id),
    FOREIGN KEY (tenant_id, key_id) REFERENCES conversation_keys
);

-- One nightly revocation check per tenant and day, claimed by whichever gateway gets there.
CREATE TABLE IF NOT EXISTS revocation_runs (
    tenant_id   TEXT        NOT NULL,
    run_date    DATE        NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    outcome     TEXT CHECK (outcome IN ('done', 'skipped_unreadable', 'skipped_implausible',
        'skipped_unstable', 'skipped_bound', 'failed')),
    PRIMARY KEY (tenant_id, run_date)
);

-- A decided record is evidence: afterwards only its stamp may change. A closed one is final.
CREATE OR REPLACE FUNCTION verifications_freeze() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    stamp CONSTANT TEXT[] := ARRAY['stamp_next_attempt_at', 'stamp_attempts', 'tsa_token',
        'stamped_at'];
BEGIN
    IF OLD.status IN ('approved', 'not_approved')
        AND to_jsonb(NEW) - stamp IS DISTINCT FROM to_jsonb(OLD) - stamp THEN
        RAISE EXCEPTION 'a decided verification is frozen' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status IN ('declined', 'withdrawn') AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
        RAISE EXCEPTION 'a closed verification is frozen' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;
DROP TRIGGER IF EXISTS verifications_freeze ON verifications;
CREATE TRIGGER verifications_freeze BEFORE UPDATE ON verifications
    FOR EACH ROW EXECUTE FUNCTION verifications_freeze();

-- The app writes notes only while their record is in review. Retention deletes them freely.
CREATE OR REPLACE FUNCTION verification_notes_in_review() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    note verification_notes := COALESCE(NEW, OLD);
    parent TEXT;
BEGIN
    IF current_user <> 'ssf_recording_app' THEN
        RETURN note;
    END IF;
    SELECT status INTO parent FROM verifications
        WHERE tenant_id = note.tenant_id AND verification_id = note.verification_id;
    IF parent IS DISTINCT FROM 'in_review' THEN
        RAISE EXCEPTION 'notes of a verification not in review' USING ERRCODE = 'check_violation';
    END IF;
    RETURN note;
END
$$;
DROP TRIGGER IF EXISTS verification_notes_in_review ON verification_notes;
CREATE TRIGGER verification_notes_in_review BEFORE INSERT OR DELETE ON verification_notes
    FOR EACH ROW EXECUTE FUNCTION verification_notes_in_review();

GRANT SELECT, INSERT, UPDATE ON verifications TO ssf_recording_app;
GRANT SELECT, INSERT, DELETE ON verification_notes TO ssf_recording_app;
GRANT SELECT, INSERT, UPDATE ON revocation_runs TO ssf_recording_app;
GRANT SELECT, DELETE ON verifications, verification_notes TO ssf_recording_retention;

DO $$
DECLARE
    tenant_table TEXT;
BEGIN
    FOREACH tenant_table IN ARRAY ARRAY['verifications', 'verification_notes', 'revocation_runs']
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
END
$$;
