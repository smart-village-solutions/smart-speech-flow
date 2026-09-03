-- Silver tier: typed, deduplicated quality events projected from bronze otel_logs.
-- See openspec/changes/add-clickhouse-quality-telemetry/design.md,
-- "The repository owns both medallion tiers".

CREATE TABLE IF NOT EXISTS quality_events
(
    event_id        UUID,
    schema_version  UInt16,
    emitted_at_utc  DateTime64(3, 'UTC'),
    event_type      LowCardinality(String),
    service_name    LowCardinality(String),
    service_version LowCardinality(String),
    deployment_env  LowCardinality(String),
    ingested_at_utc DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(ingested_at_utc)
PARTITION BY toYYYYMM(emitted_at_utc)
ORDER BY (event_type, event_id)
TTL toDateTime(emitted_at_utc) + INTERVAL 30 DAY;

-- Defensive casts are load-bearing: a materialized view that throws fails the
-- originating INSERT into otel_logs, which the collector then retries forever.
CREATE MATERIALIZED VIEW IF NOT EXISTS quality_events_mv TO quality_events AS
SELECT
    toUUIDOrZero(LogAttributes['ssf.quality.event_id'])         AS event_id,
    toUInt16OrZero(LogAttributes['ssf.quality.schema_version']) AS schema_version,
    toDateTime64(Timestamp, 3)                                  AS emitted_at_utc,
    EventName                                                   AS event_type,
    ServiceName                                                 AS service_name,
    ResourceAttributes['service.version']                       AS service_version,
    ResourceAttributes['deployment.environment.name']           AS deployment_env
FROM otel_logs
-- toUUIDOrNull in the filter, toUUIDOrZero in the projection: the filter keeps
-- unparseable ids out, and the cast that runs on surviving rows still cannot
-- throw. Without the filter every malformed id becomes the nil UUID, and
-- ReplacingMergeTree's (event_type, event_id) sort key then collapses all of
-- them onto a single row -- silent loss rather than inspectable garbage.
WHERE toUUIDOrNull(LogAttributes['ssf.quality.event_id']) IS NOT NULL;
