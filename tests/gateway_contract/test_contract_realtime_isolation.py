"""Another tenant's key, session or ticket gets nothing from the realtime surface.

test_contract_websocket.py pins the tenant-scoped connection listings,
test_contract_polling.py a foreign admin driving an admin poller, and
test_contract_realtime_tickets.py a foreign ticket on polling activation. This
file adds the socket side, the frames themselves and the customer poller.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.gateway_contract.contract_support import ALLOWED_ORIGIN, TENANT_A, TENANT_B

ORIGIN = {"Origin": ALLOWED_ORIGIN}


def _admin_socket(client, session_id: str, ticket: str):
    return client.websocket_connect(f"/ws/admin/{session_id}?ticket={ticket}", headers=ORIGIN)


def _close(client, session_id: str, ticket: str) -> tuple[int, str]:
    with pytest.raises(WebSocketDisconnect) as closed:
        with _admin_socket(client, session_id, ticket):
            pass
    return closed.value.code, closed.value.reason


def _before_a_sentinel(socket) -> list[dict[str, Any]]:
    socket.send_text("not json")
    frames: list[dict[str, Any]] = []
    while True:
        frame: dict[str, Any] = socket.receive_json()
        if frame["type"] == "error":
            return frames
        frames.append(frame)


def _customer_poller(client, session_id: str) -> str:
    response = client.post(f"/api/customer/session/{session_id}/polling/activate")
    assert response.status_code == 200, response.text
    polling_id: str = response.json()["polling_id"]
    return polling_id


def test_a_ticket_opens_no_socket_on_another_tenants_session(client, conversations, identity):
    own = conversations.create(TENANT_A)
    foreign = conversations.create(TENANT_B)
    foreign_ticket = conversations.ticket(foreign)

    identity.act_as(TENANT_A)
    ticket = conversations.ticket(own)
    with _admin_socket(client, own, ticket) as peer:
        peer.receive_json()
        refused = _close(client, own, foreign_ticket)
        leaked = _before_a_sentinel(peer)

    assert refused == (4404, "Session not found")
    assert leaked == []
    # The mismatch spent the ticket, so its own session refuses it too.
    assert _close(client, foreign, foreign_ticket) == (4404, "Session not found")


@pytest.mark.usefixtures("speech_services")
def test_one_tenants_frames_never_reach_another_tenants_sockets_or_pollers(
    client, conversations, identity
):
    sessions = {TENANT_A: conversations.create(TENANT_A), TENANT_B: conversations.create(TENANT_B)}
    tickets = {}
    for tenant, session_id in sessions.items():
        identity.act_as(tenant)
        conversations.activate(session_id, "en")
        tickets[tenant] = conversations.ticket(session_id)
    foreign_poller = _customer_poller(client, sessions[TENANT_B])

    foreign_polling = f"/api/customer/session/{sessions[TENANT_B]}/polling/{foreign_poller}"

    with _admin_socket(client, sessions[TENANT_B], tickets[TENANT_B]) as foreign:
        foreign.receive_json()
        # The foreign session's own admin join.
        assert client.get(foreign_polling).json()["message_count"] == 1
        with _admin_socket(client, sessions[TENANT_A], tickets[TENANT_A]) as admin:
            admin.receive_json()
            with client.websocket_connect(
                f"/ws/customer/{sessions[TENANT_A]}", headers=ORIGIN
            ) as customer:
                customer.receive_json()
                admin.receive_json()
                admin.send_json({"type": "message", "content": {"text": "hallo"}})
                admin.send_json({"type": "typing_indicator", "is_typing": True})
                identity.act_as(TENANT_A)
                sent = conversations.send_text(sessions[TENANT_A])
                assert sent.status_code == 200, sent.text
                assert [frame["type"] for frame in _before_a_sentinel(customer)] == [
                    "message",
                    "typing_indicator",
                    "message",
                ]
            conversations.terminate(sessions[TENANT_A])
            while admin.receive_json()["type"] != "session_terminated":
                pass
        leaked = _before_a_sentinel(foreign)
        polled = client.get(foreign_polling)

    assert leaked == []
    assert polled.status_code == 200
    assert polled.json() == {"messages": [], "message_count": 0}


def test_another_tenant_cannot_read_an_admin_pollers_status(client, conversations, identity):
    session_id = conversations.create(TENANT_A)
    ticket = conversations.ticket(session_id, "polling")
    activated = client.post(
        f"/api/admin/session/{session_id}/polling/activate", json={"ticket": ticket}
    )
    polling_id = activated.json()["polling_id"]

    identity.act_as(TENANT_B)
    response = client.get(f"/api/admin/session/{session_id}/polling/{polling_id}/status")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


def test_a_foreign_bearer_cannot_drive_or_feed_a_customer_poller(client, conversations, identity):
    session_id = conversations.create(TENANT_A)
    polling_id = _customer_poller(client, session_id)
    base = f"/api/customer/session/{session_id}/polling/{polling_id}"

    identity.customer_bearer(TENANT_B)
    responses = [
        client.get(base),
        client.post(f"{base}/send", json={"type": "message", "content": {"text": "x"}}),
        client.get(f"{base}/status"),
        client.post(f"{base}/recover"),
        client.delete(base),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"detail": "Polling client not found"}
    identity.customer_bearer(TENANT_A)
    status = client.get(f"{base}/status")
    assert status.status_code == 200
    assert status.json()["queued_messages"] == 0


def test_a_poller_cannot_be_driven_through_another_session(client, conversations, identity):
    own = conversations.create(TENANT_A)
    foreign = conversations.create(TENANT_B)
    polling_id = _customer_poller(client, foreign)

    response = client.get(f"/api/customer/session/{own}/polling/{polling_id}/status")

    assert response.status_code == 404
    assert response.json() == {"detail": "Polling client not found"}
