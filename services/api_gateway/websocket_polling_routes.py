"""Tenant- and role-bound HTTP polling fallback routes."""

from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from prometheus_client import CollectorRegistry, Counter
from pydantic import BaseModel, Field

from .auth import optional_ssf_user
from .realtime_ticket import RealtimeTicketUnavailable, realtime_ticket_store
from .session_access import require_admin_session_key, require_customer_session_key
from .session_manager import ClientType
from .tenant_session import TenantSessionKey
from .websocket import WebSocketManager, get_websocket_manager

router = APIRouter(tags=["realtime-polling"])
logger = logging.getLogger(__name__)
MAX_POLLING_CLIENTS = 1000
MAX_POLLING_CLIENTS_PER_ROLE = 10
POLLING_IDLE_SECONDS = 120
POLLING_QUEUE_SIZE = 100


def _dropped_counter(registry: CollectorRegistry) -> Counter:
    return Counter(
        "tenant_polling_messages_dropped_total",
        "Polling messages discarded because a bounded recipient queue was full",
        ["client_type"],
        registry=registry,
    )


class AdminPollingActivation(BaseModel):
    ticket: str = Field(min_length=1, max_length=256)


class PollingMessage(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    content: dict[str, Any]


@dataclass
class PollingClient:
    polling_id: str
    key: TenantSessionKey
    client_type: ClientType
    messages: deque[dict[str, Any]] = field(default_factory=deque)
    event: asyncio.Event = field(default_factory=asyncio.Event)
    last_seen: float = field(default_factory=time.monotonic)
    terminated: bool = False


class TenantPollingStore:
    def __init__(self, clock=time.monotonic, registry=None) -> None:
        self.clients: dict[str, PollingClient] = {}
        self.clock = clock
        self.messages_dropped = _dropped_counter(registry or CollectorRegistry())

    def bind_metrics_registry(self, registry: CollectorRegistry) -> None:
        self.messages_dropped = _dropped_counter(registry)

    def activate(self, key: TenantSessionKey, client_type: ClientType) -> PollingClient:
        scoped_count = sum(
            client.key == key and client.client_type is client_type
            for client in self.clients.values()
        )
        if (
            len(self.clients) >= MAX_POLLING_CLIENTS
            or scoped_count >= MAX_POLLING_CLIENTS_PER_ROLE
        ):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Polling connection limit reached",
            )
        polling_id = secrets.token_urlsafe(24)
        client = PollingClient(
            polling_id,
            key,
            client_type,
            last_seen=self.clock(),
        )
        self.clients[polling_id] = client
        return client

    def require(
        self,
        polling_id: str,
        key: TenantSessionKey,
        client_type: ClientType,
    ) -> PollingClient:
        client = self.clients.get(polling_id)
        if (
            client is None
            or client.client_type is not client_type
            or not hmac.compare_digest(client.key.tenant_id, key.tenant_id)
            or not hmac.compare_digest(client.key.session_id, key.session_id)
        ):
            raise HTTPException(status_code=404, detail="Polling client not found")
        client.last_seen = self.clock()
        return client

    def remove(self, client: PollingClient) -> None:
        self.clients.pop(client.polling_id, None)

    def prune(self) -> list[PollingClient]:
        threshold = self.clock() - POLLING_IDLE_SECONDS
        expired = [
            client for client in self.clients.values() if client.last_seen < threshold
        ]
        for client in expired:
            self.remove(client)
        return expired

    def _enqueue(self, client: PollingClient, message: dict[str, Any]) -> bool:
        dropped = len(client.messages) >= POLLING_QUEUE_SIZE
        if dropped:
            client.messages.popleft()
            self.messages_dropped.labels(client_type=client.client_type.value).inc()
            logger.warning(
                "tenant_polling_queue_overflow client_type=%s",
                client.client_type.value,
            )
        client.messages.append(message)
        client.event.set()
        return dropped

    def broadcast(
        self,
        key: TenantSessionKey,
        message: dict[str, Any],
        *,
        exclude_polling_id: str | None = None,
    ) -> tuple[int, int]:
        delivered = 0
        dropped = 0
        for recipient in self.clients.values():
            if recipient.polling_id == exclude_polling_id or recipient.key != key:
                continue
            dropped += self._enqueue(recipient, message)
            delivered += 1
        return delivered, dropped

    def broadcast_differentiated(
        self,
        key: TenantSessionKey,
        sender_type: ClientType,
        original_message: dict[str, Any],
        translated_message: dict[str, Any],
    ) -> tuple[int, int]:
        delivered = 0
        dropped = 0
        for recipient in self.clients.values():
            if recipient.key != key:
                continue
            message = (
                original_message
                if recipient.client_type is sender_type
                else translated_message
            )
            dropped += self._enqueue(recipient, message)
            delivered += 1
        return delivered, dropped

    def terminate(self, key: TenantSessionKey, reason: str) -> None:
        message = {
            "type": "session_terminated",
            "session_id": key.session_id,
            "reason": reason,
            "reconnect_allowed": False,
        }
        for client in self.clients.values():
            if client.key == key:
                client.terminated = True
                self._enqueue(client, message)


