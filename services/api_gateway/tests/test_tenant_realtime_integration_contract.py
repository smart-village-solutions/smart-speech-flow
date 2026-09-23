"""Contract coverage for the authenticated tenant realtime workflow."""

import pytest
from fastapi.testclient import TestClient

from services.api_gateway import websocket as websocket_module
from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.session_manager import session_manager
from tests.auth_helpers import principal


def test_admin_can_observe_only_its_session_realtime_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The supported admin API exposes connections only inside its tenant session."""
    original_module_manager = websocket_module.websocket_manager
    original_session_manager = session_manager.websocket_manager
    with monkeypatch.context() as patcher:
        patcher.setattr(websocket_module, "websocket_manager", None)
        patcher.setattr(session_manager, "websocket_manager", None)
        session_manager.reset(clear_persistence=True)
        patcher.setitem(
            app.dependency_overrides,
            require_ssf_user,
            lambda: principal("tenant-test", "operator-tenant-test"),
        )

        try:
            client = TestClient(app)
            try:
                created = client.post("/api/admin/session/create")
                assert created.status_code == 201
                session_id = created.json()["session_id"]

                ticket_response = client.post(
                    f"/api/admin/session/{session_id}/realtime-ticket",
                    json={"transport": "websocket"},
                )
                assert ticket_response.status_code == 200
                ticket = ticket_response.json()["ticket"]

                with client.websocket_connect(
                    f"/ws/admin/{session_id}?ticket={ticket}",
                    headers={"Origin": "https://translate.smart-village.solutions"},
                ) as websocket:
                    acknowledgement = websocket.receive_json()
                    assert acknowledgement["type"] == "connection_ack"

                    connections = client.get(
                        f"/api/admin/session/{session_id}/realtime/connections",
                    )
                    assert connections.status_code == 200
                    body = connections.json()
                    assert body["session_id"] == session_id
                    assert body["count"] == 1
                    assert body["connections"][0]["client_type"] == "admin"
            finally:
                client.close()
        finally:
            session_manager.reset(clear_persistence=True)

    assert websocket_module.websocket_manager is original_module_manager
    assert session_manager.websocket_manager is original_session_manager
