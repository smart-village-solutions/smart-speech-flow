-- Typed silver columns for the `translation_message` event.
--
-- Task 1.2 and the storage half of 2.3 of
-- openspec/changes/add-clickhouse-quality-telemetry. 002 typed the refinement
-- attempt; this migration types the spine event -- one row per processed
-- message, the denominator every ratio in the dashboards divides by.
--
-- ALTER, never CREATE, for the same reason as 002: production's volume already
-- holds `quality_events`, and a CREATE TABLE IF NOT EXISTS carrying new columns
-- would silently do nothing there while succeeding on a fresh stack.

ALTER TABLE quality_events
    -- Not LowCardinality: a session reference is a keyed HMAC, so the column is
    -- as high-cardinality as the session count. LowCardinality on that costs
    -- more than it saves and degrades once the dictionary overflows.
    ADD COLUMN IF NOT EXISTS session_ref             String                 DEFAULT '',
    ADD COLUMN IF NOT EXISTS direction               LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS input_mode              LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS terminal_outcome        LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS failed_stage            LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS total_duration_ms       UInt32                 DEFAULT 0,
    ADD COLUMN IF NOT EXISTS asr_duration_ms         UInt32                 DEFAULT 0,
    ADD COLUMN IF NOT EXISTS translation_duration_ms UInt32                 DEFAULT 0,
    -- Distinct from `refinement_latency_ms`, which 002 added for the
    -- `refinement_attempt` event. That row measures one attempt, primary or
    -- shadow candidate; this one measures the refinement that ran inside a
    -- particular message. Sharing a column would merge two populations whose
    -- denominators differ -- a message has at most one refinement, a shadow
    -- comparison emits two attempts -- so an average over the union would be
    -- weighted by nothing meaningful.
    ADD COLUMN IF NOT EXISTS refinement_duration_ms  UInt32                 DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tts_duration_ms         UInt32                 DEFAULT 0;

-- MODIFY QUERY rather than DROP + CREATE: dropping the view leaves a window in
-- which inserts into otel_logs are not projected into quality_events at all,
-- and those events are simply lost -- there is no replay.
--
-- Every projection stays defensive. A materialized view that throws fails the
-- originating INSERT into otel_logs, which the collector then retries forever.
-- Map access on an absent key yields the type default rather than raising, so a
-- `refinement_attempt` row projects empty strings and zeros for the message
-- columns, and a `translation_message` row does the same for the refinement
-- ones.
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
                                                                AS tts_duration_ms
FROM otel_logs
WHERE toUUIDOrNull(LogAttributes['ssf.quality.event_id']) IS NOT NULL;

-- The gold tier is deliberately not extended here. Its dimensions and its
-- latency states are the refinement attempt's, so a `translation_message` row
-- reaching it contributes a correct daily count under its own `event_type` and
-- a zero to every latency state. Message latency is therefore read from silver,
-- which keeps 30 days -- long enough for every panel this change ships. Adding
-- message dimensions means rewriting the gold ORDER BY, which is a table
-- recreate, and it belongs with the aggregate-correctness work (task 4.4) that
-- has real volume to verify against.