polling_store = TenantPollingStore()


def _activation_response(client: PollingClient) -> dict[str, object]:
    return {
        "polling_id": client.polling_id,
        "session_id": client.key.session_id,
        "client_type": client.client_type.value,
        "polling_interval": 5,
    }


@router.post("/api/admin/session/{session_id}/polling/activate")
async def activate_admin_polling(
    session_id: str,
    request: AdminPollingActivation,
    key: Annotated[TenantSessionKey, Depends(require_admin_session_key)],
    manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
) -> dict[str, object]:
    try:
        accepted = realtime_ticket_store.consume(request.ticket, key, "polling")
    except RealtimeTicketUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Realtime ticket service unavailable",
        ) from None
    if not accepted:
        raise HTTPException(status_code=404, detail="Session not found")
    session = manager.session_manager.get_session(key)
    if session is None or session.status.value == "terminated":
        raise HTTPException(status_code=404, detail="Session not found")
    await _release_stale_clients(manager)
    client = polling_store.activate(key, ClientType.ADMIN)
    manager.session_manager.admin_connected(key)
    return _activation_response(client)


@router.post("/api/customer/session/{session_id}/polling/activate")
async def activate_customer_polling(
    session_id: str,
    key: Annotated[TenantSessionKey, Depends(require_customer_session_key)],
    manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
) -> dict[str, object]:
    await _release_stale_clients(manager)
    client = polling_store.activate(key, ClientType.CUSTOMER)
    manager.session_manager.customer_connected(key)
    return _activation_response(client)


async def _release_stale_clients(manager: WebSocketManager) -> None:
    for client in polling_store.prune():
        await _release_presence(client, manager)


async def _release_presence(client: PollingClient, manager: WebSocketManager) -> None:
    try:
        if client.client_type is ClientType.ADMIN:
            manager.session_manager.admin_disconnected(client.key)
        else:
            manager.session_manager.customer_disconnected(client.key)
    except KeyError:
        pass


def _client(
    polling_id: str,
    key: TenantSessionKey,
    client_type: ClientType,
) -> PollingClient:
    return polling_store.require(polling_id, key, client_type)


async def _active_client(
    polling_id: str,
    key: TenantSessionKey,
    client_type: ClientType,
    manager: WebSocketManager,
) -> PollingClient:
    """Release expired presence before accepting activity from a poller."""
    await _release_stale_clients(manager)
    return _client(polling_id, key, client_type)


def require_customer_polling_key(
    session_id: str,
    polling_id: str,
    principal: Annotated[dict[str, Any] | None, Depends(optional_ssf_user)],
) -> TenantSessionKey:
    client = polling_store.clients.get(polling_id)
    if (
        client is None
        or client.client_type is not ClientType.CUSTOMER
        or not hmac.compare_digest(client.key.session_id, session_id)
    ):
        raise HTTPException(status_code=404, detail="Polling client not found")
    if principal is not None:
        tenant_id = principal.get("studio_tenant_id")
        if not isinstance(tenant_id, str) or not hmac.compare_digest(
            tenant_id, client.key.tenant_id
        ):
            raise HTTPException(status_code=404, detail="Polling client not found")
    return client.key


async def _poll(client: PollingClient, timeout: int) -> dict[str, object]:
    if not client.messages and timeout:
        client.event.clear()
        if not client.messages:
            try:
                await asyncio.wait_for(client.event.wait(), timeout)
            except TimeoutError:
                pass
    messages = list(client.messages)
    client.messages.clear()
    return {"messages": messages, "message_count": len(messages)}


