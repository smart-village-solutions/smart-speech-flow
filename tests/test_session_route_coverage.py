"""Behavioral coverage for the tenant-scoped session-facing routes."""

from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.app import app
from services.api_gateway.routes import customer
from services.api_gateway.session_manager import (
    ClientType,
    Session,
    SessionManager,
    SessionMessage,
    SessionStatus,
)
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_session import (
    RuntimeConfigurationSnapshot,
    TenantSessionKey,
)

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


@pytest.fixture
def manager() -> SessionManager:
    return SessionManager(store=MemoryTenantSessionStore())


def test_session_round_trip_keeps_scope_message_and_timeout_state() -> None:
    created_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    message = SessionMessage(
        id="message-1",
        sender=ClientType.CUSTOMER,
        original_text="Hello",
        translated_text="Hallo",
        audio_base64=None,
        source_lang="en",
        target_lang="de",
        timestamp=created_at,
        pipeline_metadata={"steps": [{"name": "translation"}]},
    )
    session = Session(
        id="SESSION1",
        tenant_id="tenant-a",
        runtime_configuration=SNAPSHOT,
        customer_language="en",
        status=SessionStatus.ACTIVE,
        created_at=created_at,
        last_activity=created_at,
        messages=[message],
        timeout_warning_sent=True,
    )

    restored = Session.from_dict(session.to_dict(include_messages=True))

    assert restored.key == TenantSessionKey("tenant-a", "SESSION1")
    assert restored.messages[0].sender is ClientType.CUSTOMER
    assert restored.messages[0].pipeline_metadata == {"steps": [{"name": "translation"}]}
    assert restored.timeout_warning_sent is True


@pytest.mark.asyncio
async def test_manager_replaces_only_the_same_tenants_active_session(
    manager: SessionManager,
) -> None:
    first = await manager.create_admin_session("tenant-a", SNAPSHOT)
    other = await manager.create_admin_session("tenant-b", SNAPSHOT)
    second = await manager.create_admin_session("tenant-a", SNAPSHOT)

    assert manager.get_session(first.key).status is SessionStatus.TERMINATED
    assert manager.get_session(other.key).status is SessionStatus.PENDING
    assert manager.get_active_session(tenant_id="tenant-a")["id"] == second.id


def test_openapi_omits_generic_session_management_routes() -> None:
    paths = app.openapi()["paths"]

    assert "/api/session/create" not in paths
    assert "/api/session/{session_id}" not in paths
    assert "/api/sessions/active" not in paths
    assert "/api/admin/session/create" in paths
    assert "/api/customer/session/{session_id}" in paths


@pytest.mark.asyncio
async def test_customer_activation_uses_the_resolved_capability_key(
    manager: SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await manager.create_admin_session("tenant-a", SNAPSHOT)
    import services.api_gateway.session_access as session_access

    monkeypatch.setattr(customer, "session_manager", manager)
    monkeypatch.setattr(session_access, "session_manager", manager)
    request = customer.ActivateSessionRequest(
        session_id=session.id,
        customer_language="ar",
    )

    activation = await customer.activate_session(request, None)
    status = await customer.get_customer_session_status(session.id, session.key)

    assert activation.status == "active"
    assert activation.customer_language == "ar"
    assert status["is_active"] is True
    assert status["can_send_messages"] is True
    assert status["warning_at"]
    assert status["timeout_at"]
