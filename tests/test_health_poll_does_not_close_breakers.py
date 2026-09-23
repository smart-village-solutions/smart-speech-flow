"""Health recovery must distinguish reachability from inference health.

This is the premise of #219 running in the direction that defeats it. The
poll drove the same breaker the pipeline drives, so a service that answered
`/health` while failing every transcription had its breaker reclosed by the
poll: open at t=0 on three failed inference calls, HALF_OPEN at t>=45 on the
next ping, CLOSED two pings later -- roughly every 75 seconds, for ever, with
no inference request having succeeded at any point.

When the health monitor itself opened a breaker during startup, though, a
subsequent run of successful health checks is the only recovery signal
available. That recovery must close the breaker and restore the dashboard
without allowing health checks to pardon an inference failure.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services.api_gateway.circuit_breaker import CircuitState
from services.api_gateway.graceful_degradation import ServiceMode, graceful_degradation_manager
from services.api_gateway.service_health import service_health_manager

SERVICE = "asr"


def _breaker():
    return service_health_manager.circuit_breakers[SERVICE]


def _open_on_inference(breaker) -> None:
    """Open the breaker the way the pipeline does."""
    for _ in range(breaker.config.failure_threshold):
        breaker.record_failure("inference failed")
    assert breaker.state is CircuitState.OPEN


async def _poll_once(payload=None):
    endpoint = service_health_manager.services[SERVICE]
    reply = payload if payload is not None else {"status_code": 200, "response_time": 0.01}
    with patch.object(
        service_health_manager, "_perform_health_request", new=AsyncMock(return_value=reply)
    ):
        await service_health_manager._check_service_health(SERVICE, endpoint)


async def _wait_for_mode(expected: ServiceMode) -> None:
    for _ in range(10):
        if graceful_degradation_manager.current_mode is expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"degradation mode did not become {expected.value}")


class TestASuccessfulPingProvesNothing:
    async def test_pings_never_close_a_breaker_the_pipeline_opened(self):
        breaker = _breaker()
        _open_on_inference(breaker)
        breaker.next_attempt_time = 0  # the recovery window has elapsed

        for _ in range(breaker.config.success_threshold + 3):
            await _poll_once()

        assert breaker.state is CircuitState.OPEN, (
            "health pings reclosed a breaker that inference opened; "
            "the poll is vouching for work it never did"
        )

    async def test_a_ping_still_reports_the_service_reachable(self):
        """The two facts are separate and both are worth showing."""
        breaker = _breaker()
        _open_on_inference(breaker)

        await _poll_once()

        assert service_health_manager.service_status[SERVICE].is_healthy is True
        assert breaker.state is CircuitState.OPEN

    async def test_a_later_failed_ping_does_not_make_inference_failure_health_recoverable(self):
        breaker = _breaker()
        endpoint = service_health_manager.services[SERVICE]
        _open_on_inference(breaker)

        with patch.object(
            service_health_manager,
            "_perform_health_request",
            new=AsyncMock(side_effect=OSError("connection refused")),
        ):
            await service_health_manager._check_service_health(SERVICE, endpoint)

        breaker.next_attempt_time = 0
        for _ in range(breaker.config.success_threshold):
            await _poll_once()

        assert breaker.state is CircuitState.OPEN

    async def test_an_async_inference_failure_does_not_make_health_recovery_eligible(self):
        breaker = _breaker()
        endpoint = service_health_manager.services[SERVICE]

        with patch.object(
            service_health_manager,
            "_perform_health_request",
            new=AsyncMock(side_effect=OSError("connection refused")),
        ):
            for _ in range(breaker.config.failure_threshold):
                await service_health_manager._check_service_health(SERVICE, endpoint)

        breaker.next_attempt_time = 0

        async def fail_inference():
            raise RuntimeError("model unavailable")

        with pytest.raises(RuntimeError, match="model unavailable"):
            await breaker.call(fail_inference)

        breaker.next_attempt_time = 0
        for _ in range(breaker.config.success_threshold):
            await _poll_once()

        assert breaker.state is CircuitState.OPEN

    async def test_a_successful_ping_records_no_traffic(self):
        breaker = _breaker()

        await _poll_once()

        assert breaker.health.total_requests == 0


class TestAFailedPingIsRealEvidence:
    async def test_failed_pings_open_the_breaker(self):
        """A service that cannot answer /health cannot serve inference either."""
        breaker = _breaker()
        endpoint = service_health_manager.services[SERVICE]

        with patch.object(
            service_health_manager,
            "_perform_health_request",
            new=AsyncMock(side_effect=OSError("connection refused")),
        ):
            for _ in range(breaker.config.failure_threshold):
                await service_health_manager._check_service_health(SERVICE, endpoint)

        assert breaker.state is CircuitState.OPEN
        assert service_health_manager.service_status[SERVICE].is_healthy is False

    async def test_successful_pings_close_a_breaker_opened_by_health_checks(self):
        """A startup outage must not keep a recovered service unavailable forever."""
        breaker = _breaker()
        endpoint = service_health_manager.services[SERVICE]

        with patch.object(
            service_health_manager,
            "_perform_health_request",
            new=AsyncMock(side_effect=OSError("connection refused")),
        ):
            for _ in range(breaker.config.failure_threshold):
                await service_health_manager._check_service_health(SERVICE, endpoint)

        assert breaker.state is CircuitState.OPEN
        breaker.next_attempt_time = 0

        for _ in range(breaker.config.success_threshold):
            await _poll_once()

        assert breaker.state is CircuitState.CLOSED

    async def test_an_inflight_inference_probe_blocks_health_from_closing_the_breaker(self):
        """A health poll cannot outrun a half-open inference probe that later fails."""
        breaker = _breaker()
        endpoint = service_health_manager.services[SERVICE]

        with patch.object(
            service_health_manager,
            "_perform_health_request",
            new=AsyncMock(side_effect=OSError("connection refused")),
        ):
            for _ in range(breaker.config.failure_threshold):
                await service_health_manager._check_service_health(SERVICE, endpoint)

        breaker.next_attempt_time = 0
        breaker.record_health_success()
        assert breaker.state is CircuitState.HALF_OPEN

        inference_started = asyncio.Event()
        release_inference = asyncio.Event()

        async def blocked_inference():
            inference_started.set()
            await release_inference.wait()
            raise RuntimeError("model unavailable")

        inference_task = asyncio.create_task(breaker.call(blocked_inference))
        await inference_started.wait()

        for _ in range(breaker.config.success_threshold - 1):
            breaker.record_health_success()

        release_inference.set()
        with pytest.raises(RuntimeError, match="model unavailable"):
            await inference_task

        assert breaker.state is CircuitState.OPEN

    async def test_an_abandoned_inference_probe_does_not_strand_health_recovery(self):
        """A timed-out half-open probe is retried as a fresh health recovery window."""
        breaker = _breaker()
        endpoint = service_health_manager.services[SERVICE]

        with patch.object(
            service_health_manager,
            "_perform_health_request",
            new=AsyncMock(side_effect=OSError("connection refused")),
        ):
            for _ in range(breaker.config.failure_threshold):
                await service_health_manager._check_service_health(SERVICE, endpoint)

        breaker.next_attempt_time = 0
        breaker.record_health_success()
        assert breaker.state is CircuitState.HALF_OPEN

        with breaker.guard():
            pass  # A synchronous caller deliberately sheds its admitted probe.

        breaker.next_attempt_time = 0
        breaker.record_health_success()
        assert breaker.state is CircuitState.OPEN

        breaker.next_attempt_time = 0
        for _ in range(breaker.config.success_threshold):
            breaker.record_health_success()

        assert breaker.state is CircuitState.CLOSED

    async def test_a_late_inference_probe_result_cannot_mutate_a_newer_recovery(self):
        """An expired probe outcome belongs to its original recovery window only."""
        breaker = _breaker()
        endpoint = service_health_manager.services[SERVICE]

        with patch.object(
            service_health_manager,
            "_perform_health_request",
            new=AsyncMock(side_effect=OSError("connection refused")),
        ):
            for _ in range(breaker.config.failure_threshold):
                await service_health_manager._check_service_health(SERVICE, endpoint)

        breaker.next_attempt_time = 0
        breaker.record_health_success()

        inference_started = asyncio.Event()
        release_inference = asyncio.Event()

        async def late_failure():
            inference_started.set()
            await release_inference.wait()
            raise RuntimeError("model unavailable")

        inference_task = asyncio.create_task(breaker.call(late_failure))
        await inference_started.wait()

        breaker.next_attempt_time = 0
        breaker.record_health_success()
        assert breaker.state is CircuitState.OPEN

        breaker.next_attempt_time = 0
        for _ in range(breaker.config.success_threshold):
            breaker.record_health_success()
        assert breaker.state is CircuitState.CLOSED

        release_inference.set()
        with pytest.raises(RuntimeError, match="model unavailable"):
            await inference_task

        assert breaker.state is CircuitState.CLOSED
        assert breaker.failure_count == 0

    async def test_health_recovery_restores_the_green_degradation_mode(self):
        breaker = _breaker()
        breaker.bind_loop()
        endpoint = service_health_manager.services[SERVICE]

        with patch.object(
            service_health_manager,
            "_perform_health_request",
            new=AsyncMock(side_effect=OSError("connection refused")),
        ):
            for _ in range(breaker.config.failure_threshold):
                await service_health_manager._check_service_health(SERVICE, endpoint)

        await _wait_for_mode(ServiceMode.DEGRADED)

        breaker.next_attempt_time = 0
        for _ in range(breaker.config.success_threshold):
            await _poll_once()

        await _wait_for_mode(ServiceMode.FULL)


class TestHalfOpenIsNotFullService:
    """A breaker mid-probe has not verified anything yet."""

    @pytest.fixture(autouse=True)
    def restore_mode(self):
        yield
        graceful_degradation_manager.current_mode = ServiceMode.FULL
        graceful_degradation_manager.mode_history.clear()

    async def test_a_half_open_breaker_does_not_report_full_service(self):
        """Through the real callback, not a reimplementation of its mapping."""
        breaker = _breaker()
        _open_on_inference(breaker)
        breaker.next_attempt_time = 0
        with breaker.guard():
            pass
        assert breaker.state is CircuitState.HALF_OPEN

        await service_health_manager._on_circuit_state_change(
            SERVICE, CircuitState.OPEN, CircuitState.HALF_OPEN, breaker.health
        )

        assert (
            graceful_degradation_manager.current_mode is ServiceMode.DEGRADED
        ), "a breaker still probing was reported as full service"
