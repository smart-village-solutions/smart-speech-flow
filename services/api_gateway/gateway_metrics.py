"""The Prometheus series one gateway app owns.

create_app() builds one set per app, so two apps in one process share no
registry and no series. Every lifespan of that app reuses it: a series
registers once per registry, while the components counting into it are
rebuilt per lifespan.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter

from .audio_storage import AudioStorageMetrics
from .pipeline_admission import PipelineAdmissionMetrics
from .refinement_metrics import RefinementMetrics
from .websocket_monitor import WebSocketMetrics
from .websocket_polling_routes import polling_dropped_counter


@dataclass(frozen=True, slots=True)
class GatewayMetrics:
    # The registry /metrics serves.
    registry: CollectorRegistry
    requests_total: Counter
    pipeline_admission: PipelineAdmissionMetrics
    refinement: RefinementMetrics
    websocket: WebSocketMetrics
    polling_messages_dropped: Counter
    audio_storage: AudioStorageMetrics

    @classmethod
    def build(cls) -> GatewayMetrics:
        registry = CollectorRegistry()
        requests_total = Counter(
            "gateway_requests_total", "Total API Gateway requests", registry=registry
        )
        # Exposed from the first scrape, so increase() has a prior sample.
        requests_total.inc(0)
        return cls(
            registry=registry,
            requests_total=requests_total,
            pipeline_admission=PipelineAdmissionMetrics(registry),
            refinement=RefinementMetrics(registry),
            websocket=WebSocketMetrics(registry),
            polling_messages_dropped=polling_dropped_counter(registry),
            audio_storage=AudioStorageMetrics(CollectorRegistry()),
        )
