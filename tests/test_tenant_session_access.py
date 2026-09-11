"""Tenant authorization at the HTTP session boundary."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import optional_ssf_user, require_ssf_user
from services.api_gateway.session_manager import SessionManager
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

REVISION = f"sha256:{'a' * 64}"


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


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> SessionManager:
    manager = SessionManager(store=MemoryTenantSessionStore())
    import services.api_gateway.session_access as access_module

    monkeypatch.setattr(access_module, "session_manager", manager)
    return manager


@pytest.mark.asyncio
async def test_admin_access_uses_only_the_authenticated_tenant(
    manager: SessionManager,
) -> None:
    from services.api_gateway.session_access import require_admin_session_key

    session = await manager.create_admin_session(
        "tenant-b",
        RuntimeConfigurationSnapshot.from_configuration(_configuration("tenant-b")),
    )

    with pytest.raises(HTTPException) as caught:
        require_admin_session_key(
            session.id,
            StudioTenantContext("tenant-a", REVISION),
        )

    assert caught.value.status_code == 404
    assert caught.value.detail == "Session not found"


@pytest.mark.asyncio
async def test_customer_capability_allows_an_anonymous_request(
    manager: SessionManager,
) -> None:
    from services.api_gateway.session_access import require_customer_session_key

    session = await manager.create_admin_session(
        "tenant-a",
        RuntimeConfigurationSnapshot.from_configuration(_configuration("tenant-a")),
    )

    assert require_customer_session_key(session.id, None) == session.key


@pytest.mark.asyncio
async def test_customer_bearer_must_match_capability_tenant(
    manager: SessionManager,
) -> None:
    from services.api_gateway.session_access import require_customer_session_key

    session = await manager.create_admin_session(
        "tenant-b",
        RuntimeConfigurationSnapshot.from_configuration(_configuration("tenant-b")),
    )

    with pytest.raises(HTTPException) as caught:
        require_customer_session_key(
            session.id,
            {
                "studio_tenant_id": "tenant-a",
                "ssf_authorization_revision": REVISION,
            },
        )

    assert caught.value.status_code == 404
    assert caught.value.detail == "Session not found"


@pytest.mark.asyncio
async def test_unknown_customer_capability_has_the_same_neutral_response(
    manager: SessionManager,
) -> None:
    from services.api_gateway.session_access import require_customer_session_key

    with pytest.raises(HTTPException) as caught:
        require_customer_session_key("UNKNOWN1", None)

    assert caught.value.status_code == 404
    assert caught.value.detail == "Session not found"


@pytest.fixture
def http_client():
    original_overrides = app.dependency_overrides.copy()
    from services.api_gateway.session_manager import session_manager

    session_manager.reset(clear_persistence=True)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original_overrides)


def _authenticate_as(tenant_id: str) -> None:
    context = StudioTenantContext(tenant_id, REVISION)
    configuration = _configuration(tenant_id)
    app.dependency_overrides[require_ssf_user] = lambda: {
        "sub": "operator",
        "studio_tenant_id": tenant_id,
        "ssf_authorization_revision": REVISION,
    }
    app.dependency_overrides[require_studio_tenant_context] = lambda: context
    app.dependency_overrides[require_validated_runtime_configuration] = lambda: (
        ValidatedRuntimeConfiguration(context, configuration, "test-correlation")
    )


def test_http_create_freezes_each_tenants_own_runtime_configuration(
    http_client: TestClient,
) -> None:
    from services.api_gateway.session_manager import session_manager

    _authenticate_as("tenant-a")
    created_a = http_client.post("/api/admin/session/create")
    _authenticate_as("tenant-b")
    created_b = http_client.post("/api/admin/session/create")

    assert created_a.status_code == 201
    assert created_b.status_code == 201
    session_a = session_manager.get_session(
        TenantSessionKey("tenant-a", created_a.json()["session_id"])
    )
    session_b = session_manager.get_session(
        TenantSessionKey("tenant-b", created_b.json()["session_id"])
    )
    assert session_a is not None
    assert session_b is not None
    assert session_a.runtime_configuration == RuntimeConfigurationSnapshot.from_configuration(
        _configuration("tenant-a")
    )
    assert session_b.runtime_configuration == RuntimeConfigurationSnapshot.from_configuration(
        _configuration("tenant-b")
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/admin/session/{session_id}/status"),
        ("DELETE", "/api/admin/session/{session_id}/terminate"),
    ],
)
def test_http_admin_cannot_observe_another_tenant(
    http_client: TestClient, method: str, path: str
) -> None:
    _authenticate_as("tenant-b")
    session_id = http_client.post("/api/admin/session/create").json()["session_id"]
    _authenticate_as("tenant-a")

    response = http_client.request(method, path.format(session_id=session_id))

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


def test_http_customer_bearer_cannot_downgrade_to_anonymous_capability(
    http_client: TestClient,
) -> None:
    _authenticate_as("tenant-b")
    session_id = http_client.post("/api/admin/session/create").json()["session_id"]
    app.dependency_overrides[optional_ssf_user] = lambda: {
        "studio_tenant_id": "tenant-a",
        "ssf_authorization_revision": REVISION,
    }

    response = http_client.get(f"/api/customer/session/{session_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


def test_http_customer_rejects_a_malformed_supplied_bearer(
    http_client: TestClient,
) -> None:
    _authenticate_as("tenant-a")
    session_id = http_client.post("/api/admin/session/create").json()["session_id"]

    response = http_client.get(
        f"/api/customer/session/{session_id}",
        headers={"Authorization": "Bearer malformed"},
    )

    assert response.status_code == 401
