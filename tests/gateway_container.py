"""A fresh dependency container on a gateway app that runs without its lifespan.

Not named ``test_*``, so pytest does not collect it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI

from services.api_gateway.dependencies import GatewayDependencies, build_gateway_dependencies


@contextmanager
def installed_gateway_dependencies(app: FastAPI) -> Iterator[GatewayDependencies]:
    """Install what the lifespan would build, minus its startup I/O, and put it back."""
    previous = getattr(app.state, "dependencies", None)
    dependencies = build_gateway_dependencies(prometheus_registry=app.state.prometheus_registry)
    app.state.dependencies = dependencies
    try:
        yield dependencies
    finally:
        app.state.dependencies = previous
