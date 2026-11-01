"""Behavioral tests for tenant-bound HTTP polling."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services.api_gateway.session_models import ClientType
from services.api_gateway.tenant_session import TenantSessionKey
from services.api_gateway.websocket_polling_routes import (
    POLLING_QUEUE_SIZE,
    TenantPollingStore,
    _poll,
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
    other_tenant_key = TenantSessionKey("tenant-b", "SESSION1")
    with pytest.raises(HTTPException) as cross_tenant:
        store.require(
            client.polling_id,
            other_tenant_key,
            ClientType.ADMIN,
        )

    assert missing.value.status_code == 404
    assert cross_tenant.value.status_code == 404


def test_a_broadcast_queues_only_inside_the_tenant():
    store = TenantPollingStore()
    key = TenantSessionKey("tenant-a", "SESSION1")
    receiver = store.activate(key, ClientType.ADMIN)
    other_tenant = store.activate(TenantSessionKey("tenant-b", "SESSION1"), ClientType.ADMIN)

    delivered, dropped = store.broadcast(key, {"type": "ready"})

    assert (delivered, dropped) == (1, 0)
    assert list(receiver.messages) == [{"type": "ready"}]
    assert not other_tenant.messages


def test_an_overflowing_queue_keeps_the_newest_frame():
    store = TenantPollingStore()
    key = TenantSessionKey("tenant-a", "SESSION1")
    receiver = store.activate(key, ClientType.ADMIN)
    for index in range(POLLING_QUEUE_SIZE):
        receiver.messages.append({"type": "old", "index": index})

    _delivered, dropped = store.broadcast(key, {"type": "newest"})

    assert receiver.messages[-1] == {"type": "newest"}
    assert len(receiver.messages) == POLLING_QUEUE_SIZE
    assert dropped == 1


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
