"""One session, one session_ref, whichever component logs it.

Production leaves SSF_QUALITY_TELEMETRY_SESSION_KEY empty by default, so every
pseudonymizer built from the environment draws its own random key. The session
manager's telemetry and the WebSocket monitor's log lines only correlate when
they share one pseudonymizer.
"""

from __future__ import annotations

import logging

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway import websocket_monitor as monitor_module
from services.api_gateway.dependencies import build_gateway_dependencies
from services.api_gateway.session_pseudonym import SESSION_KEY_ENV
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

REVISION = f"sha256:{'a' * 64}"


class _LifecycleSpy:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def emit_session_lifecycle(self, **kwargs) -> None:
        self.calls.append(kwargs)


async def test_the_manager_and_the_monitor_agree_on_a_session_ref_without_a_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(SESSION_KEY_ENV, raising=False)
    monkeypatch.setattr(
        monitor_module,
        "websocket_monitor",
        monitor_module.WebSocketMonitor(registry=CollectorRegistry()),
    )
    dependencies = build_gateway_dependencies(prometheus_registry=CollectorRegistry())
    spy = _LifecycleSpy()
    dependencies.session_manager.attach_quality_telemetry(spy)
    session = await dependencies.session_manager.create_admin_session(
        "tenant-a", RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")
    )

    with caplog.at_level(logging.INFO, logger=monitor_module.__name__):
        dependencies.websocket_monitor.connection_established(
            "connection-1", session.id, "admin", resource_key=session.key
        )

    (record,) = [r for r in caplog.records if r.getMessage() == "websocket_connection_established"]
    assert spy.calls[0]["session_ref"] == record.session_ref
