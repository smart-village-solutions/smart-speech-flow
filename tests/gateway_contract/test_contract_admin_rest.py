"""Tenant-scoped administrative REST routes."""

from __future__ import annotations

import pytest

from tests.gateway_contract.contract_support import TENANT_A, TENANT_B

NOT_FOUND = {"detail": "Session not found"}
STATUS_FIELDS = {
    "session_id",
    "status",
    "customer_language",
    "admin_connected",
    "customer_connected",
    "message_count",
    "created_at",
    "terminated_at",
    "termination_reason",
    "warning_at",
    "timeout_at",
}
HISTORY_ITEM_FIELDS = {
    "id",
    "consent_status",
    "customer_language",
    "admin_language",
    "status",
    "created_at",
    "terminated_at",
    "message_count",
    "admin_connected",
    "customer_connected",
    "termination_reason",
    "last_activity",
    "timeout_warning_sent",
    "session_timeout_minutes",
    "warning_timeout_minutes",
    "minutes_since_activity",
    "admin_connection_count",
    "customer_connection_count",
    "admin_disconnected_at",
    "reconnect_grace_minutes",
    "timeout_warning_minutes",
    "maximum_lifetime_hours",
    "warning_at",
    "timeout_at",
}


def test_create_returns_a_pending_session_and_its_join_link(client, monkeypatch):
    monkeypatch.setenv("CLIENT_BASE_URL", "https://dialog.example")

    created = client.post("/api/admin/session/create")

    assert created.status_code == 201
    body = created.json()
    assert set(body) == {"session_id", "client_url", "status", "created_at", "message"}
    assert body["status"] == "pending"
    assert body["client_url"] == f"https://dialog.example/join/{body['session_id']}"


def test_create_ends_the_tenants_previous_session_only(client, conversations, identity):
    foreign = conversations.create(TENANT_B)
    first = conversations.create(TENANT_A)
    second = conversations.create(TENANT_A)

    first_status = client.get(f"/api/admin/session/{first}/status").json()
    second_status = client.get(f"/api/admin/session/{second}/status").json()
    identity.act_as(TENANT_B)
    foreign_status = client.get(f"/api/admin/session/{foreign}/status").json()

    assert (first_status["status"], first_status["termination_reason"]) == (
        "terminated",
        "new_session_created",
    )
    assert second_status["status"] == "pending"
    assert foreign_status["status"] == "pending"


def test_status_reports_the_full_session_view(client, conversations):
    session_id = conversations.create()
    conversations.activate(session_id, "tr")

    response = client.get(f"/api/admin/session/{session_id}/status")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == STATUS_FIELDS
    assert body["session_id"] == session_id
    assert (body["status"], body["customer_language"], body["message_count"]) == (
        "active",
        "tr",
        0,
    )
    assert (body["terminated_at"], body["termination_reason"]) == (None, None)


def test_current_session_without_an_id_reports_the_active_one(client, conversations):
    assert client.get("/api/admin/session/current").json() == {
        "detail": "Keine aktive Admin-Session gefunden"
    }

    session_id = conversations.create()
    response = client.get("/api/admin/session/current")

    assert response.status_code == 200
    assert set(response.json()) == STATUS_FIELDS
    assert response.json()["session_id"] == session_id


def test_terminate_reports_the_first_and_a_repeated_termination(client, conversations):
    session_id = conversations.create()

    first = client.delete(f"/api/admin/session/{session_id}/terminate")
    repeated = client.delete(f"/api/admin/session/{session_id}/terminate")

    assert first.status_code == 200
    assert set(first.json()) == {"message", "session_id", "status", "timestamp"}
    assert (first.json()["session_id"], first.json()["status"]) == (session_id, "terminated")
    assert repeated.status_code == 200
    assert set(repeated.json()) == {"message", "session_id", "status"}
    assert repeated.json()["status"] == "already_terminated"


def test_history_lists_only_the_signed_tenants_sessions(client, conversations, identity):
    foreign = conversations.create(TENANT_B)
    conversations.terminate(foreign)
    ended = conversations.create(TENANT_A)
    conversations.terminate(ended)
    active = conversations.create(TENANT_A)

    identity.act_as(TENANT_A)
    response = client.get("/api/admin/session/history")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"sessions", "total_count", "active_sessions"}
    assert [item["id"] for item in body["sessions"]] == [ended]
    assert [item["id"] for item in body["active_sessions"]] == [active]
    assert body["total_count"] == 1
    for item in body["sessions"] + body["active_sessions"]:
        assert set(item) == HISTORY_ITEM_FIELDS


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/admin/session/{id}/messages"),
        ("POST", "/api/admin/session/{id}/message"),
        ("GET", "/api/admin/session/{id}/audio/any-message/original.wav"),
        ("GET", "/api/admin/session/{id}/audio/any-message/translated.wav"),
    ],
)
def test_another_tenants_session_is_not_found(client, conversations, identity, method, path):
    session_id = conversations.create(TENANT_A)
    body = {"transport": "websocket", "text": "x", "source_lang": "de", "target_lang": "en"}

    identity.act_as(TENANT_B)
    response = client.request(method, path.format(id=session_id), json=body)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    identity.act_as(TENANT_A)
    assert client.get(f"/api/admin/session/{session_id}/status").json()["status"] == "pending"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/admin/session/create"),
        ("GET", "/api/admin/session/current"),
        ("GET", "/api/admin/session/{id}/status"),
        ("DELETE", "/api/admin/session/{id}/terminate"),
        ("GET", "/api/admin/session/{id}/messages"),
        ("POST", "/api/admin/session/{id}/realtime-ticket"),
        ("POST", "/api/admin/session/{id}/polling/activate"),
        ("GET", "/api/admin/realtime/connections"),
    ],
)
def test_admin_routes_require_a_bearer_token(client, conversations, identity, method, path):
    session_id = conversations.create()

    identity.unauthenticated()
    response = client.request(method, path.format(id=session_id), json={})

    assert response.status_code == 401
    assert response.json() == {"detail": "A valid bearer token is required"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("method", "request_options"),
    [
        ("GET", {"params": {"tenant_id": TENANT_B}}),
        ("GET", {"headers": {"X-Tenant-Id": TENANT_B}}),
        ("GET", {"cookies": {"studio_tenant_id": TENANT_B}}),
        ("POST", {"json": {"transport": "websocket", "context": {"studio_tenant_id": TENANT_B}}}),
    ],
)
def test_tenant_selectors_outside_the_token_are_refused(
    client, conversations, identity, method, request_options
):
    session_id = conversations.create()
    path = f"/api/admin/session/{session_id}/" + (
        "status" if method == "GET" else "realtime-ticket"
    )

    identity.with_real_tenant_context()
    client.cookies.clear()
    response = client.request(method, path, **request_options)

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Tenant selectors are not accepted outside the bearer token"
    }
