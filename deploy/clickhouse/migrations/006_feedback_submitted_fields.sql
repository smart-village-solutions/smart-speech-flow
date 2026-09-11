-- Typed silver columns for the `feedback_submitted` event, plus its own gold
-- aggregate.
--
-- Task 2.1 and 2.2 of openspec/changes/add-feedback-persistence. This is the
-- analytical half of a feedback submission: ratings, NPS and two opaque
-- references. The improvement text that came with them lives in the
-- transactional feedback database and is not representable here -- there is no
-- allowlisted key for it and no column to hold it.
--
-- ALTER, never CREATE, for the same reason as 002 through 005: production's
-- volume already holds `quality_events`.
--
-- Numbered 006 so it runs after 005_tenant_reference. Both replace the
-- view's projection with MODIFY QUERY, so whichever runs last wins; this one
-- therefore restates tenant_ref too, and must stay last.

ALTER TABLE quality_events
    ADD COLUMN IF NOT EXISTS feedback_ref          String                 DEFAULT '',
    -- Ratings are 1-5 and NPS is 0-10; UInt8 is ample and 0 is the "absent"
    -- value for every non-feedback row, which is why the aggregate below
    -- filters on event_type rather than trusting the columns to be null.
    ADD COLUMN IF NOT EXISTS translation_quality   UInt8                  DEFAULT 0,
    ADD COLUMN IF NOT EXISTS performance           UInt8                  DEFAULT 0,
    ADD COLUMN IF NOT EXISTS usability             UInt8                  DEFAULT 0,
    ADD COLUMN IF NOT EXISTS net_promoter_score    UInt8                  DEFAULT 0,
    ADD COLUMN IF NOT EXISTS feedback_form_version LowCardinality(String) DEFAULT '';

-- MODIFY QUERY replaces the whole view, so every earlier field is re-stated
-- here. Dropping one would leave its column in place and silently fill it with
-- defaults -- no error, no missing column, just zeros where the data was.
-- `tests/test_quality_events_schema_contract.py` fails if the newest migration
-- projects fewer keys than the allowlist declares.
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
    LogAttributes['ssf.quality.feedback_form_version']          AS feedback_form_version
FROM otel_logs
WHERE toUUIDOrNull(LogAttributes['ssf.quality.event_id']) IS NOT NULL;


-- A dedicated aggregate rather than extending `quality_events_daily`: that
-- table is refinement-oriented, and a feedback row reaching it contributes a
-- zero to every latency state. Feedback KPIs also need denominators the
-- refinement table has no place for.
--
-- uniqExactState(event_id), not count(): the reconciler in #305 re-emits a
-- failed delivery under the same event id, and silver's ReplacingMergeTree
-- only collapses the duplicate at merge time. A plain counter would count the
-- retry permanently, and an aggregate cannot be un-counted.
--
-- KNOWN LIMITATION, verified against 26.3.17: the counts are exact under
-- retry, but the rating and NPS averages are not. avgState has no distinct-by
-- form, so a re-emitted submission contributes its values twice -- observed as
-- an NPS average of 7 across two distinct submissions of 9 and 3 after one
-- retry, where the true value is 6. The same caveat is recorded for the
-- latency states in 002, but it matters more here: #305 re-emits by design,
-- not only after a fault. Read rating averages from silver's 30 days when
-- exactness matters; the counts and rates above are safe to read from gold.
CREATE TABLE IF NOT EXISTS feedback_daily
(
    event_date               Date,
    deployment_env           LowCardinality(String),
    service_version          LowCardinality(String),
    feedback_form_version    LowCardinality(String),
    submissions              AggregateFunction(uniqExact, UUID),
    sessions                 AggregateFunction(uniqExact, String),
    translation_quality_avg  AggregateFunction(avg, UInt8),
    performance_avg          AggregateFunction(avg, UInt8),
    usability_avg            AggregateFunction(avg, UInt8),
    net_promoter_score_avg   AggregateFunction(avg, UInt8),
    -- uniqExact, not uniqExactIf: `-StateIf` filters before building the
    -- state, so the stored type is a plain uniqExact state. Declaring
    -- uniqExactIf would type-check on write and force every reader into
    -- uniqExactIfMerge, diverging from quality_events_daily for no gain.
    promoters                AggregateFunction(uniqExact, UUID),
    detractors               AggregateFunction(uniqExact, UUID)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (
    event_date, deployment_env, service_version, feedback_form_version
)
TTL event_date + INTERVAL 13 MONTH;

CREATE MATERIALIZED VIEW IF NOT EXISTS feedback_daily_mv
TO feedback_daily AS
SELECT
    toDate(emitted_at_utc)                  AS event_date,
    deployment_env,
    service_version,
    feedback_form_version,
    uniqExactState(event_id)                AS submissions,
    -- The denominator a response rate divides by is counted from
    -- session_lifecycle, not from here; this is the numerator's session set.
    uniqExactState(session_ref)             AS sessions,
    avgState(translation_quality)           AS translation_quality_avg,
    avgState(performance)                   AS performance_avg,
    avgState(usability)                     AS usability_avg,
    avgState(net_promoter_score)            AS net_promoter_score_avg,
    uniqExactStateIf(event_id, net_promoter_score >= 9) AS promoters,
    uniqExactStateIf(event_id, net_promoter_score <= 6) AS detractors
FROM quality_events
WHERE event_type = 'feedback_submitted'
GROUP BY event_date, deployment_env, service_version, feedback_form_version;
