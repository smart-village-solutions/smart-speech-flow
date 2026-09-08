"""A disconnect reason the code already knows must reach the monitor.

R2 (unexpected disconnect rate) and two alert rules filter on this label. While
every disconnect records `client_disconnect`, all three read zero forever.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from services.api_gateway.websocket_monitor import DisconnectReason

ALERT_RULES = Path(__file__).resolve().parents[1] / "monitoring" / "alert_rules.yml"


def _websocket_connection_failures_expr() -> str:
    groups = yaml.safe_load(ALERT_RULES.read_text())["groups"]
    group = next(g for g in groups if g["name"] == "websocket-health")
    rule = next(r for r in group["rules"] if r["alert"] == "WebSocketConnectionFailures")
    return rule["expr"]


def _excluded_disconnect_reasons() -> set[str]:
    """The alternation inside disconnect_reason!~"...": the label values
    treated as routine lifecycle and excluded from the failure rate.

    Parsed from the rule file rather than hardcoded, so an edit to the
    expression that is not reflected here fails this test instead of
    silently going stale.
    """
    match = re.search(r'disconnect_reason!~"([^"]+)"', _websocket_connection_failures_expr())
    assert match, "WebSocketConnectionFailures no longer filters on disconnect_reason"
    return set(match.group(1).split("|"))


class TestTheWireFormatMapsToTheEnum:
    @pytest.mark.parametrize(
        "wire,expected",
        [
            ("client_disconnect", DisconnectReason.CLIENT_DISCONNECT),
            ("heartbeat_timeout", DisconnectReason.HEARTBEAT_TIMEOUT),
            ("origin_not_allowed", DisconnectReason.ORIGIN_NOT_ALLOWED),
            ("no_connections", DisconnectReason.SERVER_DISCONNECT),
            ("session_timeout", DisconnectReason.SESSION_EXPIRED),
            ("manual_termination", DisconnectReason.SERVER_DISCONNECT),
            ("manual_admin_termination", DisconnectReason.SERVER_DISCONNECT),
        ],
    )
    def test_known_reasons_map(self, wire: str, expected: DisconnectReason):
        assert DisconnectReason.from_wire(wire) is expected

    def test_an_unknown_reason_is_not_silently_a_client_disconnect(self):
        """Counting an unknown cause as a clean client exit is the bug itself."""
        assert DisconnectReason.from_wire("something_new") is DisconnectReason.PROTOCOL_ERROR


class TestTheAlertsCanFire:
    def test_origin_not_allowed_is_a_real_enum_value(self):
        """alert_rules.yml:199 matches this label; the enum lacked the member."""
        assert DisconnectReason.ORIGIN_NOT_ALLOWED.value == "origin_not_allowed"

    def test_a_heartbeat_timeout_is_not_labelled_a_client_disconnect(self):
        """alert_rules.yml:159 filters reason!="client_disconnect"."""
        assert (
            DisconnectReason.from_wire("heartbeat_timeout").value != "client_disconnect"
        )


class TestTheReasonSurvivesCleanup:
    async def test_a_heartbeat_timeout_reaches_the_monitor(self, monkeypatch):
        from services.api_gateway import websocket as ws
        from services.api_gateway.session_manager import SessionManager

        recorded: list[DisconnectReason] = []

        class _Monitor:
            def connection_closed(self, connection_id, reason):
                recorded.append(reason)
                return None

        monkeypatch.setattr(ws, "get_websocket_monitor", lambda: _Monitor())

        manager = ws.WebSocketManager(SessionManager())
        connection_id = manager._build_connection_id("s1", ws.ClientType.CUSTOMER)
        manager.all_connections[connection_id] = ws.WebSocketConnection(
            websocket=Mock(),
            client_type=ws.ClientType.CUSTOMER,
            session_id="s1",
            connected_at=datetime.now(timezone.utc),
            last_heartbeat=datetime.now(timezone.utc),
            state=ws.ConnectionState.CONNECTED,
        )
        await manager._cleanup_connection(
            connection_id, DisconnectReason.HEARTBEAT_TIMEOUT
        )

        assert recorded == [DisconnectReason.HEARTBEAT_TIMEOUT]


class _RecordingMonitor:
    """Only the two calls these paths make; anything else is a test bug."""

    def __init__(self) -> None:
        self.closed: list[DisconnectReason] = []
        self.rejected: list[DisconnectReason] = []

    def connection_closed(self, connection_id, reason):
        self.closed.append(reason)
        return None

    def record_rejected_connection(self, reason):
        self.rejected.append(reason)


def _manager_with_one_connection(monkeypatch, monitor: _RecordingMonitor):
    from services.api_gateway import websocket as ws
    from services.api_gateway.session_manager import SessionManager

    monkeypatch.setattr(ws, "get_websocket_monitor", lambda: monitor)

    manager = ws.WebSocketManager(SessionManager())
    connection_id = manager._build_connection_id("s1", ws.ClientType.CUSTOMER)
    socket = Mock()
    socket.send_json = AsyncMock()
    socket.close = AsyncMock()
    connection = ws.WebSocketConnection(
        websocket=socket,
        client_type=ws.ClientType.CUSTOMER,
        session_id="s1",
        connected_at=datetime.now(timezone.utc),
        last_heartbeat=datetime.now(timezone.utc),
        state=ws.ConnectionState.CONNECTED,
    )
    manager.all_connections[connection_id] = connection
    manager.session_connections["s1"] = {connection_id: connection}
    return manager, connection_id


class TestTheReasonSurvivesTheCallOperatorsActuallyMake:
    """_cleanup_connection is the seam the fix edited; disconnect_websocket is
    the seam every caller uses. Dropping the argument at that call site passes
    a suite that only exercises the former."""

    async def test_a_heartbeat_timeout_reaches_the_monitor(self, monkeypatch):
        monitor = _RecordingMonitor()
        manager, connection_id = _manager_with_one_connection(monkeypatch, monitor)

        await manager.disconnect_websocket(connection_id, "heartbeat_timeout")

        assert monitor.closed == [DisconnectReason.HEARTBEAT_TIMEOUT]

    async def test_the_default_is_still_a_clean_client_exit(self, monkeypatch):
        monitor = _RecordingMonitor()
        manager, connection_id = _manager_with_one_connection(monkeypatch, monitor)

        await manager.disconnect_websocket(connection_id)

        assert monitor.closed == [DisconnectReason.CLIENT_DISCONNECT]


class TestASessionTerminationIsNotAFailure:
    """terminate_all_active_sessions(reason="new_session_created") runs on every
    new session. Recording those as CONNECTION_ERROR feeds routine traffic into
    a critical alert."""

    @pytest.mark.parametrize(
        "reason,expected",
        [
            ("session_timeout", DisconnectReason.SESSION_EXPIRED),
            ("new_session_created", DisconnectReason.SERVER_DISCONNECT),
            ("session_ended", DisconnectReason.SERVER_DISCONNECT),
        ],
    )
    async def test_the_termination_reason_reaches_the_monitor(
        self, monkeypatch, reason: str, expected: DisconnectReason
    ):
        monitor = _RecordingMonitor()
        manager, _ = _manager_with_one_connection(monkeypatch, monitor)

        await manager.handle_session_termination("s1", reason)

        assert monitor.closed == [expected]


class TestARejectedOriginIsCounted:
    """WebSocketOriginBlocked matches a counter nothing incremented before the
    rejection path started recording it."""

    async def test_the_rejection_increments_the_disconnect_counter(self, monkeypatch):
        from services.api_gateway import websocket as ws

        monitor = _RecordingMonitor()
        monkeypatch.setattr(ws, "get_websocket_monitor", lambda: monitor)

        async def deny(_origin):
            return False

        monkeypatch.setattr(ws, "validate_websocket_origin", deny)

        socket = Mock()
        socket.close = AsyncMock()

        await ws.websocket_endpoint(
            socket, "TEST1234", "admin", Mock(), "https://not-allowed.example"
        )

        assert monitor.rejected == [DisconnectReason.ORIGIN_NOT_ALLOWED]
        socket.close.assert_awaited_once()


class TestNormalSessionEndDoesNotPageWebSocketConnectionFailures:
    """The alert expression is now load-bearing on specific enum values: a
    reason that DisconnectReason.from_wire maps outside its exclusion list
    contributes to the failure rate and can page. An operator terminating a
    session (manual_termination, manual_admin_termination), a new session
    replacing an old one (new_session_created), a clean shutdown
    (session_ended) and a session ageing out (session_timeout) are all
    routine lifecycle, not connection failures."""

    @pytest.mark.parametrize(
        "wire_reason",
        [
            "new_session_created",
            "session_ended",
            "session_timeout",
            "manual_termination",
            "manual_admin_termination",
            "system_cleanup",
            "timeout",
        ],
    )
    def test_a_normal_session_end_reason_is_excluded(self, wire_reason: str):
        mapped = DisconnectReason.from_wire(wire_reason)
        assert mapped.value in _excluded_disconnect_reasons(), (
            f"{wire_reason!r} maps to {mapped.value!r}, which "
            "WebSocketConnectionFailures does not exclude -- it would page on "
            "routine session lifecycle"
        )

    def test_every_termination_reason_the_session_layer_can_name_is_excluded(self):
        """Enumerated from the enum, not listed by hand.

        The hand-written list above is what let system_cleanup -- a member of
        this closed enum and the default of terminate_all_active_sessions --
        map to PROTOCOL_ERROR and page critical for a deliberate operator
        action. A new member of SessionTerminationReason now fails here
        instead.
        """
        from services.api_gateway.quality_telemetry import SessionTerminationReason

        excluded = _excluded_disconnect_reasons()
        offenders = {}
        for reason in SessionTerminationReason:
            if reason in (
                SessionTerminationReason.NONE,
                SessionTerminationReason.OTHER,
            ):
                continue
            mapped = DisconnectReason.from_wire(reason.value)
            if mapped.value not in excluded:
                offenders[reason.value] = mapped.value

        assert not offenders, (
            f"deliberate session terminations mapping outside the exclusion "
            f"list: {offenders} -- each would contribute to "
            "WebSocketConnectionFailures and page critical"
        )

    def test_a_session_error_is_an_error_not_a_protocol_violation(self):
        """_get_termination_message carries "error"; it is a fault and must
        still page, but calling it a protocol violation misroutes triage."""
        assert DisconnectReason.from_wire("error") is DisconnectReason.CONNECTION_ERROR
        assert (
            DisconnectReason.CONNECTION_ERROR.value not in _excluded_disconnect_reasons()
        )

    def test_a_genuine_connection_error_still_pages(self):
        assert (
            DisconnectReason.CONNECTION_ERROR.value
            not in _excluded_disconnect_reasons()
        )


class TestOneCauseDoesNotRaiseTwoAlerts:
    """A blocked origin is a configuration problem with a purpose-built rule.
    Leaving it in the generic failure rate as well pages critical for the same
    cause the warning already covers, ten times less sensitively."""

    def test_a_blocked_origin_is_owned_by_its_own_rule(self):
        assert (
            DisconnectReason.ORIGIN_NOT_ALLOWED.value in _excluded_disconnect_reasons()
        ), (
            "origin_not_allowed contributes to WebSocketConnectionFailures "
            "(critical) as well as WebSocketOriginBlocked (warning)"
        )

    def test_the_dedicated_rule_still_matches_it(self):
        """Excluding it from the generic rule is only safe while this exists."""
        groups = yaml.safe_load(ALERT_RULES.read_text())["groups"]
        group = next(g for g in groups if g["name"] == "websocket-health")
        rule = next(r for r in group["rules"] if r["alert"] == "WebSocketOriginBlocked")

        assert 'disconnect_reason="origin_not_allowed"' in rule["expr"]
        assert rule["labels"]["severity"] == "warning"
