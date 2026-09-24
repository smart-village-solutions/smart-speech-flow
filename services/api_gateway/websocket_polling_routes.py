"""Tenant- and role-bound HTTP polling fallback routes."""

from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
import time
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from prometheus_client import CollectorRegistry, Counter
from pydantic import BaseModel, Field

from .auth import optional_ssf_user
from .dependencies import (
    get_polling_store,
    get_realtime_ticket_store,
    get_session_manager,
    get_websocket_manager,
)
from .realtime_protocol import Frame, polled_envelope_frame, polled_session_terminated_frame
from .realtime_ticket import RealtimeTicketStore, RealtimeTicketUnavailable
from .session_access import require_admin_session_key, require_customer_session_key
from .session_manager import ClientType, TenantSessionManager
from .tenant_session import TenantSessionKey
from .websocket import WebSocketManager

router = APIRouter(tags=["realtime-polling"])
SessionManagerDependency = Annotated[TenantSessionManager, Depends(get_session_manager)]
logger = logging.getLogger(__name__)
MAX_POLLING_CLIENTS = 1000
MAX_POLLING_CLIENTS_PER_ROLE = 10
POLLING_IDLE_SECONDS = 120
POLLING_QUEUE_SIZE = 100
_POLLING_CLIENT_NOT_FOUND = "Polling client not found"


def polling_dropped_counter(registry: CollectorRegistry) -> Counter:
    """Registered once per registry; every app's polling store counts into it."""
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
    messages: deque[Frame] = field(default_factory=deque)
    event: asyncio.Event = field(default_factory=asyncio.Event)
    last_seen: float = field(default_factory=time.monotonic)
    terminated: bool = False


class TenantPollingStore:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        messages_dropped: Counter | None = None,
    ) -> None:
        self.clients: dict[str, PollingClient] = {}
        self.mutation_lock = asyncio.Lock()
        self.clock = clock
        self.messages_dropped = messages_dropped or polling_dropped_counter(CollectorRegistry())

    def activate(self, key: TenantSessionKey, client_type: ClientType) -> PollingClient:
        scoped_count = sum(
            client.key == key and client.client_type is client_type
            for client in self.clients.values()
        )
        if len(self.clients) >= MAX_POLLING_CLIENTS or scoped_count >= MAX_POLLING_CLIENTS_PER_ROLE:
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
            raise HTTPException(status_code=404, detail=_POLLING_CLIENT_NOT_FOUND)
        client.last_seen = self.clock()
        return client

    def remove(self, client: PollingClient) -> None:
        self.clients.pop(client.polling_id, None)

    def prune(self) -> list[PollingClient]:
        threshold = self.clock() - POLLING_IDLE_SECONDS
        expired = [client for client in self.clients.values() if client.last_seen < threshold]
        for client in expired:
            self.remove(client)
        return expired

    def _enqueue(self, client: PollingClient, message: Frame) -> bool:
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
        message: Frame,
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
        original_message: Frame,
        translated_message: Frame,
    ) -> tuple[int, int]:
        delivered = 0
        dropped = 0
        for recipient in self.clients.values():
            if recipient.key != key:
                continue
            message = (
                original_message if recipient.client_type is sender_type else translated_message
            )
            dropped += self._enqueue(recipient, message)
            delivered += 1
        return delivered, dropped

    def terminate(self, key: TenantSessionKey, reason: str) -> None:
        message = polled_session_terminated_frame(key.session_id, reason)
        for client in self.clients.values():
            if client.key == key:
                client.terminated = True
                self._enqueue(client, message)


def _activation_response(client: PollingClient) -> dict[str, object]:
    return {
        "polling_id": client.polling_id,
        "session_id": client.key.session_id,
        "client_type": client.client_type.value,
        "polling_interval": 5,
    }


