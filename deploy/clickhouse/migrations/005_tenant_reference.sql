-- Add the bounded pseudonymous tenant reference used to correlate tenant-
-- isolated lifecycle and message telemetry without storing a tenant ID.

ALTER TABLE quality_events
    ADD COLUMN IF NOT EXISTS tenant_ref String DEFAULT '';

-- MODIFY QUERY replaces the complete materialized-view projection. Keep every
-- field from 004 and add tenant_ref; the schema-contract tests guard this list.
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
    toUInt32OrZero(LogAttributes['ssf.quality.message_count'])  AS message_count
FROM otel_logs
WHERE toUUIDOrNull(LogAttributes['ssf.quality.event_id']) IS NOT NULL;