async def _send(
    client: PollingClient,
    message: PollingMessage,
    manager: WebSocketManager,
) -> dict[str, object]:
    if client.terminated:
        raise HTTPException(status_code=404, detail="Polling client not found")
    envelope = {
        "type": message.type,
        "content": message.content,
        "session_id": client.key.session_id,
        "client_type": client.client_type.value,
    }
    _delivered, dropped = polling_store.broadcast(
        client.key, envelope, exclude_polling_id=client.polling_id
    )
    await manager.broadcast_to_session(client.key, envelope, include_polling=False)
    if dropped:
        return {
            "status": "partial",
            "retryable": False,
            "messages_dropped": dropped,
        }
    return {"status": "success"}


def _status(client: PollingClient) -> dict[str, object]:
    if client.terminated:
        raise HTTPException(status_code=404, detail="Polling client not found")
    return {
        "polling_id": client.polling_id,
        "session_id": client.key.session_id,
        "client_type": client.client_type.value,
        "queued_messages": len(client.messages),
    }


def _recover(client: PollingClient) -> dict[str, str]:
    if client.terminated:
        raise HTTPException(status_code=404, detail="Polling client not found")
    return {"status": "recovery_requested"}


async def _disconnect(
    client: PollingClient, manager: WebSocketManager
) -> dict[str, str]:
    polling_store.remove(client)
    await _release_presence(client, manager)
    return {"status": "disconnected"}


def _register_role_routes(
    prefix: Literal["admin", "customer"],
    client_type: ClientType,
    key_dependency: Any,
) -> None:
    base = f"/api/{prefix}/session/{{session_id}}/polling/{{polling_id}}"

    async def poll(
        session_id: str,
        polling_id: str,
        key: TenantSessionKey = Depends(key_dependency),
        timeout: Annotated[int, Query(ge=0, le=60)] = 0,
        manager: WebSocketManager = Depends(get_websocket_manager),
    ) -> dict[str, object]:
        client = await _active_client(polling_id, key, client_type, manager)
        response = await _poll(client, timeout)
        if client.terminated:
            await _disconnect(client, manager)
        return response

    async def send(
        session_id: str,
        polling_id: str,
        message: PollingMessage,
        key: TenantSessionKey = Depends(key_dependency),
        manager: WebSocketManager = Depends(get_websocket_manager),
    ) -> dict[str, str]:
        client = await _active_client(polling_id, key, client_type, manager)
        return await _send(client, message, manager)

    async def polling_status(
        session_id: str,
        polling_id: str,
        key: TenantSessionKey = Depends(key_dependency),
        manager: WebSocketManager = Depends(get_websocket_manager),
    ) -> dict[str, object]:
        return _status(await _active_client(polling_id, key, client_type, manager))

    async def recover(
        session_id: str,
        polling_id: str,
        key: TenantSessionKey = Depends(key_dependency),
        manager: WebSocketManager = Depends(get_websocket_manager),
    ) -> dict[str, str]:
        return _recover(await _active_client(polling_id, key, client_type, manager))

    async def disconnect(
        session_id: str,
        polling_id: str,
        key: TenantSessionKey = Depends(key_dependency),
        manager: WebSocketManager = Depends(get_websocket_manager),
    ) -> dict[str, str]:
        client = await _active_client(polling_id, key, client_type, manager)
        return await _disconnect(client, manager)

    router.add_api_route(base, poll, methods=["GET"], name=f"{prefix}_poll")
    router.add_api_route(base + "/send", send, methods=["POST"], name=f"{prefix}_send")
    router.add_api_route(
        base + "/status",
        polling_status,
        methods=["GET"],
        name=f"{prefix}_polling_status",
    )
    router.add_api_route(
        base + "/recover", recover, methods=["POST"], name=f"{prefix}_recover"
    )
    router.add_api_route(
        base, disconnect, methods=["DELETE"], name=f"{prefix}_disconnect"
    )


_register_role_routes("admin", ClientType.ADMIN, require_admin_session_key)
_register_role_routes("customer", ClientType.CUSTOMER, require_customer_polling_key)
