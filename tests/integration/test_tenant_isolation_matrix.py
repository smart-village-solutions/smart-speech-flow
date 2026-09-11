"""End-to-end proof of the tenant conversation boundary.

The matrix drives the production FastAPI router for every administrative
surface.  Lower-level scenarios cover deliberately malformed duplicate public
identifiers and deterministic timeout/ticket behavior that HTTP cannot create.
"""

from __future__ import annotations

import base64
import itertools
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import services.api_gateway.websocket as websocket_module
from services.api_gateway.app import app
from services.api_gateway.auth import optional_ssf_user, require_ssf_user
from services.api_gateway.realtime_ticket import (
    MemoryRealtimeTicketBackend,
    RealtimeTicketStore,
    realtime_ticket_store,
)
from services.api_gateway.session_manager import (
    ClientType,
    SessionManager,
    SessionMessage,
    SessionStatus,
    session_manager,
)
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.studio_runtime_client import RuntimeConfiguration
from services.api_gateway.studio_runtime_flow import (
    ValidatedRuntimeConfiguration,
    require_validated_runtime_configuration,
)
from services.api_gateway.tenant_context import (
    StudioTenantContext,
    require_studio_tenant_context,
)
from services.api_gateway.tenant_session import (
    RuntimeConfigurationSnapshot,
    TenantSessionKey,
)
from services.api_gateway.websocket import WebSocketManager
from services.api_gateway.websocket_polling_routes import (
    TenantPollingStore,
    polling_store,
)

REVISION = f"sha256:{'a' * 64}"
_CLIENT_ADDRESSES = itertools.count(1)
PROTECTED_OPERATIONS = (
    "current", "history", "status", "terminate", "messages_read",
    "messages_write", "audio_original", "audio_translated",
    "websocket", "polling", "monitoring",
)


def _configuration(tenant_id: str) -> RuntimeConfiguration:
    return RuntimeConfiguration.model_validate(
        {
            "contractVersion": "1.0",
            "configurationRevision": REVISION,
            "authorizationRevision": REVISION,
            "tenant": {
                "id": tenant_id,
                "displayName": tenant_id,
                "timeZone": "Europe/Berlin",
            },
            "branding": {"logo": None, "icon": None},
            "localization": {
                "defaultLocale": "de-DE",
                "locales": [
                    {
                        "locale": "de-DE",
                        "authenticatedHomeExplanationHtml": "<p>Admin</p>",
                        "guestExplanationHtml": "<p>Guest</p>",
                        "conversationContentStorageQuestionHtml": "<p>Store?</p>",
                    }
                ],
            },
            "conversationContentStorage": {"mode": "ask"},
        }
    )


@dataclass(frozen=True)
class MatrixResponse:
    status_code: int
    public_error: str | None


@dataclass(frozen=True)
class ConversationResult:
    session_id: str
    messages: list[str]


@dataclass(frozen=True)
class TenantResource:
    session_id: str
    message_id: str
    client_url: str


