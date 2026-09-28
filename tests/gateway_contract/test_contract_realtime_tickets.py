"""Realtime tickets: issue over HTTP, consume over WebSocket or polling."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.gateway_contract.contract_support import ALLOWED_ORIGIN, TENANT_A, TENANT_B

ORIGIN = {"Origin": ALLOWED_ORIGIN}


def _admin_socket(client, session_id: str, ticket: str):
    return client.websocket_connect(f"/ws/admin/{session_id}?ticket={ticket}", headers=ORIGIN)


def _close_code(client, session_id: str, ticket: str) -> tuple[int, str]:
    with pytest.raises(WebSocketDisconnect) as closed:
        with _admin_socket(client, session_id, ticket):
            pass
    return closed.value.code, closed.value.reason


def test_issued_ticket_has_exactly_ticket_and_a_sixty_second_expiry(
    client, conversations, realtime_tickets
):
    session_id = conversations.create()

    issued = client.post(
        f"/api/admin/session/{session_id}/realtime-ticket", json={"transport": "websocket"}
    )

    assert issued.status_code == 200
    body = issued.json()
    assert set(body) == {"ticket", "expires_at"}
    assert datetime.fromisoformat(body["expires_at"]) == realtime_tickets.clock.now + timedelta(
        seconds=60
    )


@pytest.mark.parametrize("body", [{"transport": "sse"}, {}])
def test_ticket_request_outside_the_transport_literal_is_unprocessable(client, conversations, body):
    session_id = conversations.create()

    response = client.post(f"/api/admin/session/{session_id}/realtime-ticket", json=body)

    assert response.status_code == 422


def test_ticket_is_single_use_on_the_admin_websocket(client, conversations):
    session_id = conversations.create()
    ticket = conversations.ticket(session_id)

    with _admin_socket(client, session_id, ticket) as socket:
        assert socket.receive_json()["type"] == "connection_ack"

    assert _close_code(client, session_id, ticket) == (4404, "Session not found")


def test_ticket_is_single_use_on_polling_activation(client, conversations):
    session_id = conversations.create()
    ticket = conversations.ticket(session_id, "polling")
    url = f"/api/admin/session/{session_id}/polling/activate"

    assert client.post(url, json={"ticket": ticket}).status_code == 200
    replay = client.post(url, json={"ticket": ticket})

    assert replay.status_code == 404
    assert replay.json() == {"detail": "Session not found"}


def test_expired_ticket_is_rejected_by_both_transports(client, conversations, realtime_tickets):
    session_id = conversations.create()
    websocket_ticket = conversations.ticket(session_id)
    polling_ticket = conversations.ticket(session_id, "polling")

    realtime_tickets.clock.advance(61)

    assert _close_code(client, session_id, websocket_ticket) == (4404, "Session not found")
    polled = client.post(
        f"/api/admin/session/{session_id}/polling/activate", json={"ticket": polling_ticket}
    )
    assert polled.status_code == 404


def test_ticket_within_its_lifetime_is_accepted(client, conversations, realtime_tickets):
    session_id = conversations.create()
    ticket = conversations.ticket(session_id)

    realtime_tickets.clock.advance(59)

    with _admin_socket(client, session_id, ticket) as socket:
        assert socket.receive_json()["type"] == "connection_ack"


def test_ticket_is_bound_to_its_transport(client, conversations):
    session_id = conversations.create()
    polling_ticket = conversations.ticket(session_id, "polling")
    websocket_ticket = conversations.ticket(session_id, "websocket")

    assert _close_code(client, session_id, polling_ticket) == (4404, "Session not found")
    polled = client.post(
        f"/api/admin/session/{session_id}/polling/activate", json={"ticket": websocket_ticket}
    )
    assert polled.status_code == 404


def test_a_rejected_ticket_is_spent(client, conversations):
    session_id = conversations.create()
    ticket = conversations.ticket(session_id, "polling")

    assert _close_code(client, session_id, ticket)[0] == 4404
    polled = client.post(
        f"/api/admin/session/{session_id}/polling/activate", json={"ticket": ticket}
    )

    assert polled.status_code == 404


def test_termination_revokes_outstanding_websocket_tickets(client, conversations):
    session_id = conversations.create()
    ticket = conversations.ticket(session_id)

    conversations.terminate(session_id)

    assert _close_code(client, session_id, ticket) == (4404, "Session not found")


def test_another_tenant_cannot_activate_polling_with_a_foreign_ticket(
    client, conversations, identity
):
    session_id = conversations.create(TENANT_A)
    ticket = conversations.ticket(session_id, "polling")

    identity.act_as(TENANT_B)
    response = client.post(
        f"/api/admin/session/{session_id}/polling/activate", json={"ticket": ticket}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}
    identity.act_as(TENANT_A)
    replay = client.post(
        f"/api/admin/session/{session_id}/polling/activate", json={"ticket": ticket}
    )
    assert replay.status_code == 200


def test_unavailable_ticket_store_fails_every_transport_as_unavailable(
    client, conversations, realtime_tickets
):
    session_id = conversations.create()
    polling_ticket = conversations.ticket(session_id, "polling")
    websocket_ticket = conversations.ticket(session_id)

    realtime_tickets.make_unavailable()

    issued = client.post(
        f"/api/admin/session/{session_id}/realtime-ticket", json={"transport": "websocket"}
    )
    assert issued.status_code == 503
    assert issued.json() == {"detail": "Realtime ticket service unavailable"}
    assert _close_code(client, session_id, websocket_ticket) == (
        1013,
        "Realtime service unavailable",
    )
    polled = client.post(
        f"/api/admin/session/{session_id}/polling/activate", json={"ticket": polling_ticket}
    )
    assert polled.status_code == 503
    assert polled.json() == {"detail": "Realtime ticket service unavailable"}
