"""Tenant sessions for the suites that drive WebSocketManager directly.

Every socket a gateway app registers belongs to a tenant session, so these
suites build a TenantSessionManager and key their sessions by TenantSessionKey.
Not named ``test_*``, so pytest does not collect it.
"""

from __future__ import annotations

from typing import Any

from services.api_gateway.audio_storage import AudioStore
from services.api_gateway.session_manager import Session, SessionStatus, TenantSessionManager
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey

TENANT = "tenant-a"
_REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(_REVISION, _REVISION, "{}")


def tenant_session_manager() -> TenantSessionManager:
    return TenantSessionManager(
        store=MemoryTenantSessionStore(), audio_store=AudioStore.from_environment()
    )


def open_session(
    sessions: TenantSessionManager,
    session_id: str = "SESSION1",
    tenant_id: str = TENANT,
    **fields: Any,
) -> TenantSessionKey:
    """An active session the manager can find, as activation leaves it."""
    fields.setdefault("status", SessionStatus.ACTIVE)
    session = Session(id=session_id, tenant_id=tenant_id, **fields)
    assert sessions.store.create(session)
    sessions.sessions[session.key] = session
    return session.key
