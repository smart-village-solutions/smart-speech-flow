"""Regression tests for backend-core Sonar remediation."""

import importlib


class _Counter:
    def labels(self, **_labels):
        return self

    def inc(self):
        pass


def test_no_connection_broadcast_log_redacts_session_id(caplog):
    websocket = importlib.import_module("services.api_gateway.websocket")
    monitor = type("Monitor", (), {"broadcast_failure_total": _Counter()})()
    session_id = "session-secret-123"

    websocket.WebSocketManager._build_no_connection_broadcast_result(
        None,
        monitor,
        session_id,
        websocket.ClientType.ADMIN,
    )

    assert "Broadcast attempted without active connections" in caplog.text
    assert session_id not in caplog.text
