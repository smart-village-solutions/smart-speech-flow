-- Type every event even when the exporter writes EventName empty.
--
-- The ClickHouse exporter detects the otel_logs columns once, at startup. A
-- collector that starts before ClickHouse fails that detection, logs it once,
-- and from then on leaves EventName out of every INSERT until it is restarted;
-- Docker's restart policy ignores depends_on, so any daemon restart can cause
-- it. On production that left every event untyped from 2026-10-23 until
-- 2026-11-20, and every dashboard panel filters on event_type.
--
-- The collector now copies the event name into the ssf.collector.event_name
-- log attribute, which lands in LogAttributes whatever the exporter detected.
-- EventName still wins when present, so this works in either deploy order.
--
-- MODIFY QUERY replaces the whole view, so 008's projection is restated in
-- full; only event_type changes.

ALTER TABLE quality_events_mv MODIFY QUERY
SELECT
    toUUIDOrZero(LogAttributes['ssf.quality.event_id'])         AS event_id,
    toUInt16OrZero(LogAttributes['ssf.quality.schema_version']) AS schema_version,
    toDateTime64(Timestamp, 3)                                  AS emitted_at_utc,
    if(EventName != '', EventName, LogAttributes['ssf.collector.event_name'])
                                                                AS event_type,
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
