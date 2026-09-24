"""The monitor's connection and disconnect accounting must match the sockets.

The monitor never saw a heartbeat, so its five-minute cleanup treated every
connection older than 300 s as stale and recorded a heartbeat_timeout for a
socket that was still open. The real close then found no record and was lost.
That inflated the WebSocketConnectionFailures alert and truncated R2 and R4.
"""

import asyncio
from datetime import timedelta

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway import websocket as ws
from services.api_gateway import websocket_monitor as wm
from tests.realtime_sessions import open_session, tenant_session_manager

CLIENT = ws.ClientType.CUSTOMER.value


class _Socket:
    def __init__(self):
        self.sent = []
        self.client_state = type("State", (), {"DISCONNECTED": "DISCONNECTED"})()

    async def accept(self):
        pass

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        self.client_state = self.client_state.DISCONNECTED


@pytest.fixture
def registry():
    return CollectorRegistry()


@pytest.fixture
def monitor(monkeypatch, registry):
    real = wm.WebSocketMonitor(registry=registry)
    monkeypatch.setattr(ws, "get_websocket_monitor", lambda: real)
    return real


@pytest.fixture
def manager(monkeypatch, monitor):
    sessions = tenant_session_manager()
    open_session(sessions, "session-1")
    real = ws.WebSocketManager(sessions)

    async def no_heartbeat_loop():
        return None

    monkeypatch.setattr(real, "start_heartbeat_system", no_heartbeat_loop)
    return real


async def _connect(manager) -> str:
    key = next(iter(manager.session_manager.sessions))
    return await manager.connect_websocket(_Socket(), key, ws.ClientType.CUSTOMER)


def _age(manager, monitor, connection_id: str, seconds: int) -> None:
    earlier = wm.utc_now() - timedelta(seconds=seconds)
    monitor._active_connections[connection_id].connect_time = earlier
    manager.all_connections[connection_id].connected_at = earlier


async def _run_one_cleanup(monitor, manager, monkeypatch) -> None:
    calls = {"count": 0}

    async def one_pass(_seconds):
        calls["count"] += 1
        if calls["count"] > 1:
            raise asyncio.CancelledError()

    # wm.asyncio is the asyncio module itself, so the patch must not outlive
    # the pass: the manager's close path sleeps too.
    with monkeypatch.context() as patch, pytest.raises(asyncio.CancelledError):
        patch.setattr(wm.asyncio, "sleep", one_pass)
        await monitor.periodic_cleanup(lambda: manager.all_connections.keys())


def _disconnects(registry, reason: str) -> float:
    value = registry.get_sample_value(
        "websocket_disconnects_total",
        {"client_type": CLIENT, "disconnect_reason": reason},
    )
    return value or 0.0


def _active(registry) -> float:
    return registry.get_sample_value("websocket_connections_active", {"client_type": CLIENT})


def _duration_sum(registry, reason: str) -> float:
    value = registry.get_sample_value(
        "websocket_connection_duration_seconds_sum",
        {"client_type": CLIENT, "disconnect_reason": reason},
    )
    return value or 0.0


async def test_a_long_conversation_that_answers_pings_is_not_a_heartbeat_timeout(
    manager, monitor, registry, monkeypatch
):
    connection_id = await _connect(manager)
    _age(manager, monitor, connection_id, 400)
    await manager._send_heartbeat_pings()
    await manager.handle_websocket_message(connection_id, {"type": "heartbeat_pong"})

    await _run_one_cleanup(monitor, manager, monkeypatch)

    assert _disconnects(registry, "heartbeat_timeout") == 0
    assert _active(registry) == 1
    assert connection_id in monitor.get_active_connections()


async def test_a_connection_that_stops_answering_counts_once_as_heartbeat_timeout(
    manager, monitor, registry, monkeypatch
):
    connection_id = await _connect(manager)
    manager.all_connections[connection_id].last_heartbeat = ws.utc_now() - timedelta(
        seconds=manager.heartbeat_timeout + 1
    )

    await manager._check_heartbeat_timeouts()
    # The endpoint's finally block runs once the closed socket raises.
    await manager.disconnect_websocket(connection_id, "client_disconnect")
    await _run_one_cleanup(monitor, manager, monkeypatch)

    assert _disconnects(registry, "heartbeat_timeout") == 1
    assert _disconnects(registry, "client_disconnect") == 0
    assert _active(registry) == 0


