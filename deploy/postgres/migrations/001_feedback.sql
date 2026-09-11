-- Authoritative feedback storage. Free text lives here and nowhere else.
--
-- ClickHouse holds the structured ratings for analysis; this table holds the
-- optional improvement text, encrypted, with a stored twelve-month expiry.
-- Nothing here may be projected into the telemetry pipeline.
--
-- Every statement is IF NOT EXISTS so re-running apply.sh is safe, matching
-- deploy/clickhouse/apply.sh.

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id              UUID        PRIMARY KEY,
    tenant_id                TEXT        NOT NULL,
    -- The keyed HMAC from session_pseudonym.py, never the raw session id.
    -- MISSING_REFERENCE ('0' x 32) when the submission carried no session.
    session_ref              CHAR(32)    NOT NULL,
    translation_quality      SMALLINT    NOT NULL
        CHECK (translation_quality BETWEEN 1 AND 5),
    performance              SMALLINT    NOT NULL
        CHECK (performance BETWEEN 1 AND 5),
    usability                SMALLINT    NOT NULL
        CHECK (usability BETWEEN 1 AND 5),
    net_promoter_score       SMALLINT    NOT NULL
        CHECK (net_promoter_score BETWEEN 0 AND 10),
    -- AES-GCM: version byte || nonce || ciphertext || tag. NULL when the
    -- submitter left the field empty, which is not an empty string.
    improvements_ciphertext  BYTEA       NULL,
    form_version             TEXT        NOT NULL,
    retention_policy_version TEXT        NOT NULL,
    consent_snapshot         JSONB       NOT NULL,
    analytics_event_id       UUID        NOT NULL,
    analytics_state          TEXT        NOT NULL
        CHECK (analytics_state IN ('pending', 'delivered', 'not_applicable')),
    created_at               TIMESTAMPTZ NOT NULL,
    -- Stored, never computed: a later retention policy must not be able to
    -- move an existing record's expiry.
    expires_at               TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS feedback_expires_at_idx ON feedback (expires_at);
CREATE INDEX IF NOT EXISTS feedback_pending_idx ON feedback (analytics_state)
    WHERE analytics_state = 'pending';
CREATE INDEX IF NOT EXISTS feedback_tenant_idx ON feedback (tenant_id);

-- Content-free audit tables. Both outlive the rows they describe, so they can
-- answer "was this deleted on time" without answering "what did it say".
CREATE TABLE IF NOT EXISTS feedback_access_audit (
    audit_id     BIGSERIAL   PRIMARY KEY,
    feedback_id  UUID        NOT NULL,
    tenant_id    TEXT        NOT NULL,
    accessed_by  TEXT        NOT NULL,
    accessed_at  TIMESTAMPTZ NOT NULL,
    access_scope TEXT        NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_deletion_audit (
    audit_id    BIGSERIAL   PRIMARY KEY,
    feedback_id UUID        NOT NULL,
    tenant_id   TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    deleted_at  TIMESTAMPTZ NOT NULL,
    reason      TEXT        NOT NULL
);

-- Row-level security is active from the first migration. Until sessions carry
-- a tenant it matches one configured value, which is correct rather than
-- pointless: enabling it later would need a migration and an access review.
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'feedback'
          AND policyname = 'feedback_tenant_isolation'
    ) THEN
        CREATE POLICY feedback_tenant_isolation ON feedback
            USING (tenant_id = current_setting('ssf.tenant_id', TRUE));
    END IF;
END
$$;
