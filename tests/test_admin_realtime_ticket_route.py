"""HTTP issuance of admin realtime tickets."""

import asyncio

from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.tenant_session import (
    RuntimeConfigurationSnapshot,
    TenantSessionKey,
)

REVISION = f"sha256:{'a' * 64}"


def test_admin_issues_a_ticket_scoped_to_the_authenticated_session(
    session_manager, gateway_dependencies
) -> None:
    session_manager.reset(clear_persistence=True)
    client = TestClient(app)
    session_id = client.post("/api/admin/session/create").json()["session_id"]

    response = client.post(
        f"/api/admin/session/{session_id}/realtime-ticket",
        json={"transport": "websocket"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ticket"]
    assert body["expires_at"]
    assert (
        gateway_dependencies.realtime_tickets.consume(
            body["ticket"],
            TenantSessionKey("tenant-test", session_id),
            "websocket",
        )
        is True
    )


def test_admin_cannot_issue_a_ticket_for_another_tenant(session_manager) -> None:
    session_manager.reset(clear_persistence=True)
    client = TestClient(app)
    session = asyncio.run(
        session_manager.create_admin_session(
            "tenant-other",
            RuntimeConfigurationSnapshot(REVISION, REVISION, "{}"),
        )
    )

    response = client.post(
        f"/api/admin/session/{session.id}/realtime-ticket",
        json={"transport": "websocket"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}
