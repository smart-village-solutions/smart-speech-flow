"""The lifespan stops the WebSocket heartbeat the first socket started.

The heartbeat task is started by the first connection, not by the lifespan,
so it is not among the background tasks shutdown cancels. Driven on this
test's own event loop: TestClient closes its loop after the lifespan, which
cancels a leftover task and would hide one the lifespan left running.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.api_gateway.app import create_app, lifespan
from services.api_gateway.session_manager import ClientType
from tests.realtime_sessions import SNAPSHOT, TENANT


@pytest.fixture
def local_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "REDIS_URL",
        "SSF_DEPLOYMENT_ENV",
        "STUDIO_RUNTIME_CONFIGURATION_BASE_URL",
        "SSF_FEEDBACK_DATABASE_URL",
        "SSF_FEEDBACK_MAINTENANCE_DATABASE_URL",
        "SSF_FEEDBACK_READER_DATABASE_URL",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")


@pytest.mark.usefixtures("local_environment")
async def test_the_heartbeat_task_does_not_outlive_the_lifespan() -> None:
    app = create_app()

    async with lifespan(app):
        dependencies = app.state.dependencies
        session = await dependencies.session_manager.create_admin_session(TENANT, SNAPSHOT)
        socket = AsyncMock()
        await dependencies.websocket_manager.connect_websocket(
            socket, session.key, ClientType.ADMIN
        )
        heartbeat = dependencies.websocket_manager.heartbeat_task
        assert heartbeat is not None and not heartbeat.done()

    assert heartbeat.done()
