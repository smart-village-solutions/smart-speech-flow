"""Regression tests for backend-core Sonar remediation."""

import importlib
import json
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI


class _Counter:
    def labels(self, **_labels):
        return self

    def inc(self):
        pass


def test_no_connection_broadcast_log_redacts_session_id(caplog):
    websocket = importlib.import_module("services.api_gateway.websocket")
    monitor = type("Monitor", (), {"broadcast_failure_total": _Counter()})()
    session_id = "session-secret-123"

    websocket.WebSocketManager._build_no_connection_broadcast_result(
        None,
        monitor,
        session_id,
        websocket.ClientType.ADMIN,
    )

    assert "Broadcast attempted without active connections" in caplog.text
    assert session_id not in caplog.text


@pytest.mark.asyncio
async def test_polling_timeout_keeps_public_openapi_name(monkeypatch):
    polling_routes = importlib.import_module(
        "services.api_gateway.websocket_polling_routes"
    )
    monkeypatch.setattr(
        polling_routes.fallback_manager,
        "get_polling_client_status",
        lambda _polling_id: {"polling_interval": 7},
    )
    monkeypatch.setattr(
        polling_routes.fallback_manager,
        "poll_messages",
        Mock(side_effect=[[], [{"type": "message"}]]),
    )
    monkeypatch.setattr(polling_routes.asyncio, "sleep", AsyncMock())

    response = await polling_routes.poll_messages("poll-1", wait_seconds=1)
    payload = json.loads(response.body)
    assert payload["messages"] == [{"type": "message"}]

    app = FastAPI()
    app.include_router(polling_routes.router)
    parameters = app.openapi()["paths"]["/api/websocket/polling/poll/{polling_id}"][
        "get"
    ]["parameters"]
    timeout_parameter = next(
        parameter
        for parameter in parameters
        if parameter["in"] == "query" and parameter["name"] == "timeout"
    )

    assert timeout_parameter["schema"]["minimum"] == 1
    assert timeout_parameter["schema"]["maximum"] == 60