@router.post(
    "/api/admin/session/{session_id}/polling/activate",
    responses={
        404: {"description": "Session not found or realtime ticket rejected"},
        503: {"description": "Realtime ticket service unavailable"},
    },
)
async def activate_admin_polling(
    session_id: str,
    request: AdminPollingActivation,
    key: Annotated[TenantSessionKey, Depends(require_admin_session_key)],
    sessions: SessionManagerDependency,
    polling_store: Annotated[TenantPollingStore, Depends(get_polling_store)],
    tickets: Annotated[RealtimeTicketStore, Depends(get_realtime_ticket_store)],
) -> dict[str, object]:
    async with polling_store.mutation_lock:
        try:
            accepted = tickets.consume(request.ticket, key, "polling")
        except RealtimeTicketUnavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Realtime ticket service unavailable",
            ) from None
        if not accepted:
            raise HTTPException(status_code=404, detail="Session not found")
        session = sessions.get_session(key)
        if session is None or session.status.value == "terminated":
            raise HTTPException(status_code=404, detail="Session not found")
        _release_stale_clients(polling_store, sessions)
        client = polling_store.activate(key, ClientType.ADMIN)
        sessions.admin_connected(key)
        return _activation_response(client)


@router.post("/api/customer/session/{session_id}/polling/activate")
async def activate_customer_polling(
    session_id: str,
    key: Annotated[TenantSessionKey, Depends(require_customer_session_key)],
    sessions: SessionManagerDependency,
    polling_store: Annotated[TenantPollingStore, Depends(get_polling_store)],
) -> dict[str, object]:
    async with polling_store.mutation_lock:
        _release_stale_clients(polling_store, sessions)
        client = polling_store.activate(key, ClientType.CUSTOMER)
        sessions.customer_connected(key)
        return _activation_response(client)


def _release_stale_clients(
    polling_store: TenantPollingStore, sessions: TenantSessionManager
) -> None:
    """Release the entire pruned batch without a cancellation point."""
    for client in polling_store.prune():
        _release_presence(client, sessions)


def _release_presence(client: PollingClient, sessions: TenantSessionManager) -> None:
    try:
        if client.client_type is ClientType.ADMIN:
            sessions.admin_disconnected(client.key)
        else:
            sessions.customer_disconnected(client.key)
    except KeyError:
        pass


def _active_client(
    polling_store: TenantPollingStore,
    polling_id: str,
    key: TenantSessionKey,
    client_type: ClientType,
    sessions: TenantSessionManager,
) -> PollingClient:
    """Release expired presence before accepting activity from a poller."""
    _release_stale_clients(polling_store, sessions)
    return polling_store.require(polling_id, key, client_type)


def require_customer_polling_key(
    session_id: str,
    polling_id: str,
    principal: Annotated[dict[str, Any] | None, Depends(optional_ssf_user)],
    polling_store: Annotated[TenantPollingStore, Depends(get_polling_store)],
) -> TenantSessionKey:
    client = polling_store.clients.get(polling_id)
    if (
        client is None
        or client.client_type is not ClientType.CUSTOMER
        or not hmac.compare_digest(client.key.session_id, session_id)
    ):
        raise HTTPException(status_code=404, detail=_POLLING_CLIENT_NOT_FOUND)
    if principal is not None:
        tenant_id = principal.get("studio_tenant_id")
        if not isinstance(tenant_id, str) or not hmac.compare_digest(
            tenant_id, client.key.tenant_id
        ):
            raise HTTPException(status_code=404, detail=_POLLING_CLIENT_NOT_FOUND)
    return client.key


def _poll(client: PollingClient, timeout: int) -> Coroutine[Any, Any, dict[str, object]]:
    """Keep the existing timeout keyword while returning an awaitable poll."""
    return _poll_messages(client, timeout)


async def _poll_messages(client: PollingClient, wait_seconds: int) -> dict[str, object]:
    if not client.messages and wait_seconds:
        client.event.clear()
        if not client.messages:
            try:
                async with asyncio.timeout(wait_seconds):
                    await client.event.wait()
            except TimeoutError:
                pass
    messages = list(client.messages)
    client.messages.clear()
    return {"messages": messages, "message_count": len(messages)}


