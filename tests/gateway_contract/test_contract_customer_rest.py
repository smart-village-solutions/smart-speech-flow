"""Customer REST routes, reached through the public session capability."""

from __future__ import annotations

import pytest

from tests.gateway_contract.contract_support import TENANT_A, TENANT_B

NOT_FOUND = {"detail": "Session not found"}
ACTIVATION_FIELDS = {"session_id", "status", "customer_language", "message", "timestamp"}
CUSTOMER_STATUS_FIELDS = {
    "session_id",
    "status",
    "customer_language",
    "admin_connected",
    "customer_connected",
    "is_active",
    "can_send_messages",
    "created_at",
    "warning_at",
    "timeout_at",
}


def test_activation_response_for_a_first_and_a_repeated_activation(conversations):
    session_id = conversations.create()

    first = conversations.activate(session_id, "fa")
    repeated = conversations.activate(session_id, "fa")
    switched = conversations.activate(session_id, "uk")

    for body in (first, repeated, switched):
        assert set(body) == ACTIVATION_FIELDS
        assert (body["session_id"], body["status"]) == (session_id, "active")
    assert first["customer_language"] == "fa"
    assert repeated["customer_language"] == "fa"
    assert switched["customer_language"] == "uk"
    assert first["message"] != repeated["message"]


def test_activation_of_an_unknown_session_is_not_found(client):
    response = client.post(
        "/api/customer/session/activate", json={"session_id": "NOSUCH01", "customer_language": "en"}
    )

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


@pytest.mark.parametrize("body", [{"session_id": "ABCD1234"}, {"customer_language": "en"}])
def test_activation_requires_session_and_language(client, body):
    assert client.post("/api/customer/session/activate", json=body).status_code == 422


def test_customer_status_before_and_after_activation(client, conversations):
    session_id = conversations.create()

    pending = client.get(f"/api/customer/session/{session_id}").json()
    conversations.activate(session_id, "ru")
    active = client.get(f"/api/customer/session/{session_id}").json()

    assert set(pending) == CUSTOMER_STATUS_FIELDS
    assert (pending["status"], pending["is_active"], pending["can_send_messages"]) == (
        "pending",
        False,
        False,
    )
    assert set(active) == CUSTOMER_STATUS_FIELDS
    assert (active["status"], active["customer_language"], active["can_send_messages"]) == (
        "active",
        "ru",
        True,
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/customer/session/{id}/messages"),
        ("POST", "/api/customer/session/{id}/message"),
        ("GET", "/api/customer/session/{id}/audio/any-message/translated.wav"),
        ("POST", "/api/customer/session/activate"),
    ],
)
def test_a_bearer_from_another_tenant_cannot_use_the_capability(
    client, conversations, identity, method, path
):
    session_id = conversations.create(TENANT_A)
    body = {"session_id": session_id, "customer_language": "en", "text": "x"}

    identity.customer_bearer(TENANT_B)
    response = client.request(method, path.format(id=session_id), json=body)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/customer/session/{id}/messages"),
        ("POST", "/api/customer/session/activate"),
    ],
)
def test_a_malformed_supplied_bearer_is_unauthorized(client, conversations, identity, method, path):
    session_id = conversations.create()
    body = {"session_id": session_id, "customer_language": "en"}

    identity.with_real_customer_authentication()
    response = client.request(
        method,
        path.format(id=session_id),
        json=body,
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "A valid bearer token is required"}


def test_customer_routes_refuse_an_ended_session(client, conversations):
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    conversations.terminate(session_id)

    for method, path in (
        ("GET", f"/api/customer/session/{session_id}"),
        ("GET", f"/api/customer/session/{session_id}/messages"),
        ("POST", f"/api/customer/session/{session_id}/message"),
        ("POST", f"/api/customer/session/{session_id}/polling/activate"),
    ):
        response = client.request(method, path, json={})
        assert response.status_code == 404, path
        assert response.json() == NOT_FOUND


def test_customer_audio_for_an_unknown_message_or_variant(client, conversations):
    session_id = conversations.create()

    missing = client.get(f"/api/customer/session/{session_id}/audio/unknown/translated.wav")
    bad_variant = client.get(f"/api/customer/session/{session_id}/audio/unknown/other.wav")

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Audio file not found"}
    assert bad_variant.status_code == 422


def test_supported_language_lists_agree(client):
    customer = client.get("/api/customer/languages/supported")
    shared = client.get("/api/languages/supported")
    public = client.get("/languages")

    for response in (customer, shared, public):
        assert response.status_code == 200
        assert response.json() == customer.json()
    assert {"languages", "admin_default", "popular"} <= set(customer.json())
