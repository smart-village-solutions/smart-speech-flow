-- Per-answer feedback events, an audience split, and a gold tier that only
-- averages the bundled ratings where a submission carries them.
--
-- Studio v2 PR 12 (openspec/changes/update-studio-runtime-contract-v2, task
-- 12.2). Since PR 12 every stored submission emits a `feedback_submitted`
-- header, and one `feedback_answer` event per answered numeric question. The
-- header carries the four bundled ratings only when the form asked those
-- questions the bundled way; free text is not representable in either event.
--
-- ALTER, never CREATE, on `quality_events`, for the same reason as 002-007:
-- production's volume already holds it. Every statement is safe to re-run,
-- because apply.sh re-runs every migration on every apply.

ALTER TABLE quality_events
    ADD COLUMN IF NOT EXISTS audience           LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS form_source        LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS feedback_locale    LowCardinality(String) DEFAULT '',
    -- Numeric answers only, so it equals the submission's feedback_answer
    -- events; text answers are never counted or emitted.
    ADD COLUMN IF NOT EXISTS answer_count       UInt8                  DEFAULT 0,
    -- Derived, not emitted: a header carries the rating keys exactly when it
    -- has legacy ratings. Rows written before this migration all did, and a
    -- default is computed on read for existing parts, so they read 1 here.
    ADD COLUMN IF NOT EXISTS has_legacy_ratings UInt8                  DEFAULT toUInt8(translation_quality > 0),
    ADD COLUMN IF NOT EXISTS question_id        LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS question_type      LowCardinality(String) DEFAULT '',
    -- Studio caps every range at 0-10; the emitter refuses anything over 255.
    ADD COLUMN IF NOT EXISTS answer_value       UInt8                  DEFAULT 0,
    ADD COLUMN IF NOT EXISTS answer_min         UInt8                  DEFAULT 0,
    ADD COLUMN IF NOT EXISTS answer_max         UInt8                  DEFAULT 0;

-- MODIFY QUERY replaces the whole view, so 006's projection is restated in
-- full. Dropping a line here would leave its column in place and silently fill
-- it with defaults. `tests/test_quality_events_schema_contract.py` fails if
-- this, the newest redefinition, projects fewer keys than the allowlist.
ALTER TABLE quality_events_mv MODIFY QUERY
SELECT
    toUUIDOrZero(LogAttributes['ssf.quality.event_id'])         AS event_id,
    toUInt16OrZero(LogAttributes['ssf.quality.schema_version']) AS schema_version,
    toDateTime64(Timestamp, 3)                                  AS emitted_at_utc,
    EventName                                                   AS event_type,
    ServiceName                                                 AS service_name,
    ResourceAttributes['service.version']                       AS service_version,
    ResourceAttributes['deployment.environment.name']           AS deployment_env,
    LogAttributes['ssf.quality.refiner_role']                   AS refiner_role,
    LogAttributes['ssf.quality.model_ref']                      AS model_ref,
    LogAttributes['ssf.quality.refinement_outcome']             AS refinement_outcome,
    toUInt32OrZero(LogAttributes['ssf.quality.refinement_latency_ms'])
                                                                AS refinement_latency_ms,
    toUInt8(LogAttributes['ssf.quality.refinement_changed'] = 'true')
                                                                AS refinement_changed,
    LogAttributes['ssf.quality.source_lang']                    AS source_lang,
    LogAttributes['ssf.quality.target_lang']                    AS target_lang,
    LogAttributes['ssf.quality.error_code']                     AS error_code,
    LogAttributes['ssf.quality.session_ref']                    AS session_ref,
    LogAttributes['ssf.quality.tenant_ref']                     AS tenant_ref,
    LogAttributes['ssf.quality.direction']                      AS direction,
    LogAttributes['ssf.quality.input_mode']                     AS input_mode,
    LogAttributes['ssf.quality.terminal_outcome']               AS terminal_outcome,
    LogAttributes['ssf.quality.failed_stage']                   AS failed_stage,
    toUInt32OrZero(LogAttributes['ssf.quality.total_duration_ms'])
                                                                AS total_duration_ms,
    toUInt32OrZero(LogAttributes['ssf.quality.asr_duration_ms'])
                                                                AS asr_duration_ms,
    toUInt32OrZero(LogAttributes['ssf.quality.translation_duration_ms'])
                                                                AS translation_duration_ms,
    toUInt32OrZero(LogAttributes['ssf.quality.refinement_duration_ms'])
                                                                AS refinement_duration_ms,
    toUInt32OrZero(LogAttributes['ssf.quality.tts_duration_ms'])
                                                                AS tts_duration_ms,
    LogAttributes['ssf.quality.lifecycle_phase']                AS lifecycle_phase,
    LogAttributes['ssf.quality.termination_reason']             AS termination_reason,
    toUInt32OrZero(LogAttributes['ssf.quality.session_duration_ms'])
                                                                AS session_duration_ms,
    toUInt32OrZero(LogAttributes['ssf.quality.message_count'])  AS message_count,
    LogAttributes['ssf.quality.feedback_ref']                   AS feedback_ref,
    toUInt8OrZero(LogAttributes['ssf.quality.translation_quality'])
                                                                AS translation_quality,
    toUInt8OrZero(LogAttributes['ssf.quality.performance'])     AS performance,
    toUInt8OrZero(LogAttributes['ssf.quality.usability'])       AS usability,
    toUInt8OrZero(LogAttributes['ssf.quality.net_promoter_score'])
                                                                AS net_promoter_score,
    LogAttributes['ssf.quality.feedback_form_version']          AS feedback_form_version,
    LogAttributes['ssf.quality.audience']                       AS audience,
    LogAttributes['ssf.quality.form_source']                    AS form_source,
    LogAttributes['ssf.quality.feedback_locale']                AS feedback_locale,
    toUInt8OrZero(LogAttributes['ssf.quality.answer_count'])    AS answer_count,
    toUInt8(LogAttributes['ssf.quality.translation_quality'] != '') AS has_legacy_ratings,
    LogAttributes['ssf.quality.question_id']                    AS question_id,
    LogAttributes['ssf.quality.question_type']                  AS question_type,
    toUInt8OrZero(LogAttributes['ssf.quality.answer_value'])    AS answer_value,
    toUInt8OrZero(LogAttributes['ssf.quality.answer_min'])      AS answer_min,
    toUInt8OrZero(LogAttributes['ssf.quality.answer_max'])      AS answer_max