class TwoTenantSystem:
    """Small adapter around the real router with switchable signed identity."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.actor = "tenant-a"
        self.resources: dict[str, TenantResource] = {}
        self.polling_ids: dict[str, str] = {}

    def claims(self) -> dict[str, str]:
        return {
            "sub": f"operator-{self.actor}",
            "studio_tenant_id": self.actor,
            "ssf_authorization_revision": REVISION,
        }

    def context(self) -> StudioTenantContext:
        return StudioTenantContext(self.actor, REVISION)

    def runtime(self) -> ValidatedRuntimeConfiguration:
        return ValidatedRuntimeConfiguration(
            self.context(),
            _configuration(self.actor),
            f"matrix-{self.actor}",
        )

    def create_resource(self, tenant_id: str) -> None:
        self.actor = tenant_id
        created = self.client.post("/api/admin/session/create")
        assert created.status_code == 201
        body = created.json()
        session_id = body["session_id"]
        message_id = f"message-{tenant_id}"
        key = TenantSessionKey(tenant_id, session_id)
        session_manager.add_message(
            key,
            SessionMessage(
                id=message_id,
                sender=ClientType.ADMIN,
                original_text=f"{tenant_id}-message",
                translated_text=f"{tenant_id}-translated",
                audio_base64=base64.b64encode(b"RIFFtranslated").decode("ascii"),
                source_lang="de",
                target_lang="en",
                timestamp=datetime.now(timezone.utc),
            ),
        )
        self.resources[tenant_id] = TenantResource(
            session_id=session_id,
            message_id=message_id,
            client_url=body["client_url"],
        )

    def activate_admin_polling(self, tenant_id: str) -> None:
        self.actor = tenant_id
        resource = self.resources[tenant_id]
        ticket = self.client.post(
            f"/api/admin/session/{resource.session_id}/realtime-ticket",
            json={"transport": "polling"},
        ).json()["ticket"]
        activated = self.client.post(
            f"/api/admin/session/{resource.session_id}/polling/activate",
            json={"ticket": ticket},
        )
        assert activated.status_code == 200
        self.polling_ids[tenant_id] = activated.json()["polling_id"]

    def perform(self, operation: str, *, actor: str, resource: str) -> MatrixResponse:
        self.actor = actor
        target = self.resources[resource]
        if operation == "current":
            response = self.client.get(
                "/api/admin/session/current", params={"session_id": target.session_id}
            )
        elif operation == "history":
            response = self.client.get("/api/admin/session/history")
            body = response.json()
            visible_ids = {
                item["id"]
                for group in (body.get("sessions", []), body.get("active_sessions", []))
                for item in group
            }
            if target.session_id not in visible_ids:
                return MatrixResponse(404, "Session not found")
            return MatrixResponse(200, None)
        elif operation == "status":
            response = self.client.get(
                f"/api/admin/session/{target.session_id}/status"
            )
        elif operation == "terminate":
            response = self.client.delete(
                f"/api/admin/session/{target.session_id}/terminate"
            )
        elif operation == "messages_read":
            response = self.client.get(
                f"/api/admin/session/{target.session_id}/messages"
            )
        elif operation == "messages_write":
            response = self.client.post(
                f"/api/admin/session/{target.session_id}/message",
                json={"text": "cross-tenant", "source_lang": "de", "target_lang": "en"},
            )
        elif operation in {"audio_original", "audio_translated"}:
            variant = operation.removeprefix("audio_")
            response = self.client.get(
                f"/api/admin/session/{target.session_id}/audio/"
                f"{target.message_id}/{variant}.wav"
            )
        elif operation == "websocket":
            own = self.resources[actor]
            ticket = self.client.post(
                f"/api/admin/session/{own.session_id}/realtime-ticket",
                json={"transport": "websocket"},
            ).json()["ticket"]
            try:
                with self.client.websocket_connect(
                    f"/ws/admin/{target.session_id}?ticket={ticket}"
                ):
                    return MatrixResponse(200, None)
            except WebSocketDisconnect as error:
                return MatrixResponse(
                    404 if error.code == 4404 else error.code,
                    error.reason,
                )
        elif operation == "polling":
            response = self.client.get(
                f"/api/admin/session/{target.session_id}/polling/"
                f"{self.polling_ids[resource]}/status"
            )
        elif operation == "monitoring":
            response = self.client.get(
                f"/api/admin/session/{target.session_id}/realtime/connections"
            )
        else:  # pragma: no cover - protects additions to PROTECTED_OPERATIONS
            raise AssertionError(f"unknown matrix operation: {operation}")
        body = response.json()
        return MatrixResponse(response.status_code, body.get("detail"))

    def complete_conversation(self, tenant_id: str) -> ConversationResult:
        self.actor = tenant_id
        resource = self.resources[tenant_id]
        activated = self.client.post(
            "/api/customer/session/activate",
            json={"session_id": resource.session_id, "customer_language": "en"},
        )
        assert activated.status_code == 200
        response = self.client.get(
            f"/api/admin/session/{resource.session_id}/messages"
        )
        assert response.status_code == 200
        return ConversationResult(
            session_id=resource.session_id,
            messages=[item["original_text"] for item in response.json()["messages"]],
        )


@pytest.fixture
def two_tenant_system():
    original_overrides = app.dependency_overrides.copy()
    original_websocket_manager = websocket_module.websocket_manager
    session_manager.reset(clear_persistence=True)
    polling_store.clients.clear()
    realtime_ticket_store.redis.values.clear()
    websocket_module.websocket_manager = None
    address = next(_CLIENT_ADDRESSES)
    with TestClient(
        app,
        headers={"x-forwarded-for": f"192.0.2.{address}"},
    ) as client:
        system = TwoTenantSystem(client)
        app.dependency_overrides[require_ssf_user] = system.claims
        app.dependency_overrides[require_studio_tenant_context] = system.context
        app.dependency_overrides[require_validated_runtime_configuration] = system.runtime
        app.dependency_overrides[optional_ssf_user] = lambda: None
        system.create_resource("tenant-a")
        system.create_resource("tenant-b")
        system.activate_admin_polling("tenant-a")
        system.activate_admin_polling("tenant-b")
        yield system
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original_overrides)
    polling_store.clients.clear()
    realtime_ticket_store.redis.values.clear()
    websocket_module.websocket_manager = original_websocket_manager
    session_manager.reset(clear_persistence=True)


@pytest.mark.parametrize("operation", PROTECTED_OPERATIONS)
def test_tenant_a_cannot_access_tenant_b(two_tenant_system, operation):
    response = two_tenant_system.perform(
        operation, actor="tenant-a", resource="tenant-b"
    )
    assert response.status_code == 404
    assert response.public_error == "Session not found"


def test_positive_flows_remain_independent(two_tenant_system):
    a = two_tenant_system.complete_conversation("tenant-a")
    b = two_tenant_system.complete_conversation("tenant-b")
    assert a.session_id != b.session_id
    assert a.messages == ["tenant-a-message"]
    assert b.messages == ["tenant-b-message"]


def test_history_lists_only_the_authenticated_tenant(two_tenant_system) -> None:
    two_tenant_system.actor = "tenant-a"
    body = two_tenant_system.client.get("/api/admin/session/history").json()
    visible_ids = {
        item["id"]
        for group in (body["sessions"], body["active_sessions"])
        for item in group
    }

    assert two_tenant_system.resources["tenant-a"].session_id in visible_ids
    assert two_tenant_system.resources["tenant-b"].session_id not in visible_ids


def test_customer_join_link_resolves_only_through_the_public_capability(
    two_tenant_system,
) -> None:
    resource = two_tenant_system.resources["tenant-a"]
    assert resource.client_url.endswith(f"/join/{resource.session_id}")

    response = two_tenant_system.client.get(
        f"/api/customer/session/{resource.session_id}"
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == resource.session_id


def test_each_tenant_session_keeps_its_creation_time_runtime_snapshot(
    two_tenant_system,
) -> None:
    snapshots = {
        tenant_id: session_manager.get_session(
            TenantSessionKey(tenant_id, resource.session_id)
        ).runtime_configuration
        for tenant_id, resource in two_tenant_system.resources.items()
    }

    assert snapshots["tenant-a"].to_configuration().tenant.id == "tenant-a"
    assert snapshots["tenant-b"].to_configuration().tenant.id == "tenant-b"
    assert snapshots["tenant-a"] != snapshots["tenant-b"]


class Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **delta: int) -> None:
        self.current += timedelta(**delta)


@pytest.mark.asyncio
async def test_presence_grace_warning_and_absolute_lifetime_boundaries() -> None:
    clock = Clock()
    identifiers = iter(["GRACE001", "MAXIMUM1"])
    manager = SessionManager(
        store=MemoryTenantSessionStore(),
        clock=clock,
        session_id_factory=lambda: next(identifiers),
    )
    snapshot = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")
    grace = await manager.create_admin_session("tenant-a", snapshot)
    manager.admin_connected(grace.key)
    manager.admin_disconnected(grace.key)
    clock.advance(minutes=25)
    assert grace.warning_due(clock()) is True
    assert grace.timeout_due(clock()) is False
    clock.advance(minutes=5)
    assert grace.timeout_due(clock()) is True

    maximum = await manager.create_admin_session("tenant-b", snapshot)
    manager.admin_connected(maximum.key)
    clock.advance(hours=7, minutes=55)
    assert maximum.warning_due(clock()) is True
    assert maximum.timeout_due(clock()) is False
    clock.advance(minutes=5)
    assert maximum.timeout_due(clock()) is True


def test_admin_ticket_is_single_use_and_cannot_cross_same_id_tenants() -> None:
    backend = MemoryRealtimeTicketBackend()
    store = RealtimeTicketStore(backend)
    key_a = TenantSessionKey("tenant-a", "DUPL1234")
    key_b = TenantSessionKey("tenant-b", "DUPL1234")
    ticket = store.issue(key_a, "websocket")

    assert store.consume(ticket.ticket, key_b, "websocket") is False
    assert store.consume(ticket.ticket, key_a, "websocket") is False

    replay_ticket = store.issue(key_a, "websocket")
    assert store.consume(replay_ticket.ticket, key_a, "websocket") is True
    assert store.consume(replay_ticket.ticket, key_a, "websocket") is False


@pytest.mark.asyncio
async def test_malformed_same_id_registries_and_cleanup_remain_tenant_isolated() -> None:
    class Presence:
        def register_websocket_manager(self, manager):
            self.websocket_manager = manager

        async def add_websocket_connection(self, *_args):
            return None

        async def remove_websocket_connection(self, *_args):
            return None

        def get_session(self, _key):
            return type(
                "SessionState",
                (),
                {"status": SessionStatus.ACTIVE, "customer_language": None},
            )()

    key_a = TenantSessionKey("tenant-a", "DUPL1234")
    key_b = TenantSessionKey("tenant-b", "DUPL1234")
    sockets = WebSocketManager(Presence())
    sockets.start_heartbeat_system = AsyncMock()
    socket_a = AsyncMock()
    socket_b = AsyncMock()
    await sockets.connect_websocket(socket_a, key_a, ClientType.ADMIN)
    await sockets.connect_websocket(socket_b, key_b, ClientType.ADMIN)
    pollers = TenantPollingStore()
    poller_a = pollers.activate(key_a, ClientType.ADMIN)
    poller_b = pollers.activate(key_b, ClientType.ADMIN)

    await sockets.handle_session_termination(key_a)
    pollers.terminate(key_a, "manual_admin_termination")

    assert key_a not in sockets.session_connections
    assert key_b in sockets.session_connections
    assert poller_a.terminated is True
    assert poller_b.terminated is False
    assert not poller_b.messages
