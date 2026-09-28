"""WebSocket connection, frames and close codes on the role-specific endpoints."""

from __future__ import annotations

import pytest
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from tests.gateway_contract.contract_support import ALLOWED_ORIGIN, TENANT_A, TENANT_B

ORIGIN = {"Origin": ALLOWED_ORIGIN}


def _admin_socket(client, conversations, session_id: str):
    ticket = conversations.ticket(session_id)
    return client.websocket_connect(f"/ws/admin/{session_id}?ticket={ticket}", headers=ORIGIN)


def _customer_socket(client, session_id: str, headers=ORIGIN):
    return client.websocket_connect(f"/ws/customer/{session_id}", headers=headers)


def test_connection_ack_carries_session_role_time_and_heartbeat_interval(client, conversations):
    session_id = conversations.create()

    with _admin_socket(client, conversations, session_id) as socket:
        ack = socket.receive_json()

    assert set(ack) == {"type", "session_id", "client_type", "timestamp", "heartbeat_interval"}
    assert ack["type"] == "connection_ack"
    assert ack["session_id"] == session_id
    assert ack["client_type"] == "admin"
    assert ack["heartbeat_interval"] == 30


def test_admin_websocket_without_a_ticket_is_closed_as_a_policy_violation(client, conversations):
    session_id = conversations.create()

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"/ws/admin/{session_id}", headers=ORIGIN):
            pass

    assert closed.value.code == 1008


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://evil.example"}])
def test_customer_websocket_refuses_a_missing_or_foreign_origin(client, conversations, headers):
    session_id = conversations.create()

    with pytest.raises(WebSocketDisconnect) as closed:
        with _customer_socket(client, session_id, headers=headers):
            pass

    assert (closed.value.code, closed.value.reason) == (1008, "Origin not allowed")


def test_admin_websocket_refuses_a_foreign_origin_with_a_valid_ticket(client, conversations):
    session_id = conversations.create()
    ticket = conversations.ticket(session_id)
    url = f"/ws/admin/{session_id}?ticket={ticket}"

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(url, headers={"Origin": "https://evil.example"}):
            pass

    assert (closed.value.code, closed.value.reason) == (1008, "Origin not allowed")


def test_customer_websocket_for_an_unknown_or_ended_session_is_denied_before_accept(
    client, conversations
):
    ended = conversations.create()
    conversations.terminate(ended)

    for session_id in ("NOSUCH01", ended):
        with pytest.raises(WebSocketDenialResponse) as denied:
            with _customer_socket(client, session_id):
                pass
        assert denied.value.status_code == 404
        assert denied.value.json() == {"detail": "Session not found"}


def test_peers_see_joins_relayed_messages_typing_and_leaves(client, conversations):
    session_id = conversations.create()
    conversations.activate(session_id, "ar")

    with _admin_socket(client, conversations, session_id) as admin:
        assert admin.receive_json()["type"] == "connection_ack"
        with _customer_socket(client, session_id) as customer:
            assert customer.receive_json()["type"] == "connection_ack"
            joined = admin.receive_json()
            assert joined["type"] == "client_joined"
            assert joined["client_type"] == "customer"
            assert joined["customer_language"] == "ar"
            assert set(joined) == {
                "type",
                "session_id",
                "client_type",
                "connection_id",
                "timestamp",
                "customer_language",
            }

            admin.send_json({"type": "message", "content": {"text": "hallo"}})
            relayed = customer.receive_json()
            assert set(relayed) == {"type", "from", "session_id", "content", "timestamp"}
            assert relayed["from"] == "admin"
            assert relayed["content"] == {"text": "hallo"}

            customer.send_json({"type": "typing_indicator", "is_typing": True})
            typing = admin.receive_json()
            assert typing["type"] == "typing_indicator"
            assert (typing["from"], typing["is_typing"]) == ("customer", True)

            customer.send_json({"type": "message", "content": {"text": "marhaba"}})
            # The admin's next frame is the customer's message: its own was not echoed.
            assert admin.receive_json()["content"] == {"text": "marhaba"}

            customer.close()
            left = admin.receive_json()
    assert left["type"] == "client_left"
    assert (left["client_type"], left["reason"]) == ("customer", "client_disconnect")
    assert set(left) == {
        "type",
        "session_id",
        "client_type",
        "connection_id",
        "reason",
        "timestamp",
    }


def test_malformed_frame_is_answered_with_an_error_and_the_socket_stays_open(client, conversations):
    session_id = conversations.create()

    with _admin_socket(client, conversations, session_id) as socket:
        socket.receive_json()
        socket.send_text("not json")
        error = socket.receive_json()
        socket.send_text("still not json")
        second = socket.receive_json()

    assert error["type"] == "error"
    assert error["error"] == "Message processing failed"
    assert second["type"] == "error"


def test_termination_notifies_connected_clients_and_closes_normally(client, conversations):
    session_id = conversations.create()

    with _admin_socket(client, conversations, session_id) as socket:
        socket.receive_json()
        conversations.terminate(session_id)
        terminated = socket.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()

    assert terminated["type"] == "session_terminated"
    assert terminated["session_id"] == session_id
    assert terminated["reason"] == "manual_admin_termination"
    assert terminated["reconnect_allowed"] is False
    assert closed.value.code == 1000


def test_tenant_connection_listing_shows_only_the_signed_tenant(client, conversations, identity):
    own = conversations.create(TENANT_A)
    foreign = conversations.create(TENANT_B)
    polled = client.post(f"/api/customer/session/{foreign}/polling/activate")
    assert polled.status_code == 200

    identity.act_as(TENANT_A)
    with _admin_socket(client, conversations, own) as socket:
        socket.receive_json()
        listing = client.get("/api/admin/realtime/connections")
        identity.act_as(TENANT_B)
        foreign_listing = client.get("/api/admin/realtime/connections")

    assert listing.status_code == 200
    body = listing.json()
    assert body["count"] == 1
    assert [(item["transport"], item["session_id"]) for item in body["connections"]] == [
        ("websocket", own)
    ]
    foreign_body = foreign_listing.json()
    assert foreign_body["count"] == 1
    assert foreign_body["connections"][0] == {
        "transport": "polling",
        "polling_id": polled.json()["polling_id"],
        "session_id": foreign,
        "client_type": "customer",
        "queued_messages": 0,
        "terminated": False,
    }


def test_session_connection_listing_is_scoped_to_the_signed_tenant(client, conversations, identity):
    session_id = conversations.create(TENANT_A)

    identity.act_as(TENANT_B)
    response = client.get(f"/api/admin/session/{session_id}/realtime/connections")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


def test_admin_websocket_for_a_lapsed_session_closes_before_the_origin_check(
    client, conversations, lapse_sessions
):
    session_id = conversations.create()
    ticket = conversations.ticket(session_id)
    lapse_sessions()

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"/ws/admin/{session_id}?ticket={ticket}", headers=ORIGIN):
            pass

    assert (closed.value.code, closed.value.reason) == (4404, "Session not found")
