-- Typed silver columns for the `session_lifecycle` event.
--
-- Task 1.2 and the lifecycle half of 2.3 of
-- openspec/changes/add-clickhouse-quality-telemetry. 003 typed the message
-- event; this migration types the session it belongs to, which is what turns
-- "messages" into "messages per session" and makes a session that carried no
-- message at all countable.
--
-- ALTER, never CREATE, for the same reason as 002 and 003: production's volume
-- already holds `quality_events`.

ALTER TABLE quality_events
    ADD COLUMN IF NOT EXISTS lifecycle_phase     LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS termination_reason  LowCardinality(String) DEFAULT '',
    -- A session lasts minutes to hours, so this outgrows the UInt32 used for
    -- stage latencies only past 49 days; UInt32 is still ample and keeps the
    -- column the same width as the other durations.
    ADD COLUMN IF NOT EXISTS session_duration_ms UInt32                 DEFAULT 0,
    ADD COLUMN IF NOT EXISTS message_count       UInt32                 DEFAULT 0;

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
    toUInt32OrZero(LogAttributes['ssf.quality.message_count'])  AS message_count
FROM otel_logs
WHERE toUUIDOrNull(LogAttributes['ssf.quality.event_id']) IS NOT NULL;

-- The gold tier is still not extended; see the note at the end of 003. A
-- `session_lifecycle` row reaching it contributes a correct daily count under
-- its own `event_type` and a zero to every latency state, and session
-- durations are read from silver's 30 days.
