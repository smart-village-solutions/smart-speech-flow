"""Behavioral coverage for Sonar remediation error logging paths."""

import asyncio
import logging

import pytest

from services.api_gateway import circuit_breaker, circuit_breaker_client, service_health


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "call_args"),
    [
        ("asr", (b"audio", "de", False)),
        ("translation", ("Hallo", "de", "en", False)),
        ("tts", ("Hallo", "de", "default", False)),
    ],
)
async def test_service_client_returns_fallback_when_service_call_fails(
    monkeypatch, caplog, service, call_args
):
    """Unexpected downstream failures are logged and converted to fallbacks."""
    client = circuit_breaker_client.CircuitBreakerServiceClient()

    async def ensure_session():
        return None

    async def failing_call(*_args):
        raise RuntimeError("downstream unavailable")

    async def fallback(failed_service, _request, error):
        return {"service": failed_service, "error": str(error), "fallback": True}

    monkeypatch.setattr(client, "_ensure_session", ensure_session)
    monkeypatch.setattr(
        circuit_breaker_client.service_health_manager, "call_service", failing_call
    )
    monkeypatch.setattr(
        circuit_breaker_client.graceful_degradation_manager,
        "handle_service_failure",
        fallback,
    )

    with caplog.at_level(logging.ERROR, logger=circuit_breaker_client.__name__):
        result = await getattr(client, f"call_{service}_service")(*call_args)

    assert result == {
        "service": service,
        "error": "downstream unavailable",
        "fallback": True,
    }
    log_names = {"asr": "ASR", "translation": "Translation", "tts": "TTS"}
    assert f"{log_names[service]} service request failed" in caplog.text


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
    """The background monitor contains a failed health-check iteration."""
    manager = service_health.ServiceHealthManager()
    manager.is_monitoring = True

    async def failing_check():
        raise RuntimeError("health request failed")

    monkeypatch.setattr(manager, "_check_all_services", failing_check)

    with caplog.at_level(logging.ERROR, logger=service_health.__name__):
        await manager._health_check_loop()

    assert "Health check loop failed" in caplog.text
