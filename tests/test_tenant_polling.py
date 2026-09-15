"""Role and session binding for the polling fallback."""

from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.session_manager import session_manager
from services.api_gateway.websocket_polling_routes import polling_store


def test_polling_id_is_bound_to_its_server_assigned_role_and_session() -> None:
    session_manager.reset(clear_persistence=True)
    polling_store.clients.clear()
    client = TestClient(app)
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    ticket = client.post(
        f"/api/admin/session/{session_id}/realtime-ticket",
        json={"transport": "polling"},
    ).json()["ticket"]
    admin = client.post(
        f"/api/admin/session/{session_id}/polling/activate",
        json={"ticket": ticket},
    )

    assert admin.status_code == 200
    polling_id = admin.json()["polling_id"]
    wrong_role = client.get(f"/api/customer/session/{session_id}/polling/{polling_id}/status")
    wrong_session = client.get(f"/api/admin/session/UNKNOWN1/polling/{polling_id}/status")
    assert wrong_role.status_code == 404
    assert wrong_session.status_code == 404


def test_customer_polling_activation_resolves_public_capability() -> None:
    session_manager.reset(clear_persistence=True)
    polling_store.clients.clear()
    client = TestClient(app)
    session_id = client.post("/api/admin/session/create").json()["session_id"]

    response = client.post(f"/api/customer/session/{session_id}/polling/activate")

    assert response.status_code == 200
    stored = polling_store.clients[response.json()["polling_id"]]
    assert stored.key.session_id == session_id
    assert stored.key.tenant_id == "tenant-test"
    assert stored.client_type.value == "customer"
    assert session_manager.get_session(stored.key).customer_connection_count == 1


def test_generic_client_controlled_polling_routes_are_absent() -> None:
    paths = app.openapi()["paths"]

    assert not any(path.startswith("/api/websocket/polling") for path in paths)
    assert "/api/admin/session/{session_id}/polling/activate" in paths
    assert "/api/customer/session/{session_id}/polling/activate" in paths


def test_ticket_issued_before_termination_cannot_activate_polling() -> None:
    session_manager.reset(clear_persistence=True)
    polling_store.clients.clear()
    client = TestClient(app)
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    ticket = client.post(
        f"/api/admin/session/{session_id}/realtime-ticket",
        json={"transport": "polling"},
    ).json()["ticket"]

    terminated = client.delete(f"/api/admin/session/{session_id}/terminate")
    activation = client.post(
        f"/api/admin/session/{session_id}/polling/activate",
        json={"ticket": ticket},
    )

    assert terminated.status_code == 200
    assert activation.status_code == 404


def test_existing_customer_poll_receives_termination_then_is_removed() -> None:
    session_manager.reset(clear_persistence=True)
    polling_store.clients.clear()
    client = TestClient(app)
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    activated = client.post(f"/api/customer/session/{session_id}/polling/activate").json()
    polling_id = activated["polling_id"]

    client.delete(f"/api/admin/session/{session_id}/terminate")
    response = client.get(f"/api/customer/session/{session_id}/polling/{polling_id}")

    assert response.status_code == 200
    assert response.json()["messages"][-1]["type"] == "session_terminated"
    assert polling_id not in polling_store.clients


def test_stale_admin_poll_request_releases_presence_before_refresh(
    monkeypatch,
) -> None:
    """An abandoned polling client cannot revive itself after the idle deadline."""
    now = [0.0]
    session_manager.reset(clear_persistence=True)
    polling_store.clients.clear()
    monkeypatch.setattr(polling_store, "clock", lambda: now[0])
    client = TestClient(app)
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    ticket = client.post(
        f"/api/admin/session/{session_id}/realtime-ticket",
        json={"transport": "polling"},
    ).json()["ticket"]
    activated = client.post(
        f"/api/admin/session/{session_id}/polling/activate",
        json={"ticket": ticket},
    ).json()
    polling_id = activated["polling_id"]
    key = polling_store.clients[polling_id].key
    assert session_manager.get_session(key).admin_connection_count == 1

    now[0] = 121.0
    response = client.get(
        f"/api/admin/session/{session_id}/polling/{polling_id}/status"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Polling client not found"}
    assert polling_id not in polling_store.clients
    assert session_manager.get_session(key).admin_connection_count == 0
