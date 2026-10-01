"""Behavioral coverage for Sonar remediation error logging paths."""

import logging

import pytest

from services.api_gateway import circuit_breaker, service_health


@pytest.mark.asyncio
async def test_state_change_callback_failure_does_not_break_circuit_transition(
    caplog,
):
    """A failing observer is logged while the circuit remains usable."""
    breaker = circuit_breaker.CircuitBreaker("coverage")

    async def failing_callback(*_args):
        raise RuntimeError("observer unavailable")

    breaker.on_state_change = failing_callback

    with caplog.at_level(logging.ERROR, logger=circuit_breaker.__name__):
        await breaker._attempt_reset()

    assert breaker.state is circuit_breaker.CircuitState.HALF_OPEN
    assert "State change notification failed" in caplog.text


@pytest.mark.asyncio
async def test_health_monitoring_loop_logs_unexpected_check_failure(monkeypatch, caplog):
    """A failed health-check pass is logged, and the next pass still runs."""
    manager = service_health.ServiceHealthManager()
    manager.is_monitoring = True
    manager.check_interval = 0
    passes = 0

    async def failing_then_stopping_check():
        nonlocal passes
        passes += 1
        if passes == 1:
            raise RuntimeError("health request failed")
        manager.is_monitoring = False

    monkeypatch.setattr(manager, "_check_all_services", failing_then_stopping_check)

    with caplog.at_level(logging.ERROR, logger=service_health.__name__):
        await manager._health_check_loop()

    assert "Health check pass failed" in caplog.text
    assert passes == 2
