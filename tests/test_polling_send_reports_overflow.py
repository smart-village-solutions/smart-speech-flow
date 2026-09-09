"""The send route must not report clean success over a dropped message.

send_message_to_polling_client returns False when a recipient's queue was full
and an older message was evicted to make room. The route discarded that result
and answered 200 "Message sent successfully" regardless, so the signal this
branch added stopped at the function boundary and never reached the caller --
the branch's own thesis, one layer up.

False does not mean the new message was rejected: it was queued, and a
*different, older* message was lost. So the response reports partial delivery,
and a caller must not retry.
"""

import json

from unittest.mock import AsyncMock, Mock

import pytest

from services.api_gateway import websocket_polling_routes as polling_routes


@pytest.fixture
def send_route(monkeypatch):
    """Two recipients besides the sender; the test decides what each returns."""
    outcomes: dict[str, bool] = {}

    websocket_manager = Mock()
    websocket_manager.broadcast_to_session = AsyncMock()

    monkeypatch.setattr(
        polling_routes.fallback_manager,
        "get_polling_client_status",
        lambda polling_id: {"session_id": "SESSION123"},
    )
    monkeypatch.setattr(
        polling_routes.fallback_manager,
        "get_session_fallback_status",
        lambda session_id: {
            "polling_clients": [
                {"polling_id": "sender"},
                {"polling_id": "receiver-a"},
                {"polling_id": "receiver-b"},
            ]
        },
    )
    monkeypatch.setattr(
        polling_routes.fallback_manager,
        "send_message_to_polling_client",
        lambda polling_id, message: outcomes.get(polling_id, True),
    )

    from services.api_gateway import websocket

    monkeypatch.setattr(websocket, "websocket_manager", websocket_manager)

    async def call():
        message = polling_routes.PollingMessage(
            type="message",
            content={"text": "hello"},
            session_id="SESSION123",
            client_type="customer",
            timestamp="2026-07-20T12:00:00+00:00",
        )
        response = await polling_routes.send_message_via_polling("sender", message)
        return response.status_code, json.loads(response.body)

    return outcomes, call


class TestCleanDelivery:
    async def test_every_recipient_queued_reports_success(self, send_route):
        _, call = send_route

        status_code, body = await call()

        assert status_code == 200
        assert body["status"] == "success"
        assert body["polling_recipients"] == 2
        assert body["polling_overflow_recipients"] == 0


class TestOverflowIsReported:
    async def test_a_dropped_message_is_not_reported_as_clean_success(
        self, send_route
    ):
        outcomes, call = send_route
        outcomes["receiver-b"] = False

        status_code, body = await call()

        assert body["status"] != "success", (
            "a recipient lost a queued message and the caller was told the "
            "send succeeded"
        )
        assert body["polling_overflow_recipients"] == 1
        assert body["polling_recipients"] == 2
        # The message was accepted and queued; only an older one was evicted.
        assert status_code == 200

    async def test_the_caller_is_told_not_to_retry(self, send_route):
        """Retrying duplicates the newest message and evicts one more."""
        outcomes, call = send_route
        outcomes["receiver-a"] = False

        _, body = await call()

        assert body["retryable"] is False

    async def test_every_overflowing_recipient_is_counted(self, send_route):
        outcomes, call = send_route
        outcomes["receiver-a"] = False
        outcomes["receiver-b"] = False

        _, body = await call()

        assert body["polling_overflow_recipients"] == 2
