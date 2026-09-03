-- Bronze tier: the ClickHouse exporter's log table, owned by this repository.
--
-- The exporter can create this itself (`create_schema: true`), but only on its
-- first successful export. That made the silver view below un-appliable on a
-- fresh deploy, and left bronze's TTL impossible to retrofit afterwards
-- (ClickHouse fixes TTL at creation). So we create it up front and run the
-- exporter with `create_schema: false`.
--
-- CONSTRAINT: every column the exporter names in its INSERT must exist here, or
-- all exports fail. On a collector image bump, diff this against
-- `SHOW CREATE TABLE otel_logs` from a scratch stack with create_schema: true.
-- The exporter's own full-text indexes and k8s materialised columns are omitted
-- deliberately: Body is always empty here and SSF does not run on Kubernetes.

CREATE TABLE IF NOT EXISTS otel_logs
(
    Timestamp          DateTime64(9) CODEC(Delta(8), ZSTD(1)),
    TraceId            String CODEC(ZSTD(1)),
    SpanId             String CODEC(ZSTD(1)),
    TraceFlags         UInt8,
    SeverityText       LowCardinality(String) CODEC(ZSTD(1)),
    SeverityNumber     UInt8,
    ServiceName        LowCardinality(String) CODEC(ZSTD(1)),
    Body               String CODEC(ZSTD(1)),
    ResourceSchemaUrl  LowCardinality(String) CODEC(ZSTD(1)),
    ResourceAttributes Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    ScopeSchemaUrl     LowCardinality(String) CODEC(ZSTD(1)),
    ScopeName          String CODEC(ZSTD(1)),
    ScopeVersion       LowCardinality(String) CODEC(ZSTD(1)),
    ScopeAttributes    Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    LogAttributes      Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    EventName          String CODEC(ZSTD(1))
)
ENGINE = MergeTree
PARTITION BY toDate(Timestamp)
ORDER BY (toStartOfFiveMinutes(Timestamp), ServiceName, Timestamp)
TTL toDateTime(Timestamp) + INTERVAL 7 DAY
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;
