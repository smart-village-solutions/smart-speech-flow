"""One failed pass must not end a monitoring loop for the rest of the process (#230).

Both loops used to wrap `while` in their try, so the first unexpected error ended
heartbeats (until the next socket connected) or health polling (for good).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from services.api_gateway import realtime_heartbeat, service_health
from services.api_gateway.realtime_heartbeat import Heartbeat
from services.api_gateway.service_health import ServiceHealthManager


def _sleep_cancelling_on_call(number: int):
    calls = 0

    async def sleep(_seconds: float) -> None:
        nonlocal calls
        calls += 1
        if calls == number:
            raise asyncio.CancelledError  # how the lifespan stops the loop

    return sleep


def test_the_heartbeat_keeps_running_after_a_failed_pass(monkeypatch):
    heartbeat = Heartbeat(registry=Mock(), monitor=Mock(), closer=Mock())
    heartbeat.send_pings = AsyncMock(side_effect=[RuntimeError("one bad pass"), None])
    heartbeat.check_timeouts = AsyncMock()
    monkeypatch.setattr(realtime_heartbeat.asyncio, "sleep", _sleep_cancelling_on_call(3))

    loop = heartbeat.monitor_loop()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loop)

    assert heartbeat.send_pings.await_count == 2


def test_health_polling_keeps_running_after_a_failed_pass(monkeypatch):
    manager = ServiceHealthManager()
    manager.is_monitoring = True
    manager._check_all_services = AsyncMock(side_effect=[RuntimeError("one bad pass"), None, None])
    monkeypatch.setattr(service_health.asyncio, "sleep", _sleep_cancelling_on_call(3))

    loop = manager._health_check_loop()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loop)

    assert manager._check_all_services.await_count == 3
