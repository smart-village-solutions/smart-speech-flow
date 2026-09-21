"""One path for every ASR, translation and TTS call, with the breaker live.

The point of #219 is that breaker state should describe real traffic. These
tests pin what counts as traffic and what counts as a fault, because the two
are not the same: a service can answer correctly and still be refusing work.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
import requests

from services.api_gateway import ai_service_client
from services.api_gateway.circuit_breaker import CircuitBreakerOpenError, CircuitState


class FakeResponse:
    """Enough of ``requests.Response`` for the client's decision."""

    def __init__(self, status_code: int, headers: dict | None = None):
        self.status_code = status_code
        self.headers = headers or {}


def _breaker(service: str = "asr"):
    return ai_service_client.breaker_for(service)


def _post(status_code: int, headers: dict | None = None, service: str = "asr"):
    response = FakeResponse(status_code, headers)
    with patch.object(ai_service_client.requests, "post", return_value=response) as post:
        returned = ai_service_client.call_ai_service(
            service, "http://asr:8000/transcribe", json={"a": 1}, timeout=60
        )
    return returned, post


class TestOutcomeRecording:
    def test_a_2xx_is_recorded_as_a_success(self):
        breaker = _breaker()

        returned, _ = _post(200)

        assert returned.status_code == 200
        assert breaker.health.successful_requests == 1
        assert breaker.health.failed_requests == 0

    def test_a_5xx_is_recorded_as_a_failure_and_still_returned(self):
        breaker = _breaker()

        returned, _ = _post(500)

        assert returned.status_code == 500, "the caller still classifies the reply"
        assert breaker.health.failed_requests == 1

    def test_a_4xx_is_not_a_service_fault(self):
        """The service is healthy and rejecting a bad request."""
        breaker = _breaker()

        _post(422)

        assert breaker.health.failed_requests == 0
        assert breaker.health.successful_requests == 1

    def test_a_transport_error_is_a_failure_and_propagates(self):
        breaker = _breaker()

        with patch.object(
            ai_service_client.requests,
            "post",
            side_effect=requests.ConnectionError("no route to host"),
        ):
            with pytest.raises(requests.ConnectionError):
                ai_service_client.call_ai_service("asr", "http://asr:8000/transcribe", timeout=60)

        assert breaker.health.failed_requests == 1

    def test_a_timeout_is_a_failure_and_propagates(self):
        breaker = _breaker()

        with patch.object(
            ai_service_client.requests,
            "post",
            side_effect=requests.Timeout("timed out"),
        ):
            with pytest.raises(requests.Timeout):
                ai_service_client.call_ai_service("asr", "http://asr:8000/transcribe", timeout=60)

        assert breaker.health.failed_requests == 1


