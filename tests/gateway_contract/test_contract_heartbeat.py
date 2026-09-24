"""The WebSocket heartbeat as a client sees it: pings, pongs and the timeout close.

The intervals are shortened on this test's WebSocket manager; production pings
every 30 seconds and closes a socket after 60 seconds without a pong.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.gateway_contract.contract_support import ALLOWED_ORIGIN

ORIGIN = {"Origin": ALLOWED_ORIGIN}
TIMEOUT_SERIES = re.compile(
    r'^websocket_disconnects_total\{client_type="customer",'
    r'disconnect_reason="heartbeat_timeout"\} (\S+)$',
    re.MULTILINE,
)


@pytest.fixture
def fast_heartbeat(gateway_dependencies):
    manager = gateway_dependencies.websocket_manager
    manager.heartbeat_interval = 0.05
    manager.heartbeat_timeout = 1.0
    return manager


def _admin_socket(client, conversations, session_id: str):
    ticket = conversations.ticket(session_id)
    return client.websocket_connect(f"/ws/admin/{session_id}?ticket={ticket}", headers=ORIGIN)


def _ping(socket) -> dict[str, Any]:
    while True:
        frame: dict[str, Any] = socket.receive_json()
        if frame["type"] == "heartbeat_ping":
            return frame


def _settle(socket) -> None:
    """Read up to the answer to a malformed frame, which follows everything sent before."""
    socket.send_text("not json")
    while socket.receive_json()["type"] != "error":
        pass


def _health(client) -> dict[str, Any]:
    data: dict[str, Any] = client.get("/api/websocket/monitoring/health").json()["data"]
    return data


def _timeouts_counted(client) -> float:
    match = TIMEOUT_SERIES.search(client.get("/metrics").text)
    return float(match.group(1)) if match else 0.0


def test_the_ack_announces_the_interval_and_pings_follow_it(client, conversations, fast_heartbeat):
    session_id = conversations.create()

    with _admin_socket(client, conversations, session_id) as socket:
        ack = socket.receive_json()
        first = _ping(socket)
        second = _ping(socket)

    assert ack["heartbeat_interval"] == 0.05
    for ping in (first, second):
        assert set(ping) == {"type", "ping_id", "timestamp"}
        assert re.fullmatch(r"[0-9a-f]{32}", ping["ping_id"])
    assert first["ping_id"] != second["ping_id"]


def test_a_pong_marks_the_connection_healthy(client, conversations, fast_heartbeat):
    session_id = conversations.create()

    with _admin_socket(client, conversations, session_id) as socket:
        socket.receive_json()
        before = _health(client)
        ping = _ping(socket)
        socket.send_json({"type": "heartbeat_pong", "ping_id": ping["ping_id"]})
        _settle(socket)
        after = _health(client)

    assert after["healthy_connections"] == before["healthy_connections"] + 1
    assert after["active_connections"] == before["active_connections"]


def test_a_pong_without_a_ping_id_also_counts_as_a_heartbeat(client, conversations, fast_heartbeat):
    session_id = conversations.create()

    with _admin_socket(client, conversations, session_id) as socket:
        socket.receive_json()
        before = _health(client)
        socket.send_json({"type": "heartbeat_pong"})
        _settle(socket)
        after = _health(client)

    assert after["healthy_connections"] == before["healthy_connections"] + 1


def test_a_silent_socket_is_closed_and_its_peer_told(client, conversations, fast_heartbeat):
    session_id = conversations.create()
    conversations.activate(session_id, "en")
    counted_before = _timeouts_counted(client)

    with _admin_socket(client, conversations, session_id) as admin:
        admin.receive_json()
        with client.websocket_connect(f"/ws/customer/{session_id}", headers=ORIGIN) as customer:
            customer.receive_json()
            while True:
                frame = admin.receive_json()
                if frame["type"] == "heartbeat_ping":
                    admin.send_json({"type": "heartbeat_pong", "ping_id": frame["ping_id"]})
                elif frame["type"] == "client_left":
                    left = frame
                    break

            frames = []
            with pytest.raises(WebSocketDisconnect) as closed:
                while True:
                    frames.append(customer.receive_json())
        # The admin kept answering, so it is still connected.
        _settle(admin)

    status = [frame for frame in frames if frame["type"] != "heartbeat_ping"]
    assert len(status) == 1
    assert set(status[0]) == {"type", "status", "reason", "timestamp"}
    assert (status[0]["type"], status[0]["status"], status[0]["reason"]) == (
        "connection_status",
        "disconnecting",
        "heartbeat_timeout",
    )
    assert (closed.value.code, closed.value.reason) == (1001, "heartbeat_timeout")
    assert (left["client_type"], left["reason"]) == ("customer", "heartbeat_timeout")
    assert _timeouts_counted(client) == counted_before + 1
