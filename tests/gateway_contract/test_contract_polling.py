"""The tenant- and role-bound HTTP polling fallback."""

from __future__ import annotations

import pytest

from tests.gateway_contract.contract_support import ALLOWED_ORIGIN, TENANT_A, TENANT_B


def _activate_admin(client, conversations, session_id: str) -> dict:
    ticket = conversations.ticket(session_id, "polling")
    response = client.post(
        f"/api/admin/session/{session_id}/polling/activate", json={"ticket": ticket}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _activate_customer(client, session_id: str) -> dict:
    response = client.post(f"/api/customer/session/{session_id}/polling/activate")
    assert response.status_code == 200, response.text
    return response.json()


def test_activation_returns_the_server_assigned_identity_for_each_role(client, conversations):
    session_id = conversations.create()

    admin = _activate_admin(client, conversations, session_id)
    customer = _activate_customer(client, session_id)

    for body, role in ((admin, "admin"), (customer, "customer")):
        assert set(body) == {"polling_id", "session_id", "client_type", "polling_interval"}
        assert (body["session_id"], body["client_type"], body["polling_interval"]) == (
            session_id,
            role,
            5,
        )
    assert admin["polling_id"] != customer["polling_id"]


@pytest.mark.parametrize("body", [{}, {"ticket": ""}, {"ticket": "x" * 257}])
def test_admin_activation_rejects_a_malformed_ticket_body(client, conversations, body):
    session_id = conversations.create()

    response = client.post(f"/api/admin/session/{session_id}/polling/activate", json=body)

    assert response.status_code == 422


def test_customer_activation_requires_a_live_session_and_a_matching_bearer(
    client, conversations, identity
):
    session_id = conversations.create(TENANT_A)

    unknown = client.post("/api/customer/session/NOSUCH01/polling/activate")
    identity.customer_bearer(TENANT_B)
    foreign = client.post(f"/api/customer/session/{session_id}/polling/activate")
    identity.customer_bearer(TENANT_A)
    matching = client.post(f"/api/customer/session/{session_id}/polling/activate")

    for denied in (unknown, foreign):
        assert denied.status_code == 404
        assert denied.json() == {"detail": "Session not found"}
    assert matching.status_code == 200


def test_each_role_may_hold_at_most_ten_pollers_per_session(client, conversations):
    session_id = conversations.create()
    for _ in range(10):
        _activate_customer(client, session_id)

    refused = client.post(f"/api/customer/session/{session_id}/polling/activate")

    assert refused.status_code == 429
    assert refused.json() == {"detail": "Polling connection limit reached"}
    _activate_admin(client, conversations, session_id)


def test_a_sent_message_reaches_the_other_role_as_an_envelope(client, conversations):
    session_id = conversations.create()
    admin = _activate_admin(client, conversations, session_id)
    customer = _activate_customer(client, session_id)
    base = f"/api/customer/session/{session_id}/polling/{customer['polling_id']}"

    sent = client.post(f"{base}/send", json={"type": "message", "content": {"text": "hi"}})
    received = client.get(f"/api/admin/session/{session_id}/polling/{admin['polling_id']}")
    own = client.get(base)

    assert sent.status_code == 200
    assert sent.json() == {"status": "success"}
    assert received.json() == {
        "messages": [
            {
                "type": "message",
                "content": {"text": "hi"},
                "session_id": session_id,
                "client_type": "customer",
            }
        ],
        "message_count": 1,
    }
    assert own.json() == {"messages": [], "message_count": 0}


@pytest.mark.parametrize(
    "body", [{"type": "", "content": {}}, {"type": "message"}, {"type": "m", "content": "x"}]
)
def test_send_rejects_a_malformed_envelope(client, conversations, body):
    session_id = conversations.create()
    customer = _activate_customer(client, session_id)

    response = client.post(
        f"/api/customer/session/{session_id}/polling/{customer['polling_id']}/send", json=body
    )

    assert response.status_code == 422


def test_a_polled_send_reaches_a_connected_websocket(client, conversations):
    session_id = conversations.create()
    customer = _activate_customer(client, session_id)
    ticket = conversations.ticket(session_id)

    with client.websocket_connect(
        f"/ws/admin/{session_id}?ticket={ticket}", headers={"Origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        client.post(
            f"/api/customer/session/{session_id}/polling/{customer['polling_id']}/send",
            json={"type": "message", "content": {"text": "via polling"}},
        )
        frame = socket.receive_json()

    assert frame == {
        "type": "message",
        "content": {"text": "via polling"},
        "session_id": session_id,
        "client_type": "customer",
    }


def test_another_tenant_cannot_use_an_admin_poller(client, conversations, identity):
    session_id = conversations.create(TENANT_A)
    admin = _activate_admin(client, conversations, session_id)
    base = f"/api/admin/session/{session_id}/polling/{admin['polling_id']}"

    identity.act_as(TENANT_B)
    responses = [
        client.get(base),
        client.post(f"{base}/send", json={"type": "message", "content": {}}),
        client.post(f"{base}/recover"),
        client.delete(base),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"detail": "Session not found"}
    identity.act_as(TENANT_A)
    assert client.get(f"{base}/status").status_code == 200


def test_a_poller_of_one_role_cannot_be_driven_through_the_other(client, conversations):
    session_id = conversations.create()
    admin = _activate_admin(client, conversations, session_id)

    response = client.get(f"/api/customer/session/{session_id}/polling/{admin['polling_id']}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Polling client not found"}


def test_status_recover_and_disconnect_shapes(client, conversations):
    session_id = conversations.create()
    admin = _activate_admin(client, conversations, session_id)
    base = f"/api/admin/session/{session_id}/polling/{admin['polling_id']}"

    status = client.get(f"{base}/status")
    recovered = client.post(f"{base}/recover")
    disconnected = client.delete(base)
    after = client.get(f"{base}/status")

    assert status.json() == {
        "polling_id": admin["polling_id"],
        "session_id": session_id,
        "client_type": "admin",
        "queued_messages": 0,
    }
    assert recovered.json() == {"status": "recovery_requested"}
    assert disconnected.json() == {"status": "disconnected"}
    assert after.status_code == 404
    assert after.json() == {"detail": "Polling client not found"}


def test_admin_poller_receives_termination_then_is_removed(client, conversations):
    session_id = conversations.create()
    admin = _activate_admin(client, conversations, session_id)
    base = f"/api/admin/session/{session_id}/polling/{admin['polling_id']}"

    conversations.terminate(session_id)

    for refused in (
        client.get(f"{base}/status"),
        client.post(f"{base}/recover"),
        client.post(f"{base}/send", json={"type": "message", "content": {}}),
    ):
        assert refused.status_code == 404
        assert refused.json() == {"detail": "Polling client not found"}
    final = client.get(base)
    assert final.status_code == 200
    assert final.json() == {
        "messages": [
            {
                "type": "session_terminated",
                "session_id": session_id,
                "reason": "manual_admin_termination",
                "reconnect_allowed": False,
            }
        ],
        "message_count": 1,
    }
    assert client.get(base).status_code == 404
