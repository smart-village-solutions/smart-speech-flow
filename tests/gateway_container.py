"""A fresh dependency container on a gateway app that runs without its lifespan.

Not named ``test_*``, so pytest does not collect it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI

from services.api_gateway.dependencies import GatewayDependencies, build_gateway_dependencies
from services.api_gateway.translation_refiner import NoOpTranslationRefiner


@contextmanager
def installed_gateway_dependencies(app: FastAPI) -> Iterator[GatewayDependencies]:
    """Install what the lifespan would build, minus its startup I/O, and put it back.

    Refinement stays off, as it is in a process without LLM_REFINEMENT_* settings.
    The WebSocket monitor and the audio store count into the app's series, as
    the lifespan's do.
    """
    previous = getattr(app.state, "dependencies", None)
    dependencies = build_gateway_dependencies(
        prometheus_registry=app.state.prometheus_registry,
        websocket_metrics=app.state.gateway_metrics.websocket,
        audio_storage_metrics=app.state.gateway_metrics.audio_storage,
        translation_refiner=NoOpTranslationRefiner(),
    )
    app.state.dependencies = dependencies
    try:
        yield dependencies
    finally:
        app.state.dependencies = previous