FROM otel_logs
WHERE toUUIDOrNull(LogAttributes['ssf.quality.event_id']) IS NOT NULL;


-- A new gold table rather than a wider key on `feedback_daily`. Verified
-- against 26.3.17: after `ALTER TABLE feedback_daily ... MODIFY ORDER BY` with
-- two more columns, the next apply.sh run re-runs 007, whose MODIFY ORDER BY
-- silently shrinks the key back -- the AggregatingMergeTree would then merge
-- staff rows into citizen rows -- and the following re-run of the extension
-- fails ("Existing column audience is used in the expression that was added to
-- the sorting key"), stopping apply.sh for good. A table no older migration
-- names has neither problem.
--
-- `audience` keeps staff feedback out of citizen aggregates; `form_source`
-- separates Studio forms from the bundled one. Both are '' for rows copied
-- from `feedback_daily` below and for headers from a pre-PR-12 gateway.
CREATE TABLE IF NOT EXISTS feedback_daily_v2
(
    event_date               Date,
    deployment_env           LowCardinality(String),
    service_version          LowCardinality(String),
    feedback_form_version    LowCardinality(String),
    tenant_ref               LowCardinality(String),
    audience                 LowCardinality(String),
    form_source              LowCardinality(String),
    submissions              AggregateFunction(uniqExact, UUID),
    -- The NPS denominator: only submissions that answered the bundled
    -- recommendation question can be promoters or detractors.
    rated_submissions        AggregateFunction(uniqExact, UUID),
    sessions                 AggregateFunction(uniqExact, String),
    translation_quality_avg  AggregateFunction(avg, UInt8),
    performance_avg          AggregateFunction(avg, UInt8),
    usability_avg            AggregateFunction(avg, UInt8),
    net_promoter_score_avg   AggregateFunction(avg, UInt8),
    promoters                AggregateFunction(uniqExact, UUID),
    detractors               AggregateFunction(uniqExact, UUID)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (
    event_date, deployment_env, service_version, feedback_form_version,
    tenant_ref, audience, form_source
)
TTL event_date + INTERVAL 13 MONTH;

-- `-StateIf` stores a plain state (verified: avgStateIf over UInt8 is
-- AggregateFunction(avg, UInt8)), so filtering changes no column type. The
-- averages keep 006's caveat: avgState has no distinct-by form, so a
-- re-emitted submission counts twice there. Counts and NPS are exact.
CREATE MATERIALIZED VIEW IF NOT EXISTS feedback_daily_v2_mv
TO feedback_daily_v2 AS
SELECT
    toDate(emitted_at_utc)                  AS event_date,
    deployment_env,
    service_version,
    feedback_form_version,
    tenant_ref,
    audience,
    form_source,
    uniqExactState(event_id)                AS submissions,
    uniqExactStateIf(event_id, has_legacy_ratings = 1) AS rated_submissions,
    uniqExactState(session_ref)             AS sessions,
    avgStateIf(translation_quality, has_legacy_ratings = 1) AS translation_quality_avg,
    avgStateIf(performance, has_legacy_ratings = 1)         AS performance_avg,
    avgStateIf(usability, has_legacy_ratings = 1)           AS usability_avg,
    avgStateIf(net_promoter_score, has_legacy_ratings = 1)  AS net_promoter_score_avg,
    uniqExactStateIf(event_id, has_legacy_ratings = 1 AND net_promoter_score >= 9) AS promoters,
    uniqExactStateIf(event_id, has_legacy_ratings = 1 AND net_promoter_score <= 6) AS detractors
FROM quality_events
WHERE event_type = 'feedback_submitted'
GROUP BY event_date, deployment_env, service_version, feedback_form_version, tenant_ref,
    audience, form_source;

-- Retire the old aggregate. Created after v2's view, so no header is missed
-- in between. One arriving in that sub-second gap reaches both tables: the
-- copy below merges it twice, which the uniqExact counts absorb and its
-- averages do not (the caveat every gold average already carries).
--
-- `feedback_daily` itself stays, read-only history that nothing reads after
-- the copy. It cannot be dropped for good while apply.sh re-runs 006, which
-- re-creates the table and this view on every apply; 007 then modifies the
-- view and this statement drops it again. A header in that sub-second window
-- reaches both tables; the marker below keeps it from being copied twice, and
-- nothing reads the retired one. Until apply.sh stops re-running applied
-- migrations (PR 14), the same window briefly projects silver without 008's
-- columns, which is why the per-question panels skip an empty question id.
DROP VIEW IF EXISTS feedback_daily_mv;

-- Copy the old aggregate into v2, once. Every row in it predates PR 12, when
-- only submissions with the four bundled ratings emitted a header, so its
-- submissions are its rated submissions and its averages need no filter.
-- That holds only if this migration runs BEFORE a PR 12 gateway emits: such a
-- gateway sends headers without ratings, the old view stores them as zeros,
-- and the copy would keep them as rated detractors for good. Deploy order is
-- 008, then the collector, then the gateway.
--
-- The marker makes a re-run copy nothing: a second copy would leave the
-- counts exact (uniqExact merges sets) but double every average's weight.
-- The copy and the marker are two statements, so an apply.sh failing between
-- them copies again on its next run; runbook step 11 checks the marker.
CREATE TABLE IF NOT EXISTS feedback_daily_v2_backfill
(
    copied_at DateTime
)
ENGINE = TinyLog;

INSERT INTO feedback_daily_v2
SELECT
    event_date,
    deployment_env,
    service_version,
    feedback_form_version,
    tenant_ref,
    ''                       AS audience,
    ''                       AS form_source,
    submissions,
    submissions              AS rated_submissions,
    sessions,
    translation_quality_avg,
    performance_avg,
    usability_avg,
    net_promoter_score_avg,
    promoters,
    detractors
FROM feedback_daily
WHERE (SELECT count() FROM feedback_daily_v2_backfill) = 0;

INSERT INTO feedback_daily_v2_backfill
SELECT now()
WHERE (SELECT count() FROM feedback_daily_v2_backfill) = 0;


-- One row per answered numeric question. The range is part of the key: a
-- question id asked on 1-5 in one revision and 0-10 in the next must not be
-- averaged together. value_avg carries 006's re-emission caveat; `answers`
-- is exact.
CREATE TABLE IF NOT EXISTS feedback_answer_daily
(
    event_date      Date,
    deployment_env  LowCardinality(String),
    tenant_ref      LowCardinality(String),
    audience        LowCardinality(String),
    question_id     LowCardinality(String),
    question_type   LowCardinality(String),
    answer_min      UInt8,
    answer_max      UInt8,
    answers         AggregateFunction(uniqExact, UUID),
    value_avg       AggregateFunction(avg, UInt8)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (
    event_date, deployment_env, tenant_ref, audience,
    question_id, question_type, answer_min, answer_max
)
TTL event_date + INTERVAL 13 MONTH;

CREATE MATERIALIZED VIEW IF NOT EXISTS feedback_answer_daily_mv
TO feedback_answer_daily AS
SELECT
    toDate(emitted_at_utc)       AS event_date,
    deployment_env,
    tenant_ref,
    audience,
    question_id,
    question_type,
    answer_min,
    answer_max,
    uniqExactState(event_id)     AS answers,
    avgState(answer_value)       AS value_avg
FROM quality_events
WHERE event_type = 'feedback_answer'
GROUP BY event_date, deployment_env, tenant_ref, audience,
    question_id, question_type, answer_min, answer_max;