async def test_a_real_close_after_five_minutes_is_counted_with_its_full_duration(
    manager, monitor, registry, monkeypatch
):
    connection_id = await _connect(manager)
    _age(manager, monitor, connection_id, 400)

    await _run_one_cleanup(monitor, manager, monkeypatch)
    await manager.disconnect_websocket(connection_id, "connection_error")

    assert _disconnects(registry, "heartbeat_timeout") == 0
    assert _disconnects(registry, "connection_error") == 1
    assert _duration_sum(registry, "connection_error") >= 400
    assert _active(registry) == 0


def _latency_samples(registry) -> float:
    value = registry.get_sample_value(
        "websocket_heartbeat_latency_seconds_count", {"client_type": CLIENT}
    )
    return value or 0.0


def _last_ping_id(manager, connection_id: str) -> str:
    socket = manager.all_connections[connection_id].websocket
    (ping,) = [m for m in socket.sent if m.get("type") == "heartbeat_ping"][-1:]
    return ping["ping_id"]


async def test_a_pong_echoing_the_ping_reports_the_heartbeat_and_its_latency(
    manager, monitor, registry
):
    connection_id = await _connect(manager)

    await manager._send_heartbeat_pings()
    ping_id = _last_ping_id(manager, connection_id)
    await manager.handle_websocket_message(
        connection_id, {"type": "heartbeat_pong", "ping_id": ping_id}
    )

    assert monitor.get_active_connections()[connection_id].last_heartbeat is not None
    assert _latency_samples(registry) == 1


async def test_a_pong_that_does_not_echo_the_ping_records_no_latency(manager, monitor, registry):
    """The legacy client never answers a ping; both clients also send a pong
    on their own 30 s timer. Timing such a pong against the last ping measures
    the phase of two timers, not the network."""
    connection_id = await _connect(manager)

    await manager._send_heartbeat_pings()
    await manager.handle_websocket_message(connection_id, {"type": "heartbeat_pong"})
    await manager.handle_websocket_message(
        connection_id, {"type": "heartbeat_pong", "ping_id": "stale"}
    )

    assert monitor.get_active_connections()[connection_id].last_heartbeat is not None
    assert _latency_samples(registry) == 0


async def test_a_reply_that_beats_the_send_is_still_matched(manager, monitor, registry):
    """The receive loop can run while send_json is still awaiting."""
    connection_id = await _connect(manager)
    socket = manager.all_connections[connection_id].websocket

    async def send_and_answer_at_once(data):
        socket.sent.append(data)
        if data.get("type") == "heartbeat_ping":
            await manager.handle_websocket_message(
                connection_id, {"type": "heartbeat_pong", "ping_id": data["ping_id"]}
            )

    socket.send_json = send_and_answer_at_once
    await manager._send_heartbeat_pings()
    await manager.handle_websocket_message(connection_id, {"type": "heartbeat_pong"})

    assert _latency_samples(registry) == 1


async def test_a_record_the_manager_no_longer_holds_is_purged_without_a_disconnect(
    manager, monitor, registry, monkeypatch
):
    monitor.connection_established("orphan", "session-9", CLIENT)

    await _run_one_cleanup(monitor, manager, monkeypatch)

    assert "orphan" not in monitor.get_active_connections()
    assert _active(registry) == 0
    for reason in wm.DisconnectReason:
        assert _disconnects(registry, reason.value) == 0


async def test_a_cleanup_during_the_close_does_not_lose_the_disconnect(
    manager, monitor, registry, monkeypatch
):
    """The manager awaits the session manager mid-close; a purge can run there."""
    connection_id = await _connect(manager)
    original = manager.session_manager.remove_websocket_connection

    async def purge_then_remove(*args):
        monitor._purge_orphaned_records(manager.all_connections.keys())
        await original(*args)

    monkeypatch.setattr(manager.session_manager, "remove_websocket_connection", purge_then_remove)
    await manager.disconnect_websocket(connection_id, "connection_error")

    assert _disconnects(registry, "connection_error") == 1


def test_a_heartbeat_between_two_pings_is_healthy(monitor):
    """Pings go out every 30 s, so a 45 s old heartbeat is on schedule."""
    metrics = monitor.connection_established("connection-1", "session-1", CLIENT)
    metrics.last_heartbeat = wm.utc_now() - timedelta(seconds=45)

    health = monitor.get_health_status()

    assert health["status"] == "healthy"
    assert health["stale_connections"] == 0
