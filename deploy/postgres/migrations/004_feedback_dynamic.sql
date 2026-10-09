-- Feedback answers by question id (Studio contract v2).
--
-- Studio now defines the feedback forms, so the four fixed rating columns and
-- the single improvement text give way to answers keyed by question id:
-- numbers in `numeric_answers`, all free text in one encrypted envelope in
-- `text_answers_ciphertext`, and the questions as validated in `form_snapshot`.
--
-- Existing rows are converted, not deleted. They answered the bundled form, so
-- they get its snapshot (tests/fixtures/feedback/bundled_form.json, checked by
-- tests/test_feedback_migration_sql.py). Their ciphertext moves unchanged: the
-- AAD binds only feedback_id and tenant_id, and `text_answers_legacy` tells
-- the read path that inside is the old single string, not a JSON object.
-- A v1 row's audience is `guest` with a session and `installation` without
-- one; staff feedback sent through the v1 body cannot be told apart.
--
-- Grants: 002 and 003 grant on the table, not on columns, so every role keeps
-- exactly its privileges over the new columns and nothing here re-grants.
-- `feedback_tenant_isolation` reads only `tenant_id`, which is unchanged.
--
-- Re-running is safe: 001 skips the existing table, the conversion runs only
-- while the old columns exist, and each constraint is added once. Everything
-- resolves through search_path, so the integration test can run it in a
-- scratch schema.
--
-- Rollback: an older gateway fails its feedback statements against this
-- schema and answers 503 on feedback; conversations are unaffected. Rows
-- written after this migration do not survive a schema rollback, which the
-- design accepts while production holds test data only.

ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS audience                TEXT,
    ADD COLUMN IF NOT EXISTS form_source             TEXT,
    -- Studio's revision of the form the answers were checked against; NULL
    -- for the bundled form.
    ADD COLUMN IF NOT EXISTS configuration_revision  TEXT,
    ADD COLUMN IF NOT EXISTS form_locale             TEXT,
    ADD COLUMN IF NOT EXISTS form_snapshot           JSONB,
    ADD COLUMN IF NOT EXISTS numeric_answers         JSONB,
    -- AES-GCM over a JSON object of every text answer; NULL when there is none.
    ADD COLUMN IF NOT EXISTS text_answers_ciphertext BYTEA,
    ADD COLUMN IF NOT EXISTS text_answers_legacy     BOOLEAN NOT NULL DEFAULT FALSE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'feedback'
          AND column_name = 'translation_quality'
    ) THEN
        -- Held to the end of this block: a gateway still writing the old
        -- columns must not insert between the conversion and the drop, or its
        -- row keeps NULL answers, loses its ratings, and SET NOT NULL below
        -- fails on this and every later run.
        LOCK TABLE feedback IN ACCESS EXCLUSIVE MODE;

        UPDATE feedback SET
            audience = CASE WHEN session_ref = repeat('0', 32)
                            THEN 'installation' ELSE 'guest' END,
            form_source = 'bundled',
            form_snapshot =
-- bundled-form-snapshot:begin
'[{"id": "translationQuality", "type": "rating", "required": true, "min": 1, "max": 5}, {"id": "performance", "type": "rating", "required": true, "min": 1, "max": 5}, {"id": "usability", "type": "rating", "required": true, "min": 1, "max": 5}, {"id": "recommendation", "type": "scale", "required": true, "min": 0, "max": 10}, {"id": "improvementIdeas", "type": "longText", "required": false, "maxLength": 4000}]'
-- bundled-form-snapshot:end
                ::jsonb,
            numeric_answers = jsonb_build_object(
                'translationQuality', translation_quality,
                'performance', performance,
                'usability', usability,
                'recommendation', net_promoter_score
            ),
            text_answers_ciphertext = improvements_ciphertext,
            text_answers_legacy = improvements_ciphertext IS NOT NULL
        WHERE numeric_answers IS NULL;

        -- Their CHECK constraints go with them.
        ALTER TABLE feedback
            DROP COLUMN IF EXISTS translation_quality,
            DROP COLUMN IF EXISTS performance,
            DROP COLUMN IF EXISTS usability,
            DROP COLUMN IF EXISTS net_promoter_score,
            DROP COLUMN IF EXISTS improvements_ciphertext;
    END IF;
END
$$;

ALTER TABLE feedback
    ALTER COLUMN audience SET NOT NULL,
    ALTER COLUMN form_source SET NOT NULL,
    ALTER COLUMN form_snapshot SET NOT NULL,
    ALTER COLUMN numeric_answers SET NOT NULL;

DO $$
DECLARE
    wanted CONSTANT TEXT[][] := ARRAY[
        ['feedback_audience_check',
         'audience IN (''guest'', ''staff'', ''installation'')'],
        ['feedback_form_source_check',
         'form_source IN (''studio'', ''bundled'')'],
        ['feedback_revision_check',
         '(form_source = ''bundled'') = (configuration_revision IS NULL)'],
        ['feedback_numeric_answers_check',
         'jsonb_typeof(numeric_answers) = ''object'''],
        ['feedback_form_snapshot_check',
         'jsonb_typeof(form_snapshot) = ''array'''],
        ['feedback_text_legacy_check',
         'NOT text_answers_legacy OR text_answers_ciphertext IS NOT NULL']
    ];
BEGIN
    FOR i IN 1 .. array_length(wanted, 1) LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'feedback'::regclass AND conname = wanted[i][1]
        ) THEN
            EXECUTE format(
                'ALTER TABLE feedback ADD CONSTRAINT %I CHECK (%s)', wanted[i][1], wanted[i][2]
            );
        END IF;
    END LOOP;
END
$$;
