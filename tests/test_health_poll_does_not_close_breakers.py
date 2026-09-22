"""A health ping must not vouch for inference.

This is the premise of #219 running in the direction that defeats it. The
poll drove the same breaker the pipeline drives, so a service that answered
`/health` while failing every transcription had its breaker reclosed by the
poll: open at t=0 on three failed inference calls, HALF_OPEN at t>=45 on the
next ping, CLOSED two pings later -- roughly every 75 seconds, for ever, with
no inference request having succeeded at any point.

The exponential backoff could not accumulate either, because `_open_circuit`
only multiplies the recovery timeout on a HALF_OPEN -> OPEN transition and
`_close_circuit` resets it.
"""

from __future__ import annotations

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