class TestDeliberateShedding:
    """#190 sheds load with 503 + Retry-After. Breaking on that makes it worse."""

    def test_a_503_with_retry_after_records_no_outcome(self):
        """Not a fault -- and not a success either, because nothing was served.

        Recording a shed as a success is the tempting shortcut and it is wrong
        in both directions; the next two tests are the directions.
        """
        breaker = _breaker("translation")

        returned, _ = _post(503, {"Retry-After": "5"}, service="translation")

        assert returned.status_code == 503
        assert breaker.health.failed_requests == 0
        assert breaker.health.successful_requests == 0
        assert breaker.health.total_requests == 0

    def test_repeated_shedding_never_opens_the_circuit(self):
        breaker = _breaker("translation")

        for _ in range(10):
            _post(503, {"Retry-After": "5"}, service="translation")

        assert breaker.state is CircuitState.CLOSED

    def test_shedding_does_not_clear_accumulated_failures(self):
        """A service alternating real faults with shed load must still open.

        A success resets ``failure_count`` while the circuit is CLOSED, so if a
        shed counted as one, a half-broken service that sheds between its 500s
        would never reach the threshold and the breaker would never open.
        """
        breaker = _breaker("translation")

        for _ in range(breaker.config.failure_threshold - 1):
            _post(500, service="translation")
            _post(503, {"Retry-After": "5"}, service="translation")

        assert breaker.state is CircuitState.CLOSED, "opened before the threshold"

        _post(500, service="translation")

        assert breaker.state is CircuitState.OPEN

    def test_shedding_does_not_close_a_half_open_circuit(self):
        """Nothing was served, so nothing shows the service has recovered."""
        breaker = _breaker("translation")
        for _ in range(breaker.config.failure_threshold):
            breaker.record_failure("forced open by test")
        breaker.next_attempt_time = time.time() - 1

        for _ in range(breaker.config.success_threshold + 1):
            _post(503, {"Retry-After": "5"}, service="translation")

        assert breaker.state is CircuitState.HALF_OPEN

    def test_shedding_does_not_enter_the_latency_average(self):
        """A refusal costs microseconds and would flatter /api/health/services."""
        breaker = _breaker("translation")
        _post(200, service="translation")
        served = breaker.health.average_response_time

        for _ in range(5):
            _post(503, {"Retry-After": "5"}, service="translation")

        assert breaker.health.average_response_time == served

    def test_a_503_without_retry_after_is_an_ordinary_fault(self):
        breaker = _breaker("translation")

        _post(503, service="translation")

        assert breaker.health.failed_requests == 1

    def test_an_unparseable_retry_after_is_an_ordinary_fault(self):
        breaker = _breaker("translation")

        _post(503, {"Retry-After": "soon"}, service="translation")

        assert breaker.health.failed_requests == 1


class TestOpenCircuit:
    def test_an_open_circuit_sends_no_request(self):
        breaker = _breaker("tts")
        for _ in range(breaker.config.failure_threshold):
            breaker.record_failure("boom")
        assert breaker.state is CircuitState.OPEN

        with patch.object(ai_service_client.requests, "post") as post:
            with pytest.raises(CircuitBreakerOpenError):
                ai_service_client.call_ai_service(
                    "tts", "http://tts:8000/synthesize", json={}, timeout=45
                )

        post.assert_not_called()

    def test_the_error_carries_the_wait_the_caller_must_report(self):
        breaker = _breaker("tts")
        for _ in range(breaker.config.failure_threshold):
            breaker.record_failure("boom")

        with pytest.raises(CircuitBreakerOpenError) as caught:
            ai_service_client.call_ai_service(
                "tts", "http://tts:8000/synthesize", json={}, timeout=45
            )

        assert caught.value.retry_after_seconds >= 1
        assert caught.value.service_name == "tts"

    def test_enough_failures_open_the_circuit_through_this_path(self):
        breaker = _breaker("asr")

        for _ in range(breaker.config.failure_threshold):
            _post(500)

        assert breaker.state is CircuitState.OPEN


class TestItUsesTheRegisteredBreakers:
    def test_the_breaker_is_the_one_the_status_routes_report(self):
        """A private breaker would leave /api/health/services describing nothing."""
        from services.api_gateway.service_health import service_health_manager

        for service in ("asr", "translation", "tts"):
            assert (
                ai_service_client.breaker_for(service)
                is service_health_manager.circuit_breakers[service]
            )

    def test_an_unknown_service_is_a_programming_error(self):
        with pytest.raises(KeyError):
            ai_service_client.breaker_for("nope")


class TestItDoesNotImposeTheHealthCheckTimeout:
    def test_the_call_timeout_is_the_callers(self):
        """``config.timeout`` is the /health budget: 8-10s against 60s inference."""
        breaker = _breaker("asr")
        assert breaker.config.timeout <= 10.0

        with patch.object(
            ai_service_client.requests, "post", return_value=FakeResponse(200)
        ) as post:
            ai_service_client.call_ai_service(
                "asr", "http://asr:8000/transcribe", files={"f": b""}, timeout=60
            )

        assert post.call_args.kwargs["timeout"] == 60
