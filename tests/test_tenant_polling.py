"""Role and session binding for the polling fallback."""

from collections import deque

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app


@pytest.fixture
def polling_store(gateway_dependencies):
    return gateway_dependencies.polling_store


def test_polling_id_is_bound_to_its_server_assigned_role_and_session(
    session_manager, polling_store
) -> None:
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


async def test_customer_polling_activation_resolves_public_capability(
    session_manager, polling_store
) -> None:
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
    assert (await session_manager.get_session(stored.key)).customer_connection_count == 1


def test_generic_client_controlled_polling_routes_are_absent() -> None:
    paths = app.openapi()["paths"]

    assert not any(path.startswith("/api/websocket/polling") for path in paths)
    assert "/api/admin/session/{session_id}/polling/activate" in paths
    assert "/api/customer/session/{session_id}/polling/activate" in paths


def test_ticket_issued_before_termination_cannot_activate_polling(
    session_manager, polling_store
) -> None:
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


def test_existing_customer_poll_receives_termination_then_is_removed(
    session_manager, polling_store
) -> None:
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


async def test_stale_admin_poll_request_releases_presence_before_refresh(
    monkeypatch, polling_store, session_manager
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
    assert (await session_manager.get_session(key)).admin_connection_count == 1

    now[0] = 121.0
    response = client.get(f"/api/admin/session/{session_id}/polling/{polling_id}/status")

    assert response.status_code == 404
    assert response.json() == {"detail": "Polling client not found"}
    assert polling_id not in polling_store.clients
    assert (await session_manager.get_session(key)).admin_connection_count == 0


@pytest.mark.parametrize("authenticated", [False, True], ids=["guest", "user"])
@pytest.mark.parametrize("selector_source", ["query", "body", "header", "cookie"])
@pytest.mark.parametrize(
    "operation", ["activate", "poll", "send", "status", "recover", "disconnect"]
)
async def test_customer_polling_rejects_tenant_selectors_without_side_effects(
    request, monkeypatch, session_manager, polling_store, authenticated, selector_source, operation
) -> None:
    from services.api_gateway.auth import VERIFIED_TENANT_ID_CLAIM, optional_ssf_user

    session_manager.reset(clear_persistence=True)
    polling_store.clients.clear()
    client = TestClient(app, client=(request.node.nodeid, 50000))
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    base = f"/api/customer/session/{session_id}/polling"
    polling_id = client.post(base + "/activate").json()["polling_id"]
    stored = polling_store.clients[polling_id]
    principal = {VERIFIED_TENANT_ID_CLAIM: stored.key.tenant_id} if authenticated else None
    monkeypatch.setitem(app.dependency_overrides, optional_ssf_user, lambda: principal)
    methods = {
        "activate": "POST",
        "poll": "GET",
        "send": "POST",
        "status": "GET",
        "recover": "POST",
        "disconnect": "DELETE",
    }
    suffix = "" if operation in {"poll", "disconnect"} else "/" + operation
    path = base + "/activate" if operation == "activate" else base + "/" + polling_id + suffix
    payload = {"type": "test_probe", "content": {}}
    options = {"json": payload}
    if selector_source == "query":
        options["params"] = {"tenant_id": "other-tenant"}
    elif selector_source == "body":
        payload["content"] = {"tenant_id": "other-tenant"}
    elif selector_source == "header":
        options["headers"] = {"X-Tenant-Id": "other-tenant"}
    else:
        client.cookies.set("studio_tenant_id", "other-tenant")

    response = client.request(methods[operation], path, **options)

    assert response.status_code == 400
    assert list(polling_store.clients) == [polling_id]
    assert stored.messages == deque()
    assert (await session_manager.get_session(stored.key)).customer_connection_count == 1


@pytest.mark.parametrize("actor", [None, "tenant-test", "other-tenant"])
def test_customer_polling_preserves_guest_and_authenticated_tenant_access(
    request, monkeypatch, session_manager, polling_store, actor
):
    from services.api_gateway.auth import VERIFIED_TENANT_ID_CLAIM, optional_ssf_user

    session_manager.reset(clear_persistence=True)
    polling_store.clients.clear()
    client = TestClient(app, client=(request.node.nodeid, 50000))
    session_id = client.post("/api/admin/session/create").json()["session_id"]
    base = f"/api/customer/session/{session_id}/polling"
    polling_id = client.post(base + "/activate").json()["polling_id"]
    principal = {VERIFIED_TENANT_ID_CLAIM: actor} if actor else None
    monkeypatch.setitem(app.dependency_overrides, optional_ssf_user, lambda: principal)

    status = client.get(base + "/" + polling_id + "/status")
    activation = client.post(base + "/activate")

    expected = 404 if actor == "other-tenant" else 200
    assert status.status_code == expected
    assert activation.status_code == expected
