"""Only authenticated, aggregate usage crosses the admin API boundary."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api_gateway.audio_storage import AudioStore
from services.api_gateway.auth import get_auth_login_directory_provider, require_ssf_user
from services.api_gateway.conversation_usage import ConversationUsage
from services.api_gateway.dependencies import get_oidc_key_cache, get_session_manager
from services.api_gateway.routes.admin import router
from services.api_gateway.session_manager import TenantSessionManager
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_context import (
    StudioTenantContext,
    require_admin_ref,
    require_studio_tenant_context,
)


@pytest.fixture
def route_setup(tmp_path):
    now = [datetime(2026, 11, 18, 8, tzinfo=timezone.utc)]
    manager = TenantSessionManager(
        store=MemoryTenantSessionStore(),
        audio_store=AudioStore.from_environment(),
        clock=lambda: now[0],
        usage=ConversationUsage(str(tmp_path / "usage.db"), clock=lambda: now[0]),
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_ssf_user] = lambda: {"sub": "alice"}
    app.dependency_overrides[require_studio_tenant_context] = lambda: StudioTenantContext(
        "a", f"sha256:{'a' * 64}"
    )
    app.dependency_overrides[require_admin_ref] = lambda: "owner-alice"
    app.dependency_overrides[get_session_manager] = lambda: manager
    app.dependency_overrides[get_auth_login_directory_provider] = lambda: lambda: None
    app.dependency_overrides[get_oidc_key_cache] = lambda: None
    return app, manager, now


async def test_usage_endpoint_returns_only_verified_scope_aggregates(route_setup):
    app, manager, now = route_setup
    session = await manager.create_admin_session("a", f"sha256:{'a' * 64}", owner_ref="owner-alice")
    await manager.activate_session(session.key, "ar")
    now[0] += timedelta(minutes=10)
    with TestClient(app) as client:
        response = client.get("/api/admin/usage?tenant_id=b&owner_ref=someone-else")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["personal"] == {"total_seconds": 600, "by_language": {"ar": 600}}
    assert body["organisation"] == body["server"] == body["personal"]
    assert body["complete"] is False
    assert "owner-alice" not in response.text
    assert session.id not in response.text
    assert "tenant_id" not in response.text


def test_usage_failure_is_retryable_and_not_cacheable(route_setup):
    app, manager, now = route_setup
    manager.usage = None
    with TestClient(app) as client:
        response = client.get("/api/admin/usage")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "Conversation usage is temporarily unavailable"}


def test_usage_requires_authentication(route_setup):
    app, manager, now = route_setup
    app.dependency_overrides.pop(require_ssf_user)
    with TestClient(app) as client:
        response = client.get("/api/admin/usage")
    assert response.status_code == 401
    assert "personal" not in response.json()
