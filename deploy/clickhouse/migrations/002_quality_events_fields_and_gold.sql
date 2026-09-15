-- Typed quality fields on silver, plus the gold daily-aggregate tier.
--
-- Tasks 1.2 and 1.3 of openspec/changes/add-clickhouse-quality-telemetry.
-- 001 shipped the seven envelope columns and fixed the 30-day raw TTL; this
-- migration adds the first real event's fields and the 13-month aggregate tier
-- alongside it. Both retention numbers are confirmed and deliberate: ClickHouse
-- fixes TTL at table-creation time, so the 13 MONTH below cannot be changed
-- later without an ALTER or a recreate.
--
-- ALTER, never CREATE, for the silver table: production's volume already holds
-- `quality_events`, and a CREATE TABLE IF NOT EXISTS with new columns would
-- silently do nothing there while succeeding on a fresh stack -- the two
-- environments would then disagree about the schema with no error anywhere.

ALTER TABLE quality_events
    ADD COLUMN IF NOT EXISTS refiner_role          LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS model_ref             LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS refinement_outcome    LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS refinement_latency_ms UInt32                 DEFAULT 0,
    ADD COLUMN IF NOT EXISTS refinement_changed    UInt8                  DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source_lang           LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS target_lang           LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS error_code            LowCardinality(String) DEFAULT '';

-- MODIFY QUERY rather than DROP + CREATE: dropping the view leaves a window in
-- which inserts into otel_logs are not projected into quality_events at all,
-- and those events are simply lost -- there is no replay.
--
-- The defensive casts are load-bearing for the same reason as in 001: a
-- materialized view that throws fails the originating INSERT into otel_logs,
-- which the collector then retries forever. Map access on an absent key yields
-- the type default rather than raising, so an event that does not carry the
-- refinement fields projects zeros and empty strings, not an error.
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
    LogAttributes['ssf.quality.error_code']                     AS error_code
FROM otel_logs
WHERE toUUIDOrNull(LogAttributes['ssf.quality.event_id']) IS NOT NULL;

-- Gold tier: one row per day per attribute combination, kept for 13 months so a
-- release or model change can be compared against the same month a year back.
--
-- Every count here is uniqExact over event_id, never count() or sum(). A retried
-- export inserts the bronze row a second time, and silver's ReplacingMergeTree
-- only collapses that at merge time -- so an unmerged duplicate inflates a
-- plain counter permanently, because an aggregate cannot be un-counted. This
-- was observed: a sumState-based `changed_events` reported 2 for a single
-- duplicated event while `events` correctly reported 1.
--
-- The latency states are the one place this fix does not reach: avg and the
-- quantile digest have no distinct-by form, so a duplicated delivery
-- contributes its value twice. The skew is bounded by the retry rate, which the
-- writer-health alerts make visible; it is accepted rather than hidden.
CREATE TABLE IF NOT EXISTS quality_events_daily
(
    event_date           Date,
    event_type           LowCardinality(String),
    deployment_env       LowCardinality(String),
    service_version      LowCardinality(String),
    refiner_role         LowCardinality(String),
    model_ref            LowCardinality(String),
    refinement_outcome   LowCardinality(String),
    error_code           LowCardinality(String),
    source_lang          LowCardinality(String),
    target_lang          LowCardinality(String),
    events               AggregateFunction(uniqExact, UUID),
    changed_events       AggregateFunction(uniqExact, UUID),
    latency_ms_avg       AggregateFunction(avg, UInt32),
    latency_ms_quantiles AggregateFunction(quantilesTDigest(0.5, 0.95, 0.99), UInt32)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (
    event_date, event_type, deployment_env, service_version,
    refiner_role, model_ref, refinement_outcome, error_code,
    source_lang, target_lang
)
TTL event_date + INTERVAL 13 MONTH;

CREATE MATERIALIZED VIEW IF NOT EXISTS quality_events_daily_mv
TO quality_events_daily AS
SELECT
    toDate(emitted_at_utc) AS event_date,
    event_type,
    deployment_env,
    service_version,
    refiner_role,
    model_ref,
    refinement_outcome,
    error_code,
    source_lang,
    target_lang,
    uniqExactState(event_id)                    AS events,
    uniqExactStateIf(event_id, refinement_changed = 1) AS changed_events,
    avgState(refinement_latency_ms)             AS latency_ms_avg,
    quantilesTDigestState(0.5, 0.95, 0.99)(refinement_latency_ms)
                                                AS latency_ms_quantiles
FROM quality_events
GROUP BY
    event_date, event_type, deployment_env, service_version,
    refiner_role, model_ref, refinement_outcome, error_code,
    source_lang, target_lang;
