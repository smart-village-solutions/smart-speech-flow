"""Behavioral tests for tenant-bound HTTP polling."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services.api_gateway.session_manager import ClientType
from services.api_gateway.tenant_session import TenantSessionKey
from services.api_gateway.websocket_polling_routes import (
    PollingMessage,
    TenantPollingStore,
    _poll,
    _send,
)


@pytest.mark.asyncio
async def test_poll_returns_queued_messages_without_waiting(monkeypatch):
    store = TenantPollingStore()
    client = store.activate(TenantSessionKey("tenant-a", "SESSION1"), ClientType.ADMIN)
    client.messages.append({"type": "message", "content": {"text": "ready"}})
    wait_for = AsyncMock()
    monkeypatch.setattr("services.api_gateway.websocket_polling_routes.asyncio.wait_for", wait_for)

    response = await _poll(client, timeout=30)

    assert response == {
        "messages": [{"type": "message", "content": {"text": "ready"}}],
        "message_count": 1,
    }
    wait_for.assert_not_awaited()


def test_polling_store_rejects_unknown_or_cross_tenant_client():
    store = TenantPollingStore()
    key = TenantSessionKey("tenant-a", "SESSION1")
    client = store.activate(key, ClientType.ADMIN)

    with pytest.raises(HTTPException) as missing:
        store.require("missing", key, ClientType.ADMIN)
    with pytest.raises(HTTPException) as cross_tenant:
        store.require(
            client.polling_id,
            TenantSessionKey("tenant-b", "SESSION1"),
            ClientType.ADMIN,
        )

    assert missing.value.status_code == 404
    assert cross_tenant.value.status_code == 404


@pytest.mark.asyncio
async def test_polling_send_queues_and_broadcasts_only_inside_tenant(monkeypatch):
    store = TenantPollingStore()
    key = TenantSessionKey("tenant-a", "SESSION1")
    sender = store.activate(key, ClientType.CUSTOMER)
    receiver = store.activate(key, ClientType.ADMIN)
    other_tenant = store.activate(TenantSessionKey("tenant-b", "SESSION1"), ClientType.ADMIN)
    manager = AsyncMock()
    monkeypatch.setattr("services.api_gateway.websocket_polling_routes.polling_store", store)

    response = await _send(
        sender,
        PollingMessage(type="message", content={"text": "hello"}),
        manager,
    )

    assert response == {"status": "success"}
    assert len(receiver.messages) == 1
    assert not other_tenant.messages
    manager.broadcast_to_session.assert_awaited_once_with(
        key,
        {
            "type": "message",
            "content": {"text": "hello"},
            "session_id": "SESSION1",
            "client_type": "customer",
        },
        include_polling=False,
    )


@pytest.mark.asyncio
async def test_empty_poll_waits_until_a_tenant_message_arrives():
    store = TenantPollingStore()
    key = TenantSessionKey("tenant-a", "SESSION1")
    client = store.activate(key, ClientType.CUSTOMER)

    poll = asyncio.create_task(_poll(client, timeout=1))
    await asyncio.sleep(0)
    store.broadcast(key, {"type": "ready"})

    assert await poll == {
        "messages": [{"type": "ready"}],
        "message_count": 1,
    }


def test_polling_store_prunes_idle_clients_and_caps_each_role(monkeypatch):
    now = [0.0]
    store = TenantPollingStore(clock=lambda: now[0])
    key = TenantSessionKey("tenant-a", "SESSION1")
    store.activate(key, ClientType.ADMIN)
    monkeypatch.setattr(
        "services.api_gateway.websocket_polling_routes.MAX_POLLING_CLIENTS_PER_ROLE",
        1,
    )

    with pytest.raises(HTTPException) as capped:
        store.activate(key, ClientType.ADMIN)
    assert capped.value.status_code == 429

    now[0] = 121.0
    assert len(store.prune()) == 1
    assert store.clients == {}
