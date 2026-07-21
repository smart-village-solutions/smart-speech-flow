"""Behavioral tests for the WebSocket long-polling fallback routes."""

import json
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from services.api_gateway import websocket_polling_routes as polling_routes


@pytest.mark.asyncio
async def test_poll_returns_queued_messages_without_entering_wait_loop(monkeypatch):
    queued_messages = [{"type": "message", "content": {"text": "ready"}}]
    poll = Mock(return_value=queued_messages)
    wait_for_messages = AsyncMock()
    monkeypatch.setattr(
        polling_routes.fallback_manager,
        "get_polling_client_status",
        lambda polling_id: {"polling_interval": 9},
    )
    monkeypatch.setattr(polling_routes.fallback_manager, "poll_messages", poll)
    monkeypatch.setattr(polling_routes, "_await_polled_messages", wait_for_messages)

    response = await polling_routes.poll_messages("poll-ready", wait_seconds=30)

    assert json.loads(response.body) == {
        "status": "success",
        "polling_id": "poll-ready",
        "messages": queued_messages,
        "message_count": 1,
        "has_more": False,
        "next_poll_interval": 9,
        "timestamp": json.loads(response.body)["timestamp"],
    }
    wait_for_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_rejects_unknown_client_before_accessing_queue(monkeypatch):
    poll = Mock()
    monkeypatch.setattr(
        polling_routes.fallback_manager, "get_polling_client_status", lambda polling_id: None
    )
    monkeypatch.setattr(polling_routes.fallback_manager, "poll_messages", poll)

    with pytest.raises(HTTPException, match="not found or expired") as error:
        await polling_routes.poll_messages("missing-client")

    assert error.value.status_code == 404
    poll.assert_not_called()


@pytest.mark.asyncio
async def test_polling_send_broadcasts_and_queues_only_other_clients(monkeypatch):
    websocket_manager = Mock()
    websocket_manager.broadcast_to_session = AsyncMock()
    queued = []
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
                {"polling_id": "receiver"},
            ]
        },
    )
    monkeypatch.setattr(
        polling_routes.fallback_manager,
        "send_message_to_polling_client",
        lambda polling_id, message: queued.append((polling_id, message)),
    )
    from services.api_gateway import websocket

    monkeypatch.setattr(websocket, "websocket_manager", websocket_manager)
    message = polling_routes.PollingMessage(
        type="message",
        content={"text": "hello"},
        session_id="SESSION123",
        client_type="customer",
        timestamp="2026-07-20T12:00:00+00:00",
    )

    response = await polling_routes.send_message_via_polling("sender", message)

    assert json.loads(response.body)["status"] == "success"
    websocket_manager.broadcast_to_session.assert_awaited_once()
    broadcast_message = websocket_manager.broadcast_to_session.await_args.kwargs["message"]
    assert broadcast_message["sender_id"] == "sender"
    assert broadcast_message["via_polling"] is True
    assert queued == [("receiver", broadcast_message)]