async def _send(
    polling_store: TenantPollingStore,
    client: PollingClient,
    message: PollingMessage,
    manager: WebSocketManager,
) -> dict[str, object]:
    if client.terminated:
        raise HTTPException(status_code=404, detail=_POLLING_CLIENT_NOT_FOUND)
    envelope = polled_envelope_frame(
        message.type, message.content, client.key.session_id, client.client_type
    )
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
        raise HTTPException(status_code=404, detail=_POLLING_CLIENT_NOT_FOUND)
    return {
        "polling_id": client.polling_id,
        "session_id": client.key.session_id,
        "client_type": client.client_type.value,
        "queued_messages": len(client.messages),
    }


def _recover(client: PollingClient) -> dict[str, str]:
    if client.terminated:
        raise HTTPException(status_code=404, detail=_POLLING_CLIENT_NOT_FOUND)
    return {"status": "recovery_requested"}


def _disconnect(
    polling_store: TenantPollingStore, client: PollingClient, sessions: TenantSessionManager
) -> dict[str, str]:
    polling_store.remove(client)
    _release_presence(client, sessions)
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
        wait_seconds: Annotated[int, Query(alias="timeout", ge=0, le=60)] = 0,
        sessions: TenantSessionManager = Depends(get_session_manager),
        polling_store: TenantPollingStore = Depends(get_polling_store),
    ) -> dict[str, object]:
        async with polling_store.mutation_lock:
            client = _active_client(polling_store, polling_id, key, client_type, sessions)
        response = await _poll(client, wait_seconds)
        if client.terminated:
            async with polling_store.mutation_lock:
                if polling_store.clients.get(polling_id) is client:
                    _disconnect(polling_store, client, sessions)
        return response

    async def send(
        session_id: str,
        polling_id: str,
        message: PollingMessage,
        key: TenantSessionKey = Depends(key_dependency),
        manager: WebSocketManager = Depends(get_websocket_manager),
        sessions: TenantSessionManager = Depends(get_session_manager),
        polling_store: TenantPollingStore = Depends(get_polling_store),
    ) -> dict[str, str]:
        async with polling_store.mutation_lock:
            client = _active_client(polling_store, polling_id, key, client_type, sessions)
        # The response model stays dict[str, str], so an overflow's partial body is
        # still refused with 500; characterization.md leaves that to its own issue.
        return await _send(polling_store, client, message, manager)  # type: ignore[return-value]

    async def polling_status(
        session_id: str,
        polling_id: str,
        key: TenantSessionKey = Depends(key_dependency),
        sessions: TenantSessionManager = Depends(get_session_manager),
        polling_store: TenantPollingStore = Depends(get_polling_store),
    ) -> dict[str, object]:
        async with polling_store.mutation_lock:
            return _status(_active_client(polling_store, polling_id, key, client_type, sessions))

    async def recover(
        session_id: str,
        polling_id: str,
        key: TenantSessionKey = Depends(key_dependency),
        sessions: TenantSessionManager = Depends(get_session_manager),
        polling_store: TenantPollingStore = Depends(get_polling_store),
    ) -> dict[str, str]:
        async with polling_store.mutation_lock:
            return _recover(_active_client(polling_store, polling_id, key, client_type, sessions))

    async def disconnect(
        session_id: str,
        polling_id: str,
        key: TenantSessionKey = Depends(key_dependency),
        sessions: TenantSessionManager = Depends(get_session_manager),
        polling_store: TenantPollingStore = Depends(get_polling_store),
    ) -> dict[str, str]:
        async with polling_store.mutation_lock:
            client = _active_client(polling_store, polling_id, key, client_type, sessions)
            return _disconnect(polling_store, client, sessions)

    router.add_api_route(base, poll, methods=["GET"], name=f"{prefix}_poll")
    router.add_api_route(base + "/send", send, methods=["POST"], name=f"{prefix}_send")
    router.add_api_route(
        base + "/status",
        polling_status,
        methods=["GET"],
        name=f"{prefix}_polling_status",
    )
    router.add_api_route(base + "/recover", recover, methods=["POST"], name=f"{prefix}_recover")
    router.add_api_route(base, disconnect, methods=["DELETE"], name=f"{prefix}_disconnect")


_register_role_routes("admin", ClientType.ADMIN, require_admin_session_key)
_register_role_routes("customer", ClientType.CUSTOMER, require_customer_polling_key)
