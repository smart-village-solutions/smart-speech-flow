"""OTLP/HTTP adapter. The only module in the gateway importing the OTel SDK.

HTTP rather than gRPC deliberately: the gRPC exporter pulls in grpcio, a
heavyweight wheel and a recurring image-build problem.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from .quality_telemetry import enforce_allowlist

_NANOS_PER_SECOND = 1_000_000_000


class OtlpQualityExporter:
    """Ships one event over OTLP and owns the SDK objects behind it.

    It owns the provider because nothing else can shut it down: a
    `BatchLogRecordProcessor` runs a worker thread, so a provider abandoned at
    lifespan teardown leaks that thread and drops whatever it still held.
    """

    def __init__(self, provider: LoggerProvider) -> None:
        self._provider = provider
        self._logger = provider.get_logger("ssf.quality")

    def __call__(
        self,
        event_name: str,
        attributes: Mapping[str, str],
        emitted_at_utc: datetime,
    ) -> None:
        # Last checkpoint before the wire, so no caller can widen what ships.
        enforce_allowlist(attributes)
        # emit() takes kwargs directly; no LogRecord is constructed. event_name is
        # a top-level OTLP field and reaches the typed EventName column. Without
        # an explicit timestamp the SDK sends none and the column silently
        # becomes the collector's observation time instead of the event's.
        self._logger.emit(
            body="",
            event_name=event_name,
            attributes=dict(attributes),
            timestamp=int(emitted_at_utc.timestamp() * _NANOS_PER_SECOND),
        )

    def force_flush(self, timeout_millis: int = 5_000) -> bool:
        return self._provider.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self._provider.shutdown()


def build_otlp_exporter(
    *,
    endpoint: str,
    service_name: str,
    service_version: str,
    deployment_environment: str,
) -> OtlpQualityExporter:
    """Build the exporter carrying exactly the three declared resource fields.

    `Resource(attributes=...)` rather than `Resource.create(...)`: the latter
    merges OTEL_RESOURCE_ATTRIBUTES and OTEL_SERVICE_NAME from the environment
    and adds telemetry.sdk.* plus a per-process service.instance.id. The
    collector's allowlist filters log attributes, not resource attributes, so
    anything Resource.create adds would reach ClickHouse unfiltered.
    """
    provider = LoggerProvider(
        resource=Resource(
            attributes={
                "service.name": service_name,
                "service.version": service_version,
                "deployment.environment.name": deployment_environment,
            }
        )
    )
    provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint))
    )
    return OtlpQualityExporter(provider)
