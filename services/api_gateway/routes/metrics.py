from typing import Annotated

from fastapi import Depends
from fastapi.responses import Response
from prometheus_client import CollectorRegistry, generate_latest

from services.api_gateway.dependencies import get_prometheus_registry

TEXT_PLAIN_MEDIA_TYPE = "text/plain"


def metrics(
    registry: Annotated[CollectorRegistry, Depends(get_prometheus_registry)],
):
    """Kombinierte Prometheus-Metriken für Gateway und WebSocket-Monitoring"""
    try:
        # The WebSocket series live on this registry too (app.websocket_metrics).
        return Response(generate_latest(registry), media_type=TEXT_PLAIN_MEDIA_TYPE)
    except Exception:
        # Absoluter Fallback
        return Response("# Fehler beim Generieren der Metriken\n", media_type=TEXT_PLAIN_MEDIA_TYPE)
