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
from services.api_gateway.service_health import ServiceHealthManager
from services.api_gateway.speech_services import HttpSpeechServices


class FakeResponse:
    """Enough of ``requests.Response`` for the client's decision."""

    def __init__(self, status_code: int, headers: dict | None = None):
        self.status_code = status_code
        self.headers = headers or {}


@pytest.fixture
def breakers():
    """One app's breakers, as its health manager registers them."""
    return ServiceHealthManager().circuit_breakers


def _post(breakers, status_code: int, headers: dict | None = None, service: str = "asr"):
    response = FakeResponse(status_code, headers)
    with patch.object(ai_service_client.requests, "post", return_value=response) as post:
        returned = ai_service_client.call_ai_service(
            breakers[service], "http://asr:8000/transcribe", json={"a": 1}, timeout=60
        )
    return returned, post


class TestOutcomeRecording:
    def test_a_2xx_is_recorded_as_a_success(self, breakers):
        breaker = breakers["asr"]

        returned, _ = _post(breakers, 200)

        assert returned.status_code == 200
        assert breaker.health.successful_requests == 1
        assert breaker.health.failed_requests == 0

    def test_a_5xx_is_recorded_as_a_failure_and_still_returned(self, breakers):
        breaker = breakers["asr"]

        returned, _ = _post(breakers, 500)

        assert returned.status_code == 500, "the caller still classifies the reply"
        assert breaker.health.failed_requests == 1

    def test_a_4xx_is_not_a_service_fault(self, breakers):
        """The service is healthy and rejecting a bad request."""
        breaker = breakers["asr"]

        _post(breakers, 422)

        assert breaker.health.failed_requests == 0
        assert breaker.health.successful_requests == 1

    def test_a_transport_error_is_a_failure_and_propagates(self, breakers):
        breaker = breakers["asr"]

        with patch.object(
            ai_service_client.requests,
            "post",
            side_effect=requests.ConnectionError("no route to host"),
        ):
            with pytest.raises(requests.ConnectionError):
                ai_service_client.call_ai_service(
                    breakers["asr"], "http://asr:8000/transcribe", timeout=60
                )

        assert breaker.health.failed_requests == 1

    def test_a_timeout_is_a_failure_and_propagates(self, breakers):
        breaker = breakers["asr"]

        with patch.object(
            ai_service_client.requests,
            "post",
            side_effect=requests.Timeout("timed out"),
        ):
            with pytest.raises(requests.Timeout):
                ai_service_client.call_ai_service(
                    breakers["asr"], "http://asr:8000/transcribe", timeout=60
                )

        assert breaker.health.failed_requests == 1

    def test_a_late_synchronous_probe_result_cannot_mutate_a_newer_recovery(self, breakers):
        """Outcome classification stays inside ``guard()``'s probe generation."""
        breaker = breakers["asr"]
        for _ in range(breaker.config.failure_threshold):
            breaker.record_health_failure("health endpoint unavailable")
        breaker.next_attempt_time = 0
        breaker.record_health_success()
        assert breaker.state is CircuitState.HALF_OPEN

        class LateFaultResponse:
            headers: dict = {}
            triggered = False

            @property
            def status_code(self) -> int:
                if not self.triggered:
                    self.triggered = True
                    breaker.next_attempt_time = 0
                    breaker.record_health_success()
                    assert breaker.state is CircuitState.OPEN
                    breaker.next_attempt_time = 0
                    for _ in range(breaker.config.success_threshold):
                        breaker.record_health_success()
                    assert breaker.state is CircuitState.CLOSED
                return 500

        with patch.object(ai_service_client.requests, "post", return_value=LateFaultResponse()):
            ai_service_client.call_ai_service(
                breakers["asr"], "http://asr:8000/transcribe", timeout=60
            )

        assert breaker.state is CircuitState.CLOSED
        assert breaker.failure_count == 0


class TestDeliberateShedding:
    """#190 sheds load with 503 + Retry-After. Breaking on that makes it worse."""

    def test_a_503_with_retry_after_records_no_outcome(self, breakers):
        """Not a fault -- and not a success either, because nothing was served.

        Recording a shed as a success is the tempting shortcut and it is wrong
        in both directions; the next two tests are the directions.
        """
        breaker = breakers["translation"]

        returned, _ = _post(breakers, 503, {"Retry-After": "5"}, service="translation")

        assert returned.status_code == 503
        assert breaker.health.failed_requests == 0
        assert breaker.health.successful_requests == 0
        assert breaker.health.total_requests == 0

    def test_repeated_shedding_never_opens_the_circuit(self, breakers):
        breaker = breakers["translation"]

        for _ in range(10):
            _post(breakers, 503, {"Retry-After": "5"}, service="translation")

        assert breaker.state is CircuitState.CLOSED

    def test_shedding_does_not_clear_accumulated_failures(self, breakers):
        """A service alternating real faults with shed load must still open.

        A success resets ``failure_count`` while the circuit is CLOSED, so if a
        shed counted as one, a half-broken service that sheds between its 500s
        would never reach the threshold and the breaker would never open.
        """
        breaker = breakers["translation"]

        for _ in range(breaker.config.failure_threshold - 1):
            _post(breakers, 500, service="translation")
            _post(breakers, 503, {"Retry-After": "5"}, service="translation")

        assert breaker.state is CircuitState.CLOSED, "opened before the threshold"

        _post(breakers, 500, service="translation")

        assert breaker.state is CircuitState.OPEN

    def test_shedding_does_not_close_a_half_open_circuit(self, breakers):
        """Nothing was served, so nothing shows the service has recovered."""
        breaker = breakers["translation"]
        for _ in range(breaker.config.failure_threshold):
            breaker.record_failure("forced open by test")
        breaker.next_attempt_time = time.time() - 1

        _post(breakers, 503, {"Retry-After": "5"}, service="translation")

        assert breaker.state is CircuitState.HALF_OPEN
        assert breaker.health.successful_requests == 0

    def test_a_shed_probe_does_not_turn_the_breaker_into_a_no_op(self, breakers):
        """Recording nothing must not also mean gating nothing.

        The probe reported no outcome, so the slot stays reserved and the next
        caller waits out the window instead of streaming through a service
        that has told us it cannot cope.
        """
        breaker = breakers["translation"]
        for _ in range(breaker.config.failure_threshold):
            breaker.record_failure("forced open by test")
        breaker.next_attempt_time = time.time() - 1

        _post(breakers, 503, {"Retry-After": "5"}, service="translation")

        with pytest.raises(CircuitBreakerOpenError):
            _post(breakers, 503, {"Retry-After": "5"}, service="translation")

    def test_shedding_does_not_enter_the_latency_average(self, breakers):
        """A refusal costs microseconds and would flatter /api/health/services."""
        breaker = breakers["translation"]
        _post(breakers, 200, service="translation")
        served = breaker.health.average_response_time

        for _ in range(5):
            _post(breakers, 503, {"Retry-After": "5"}, service="translation")

        assert breaker.health.average_response_time == served

    def test_a_503_without_retry_after_is_an_ordinary_fault(self, breakers):
        breaker = breakers["translation"]

        _post(breakers, 503, service="translation")

        assert breaker.health.failed_requests == 1

    def test_an_unparseable_retry_after_is_an_ordinary_fault(self, breakers):
        breaker = breakers["translation"]

        _post(breakers, 503, {"Retry-After": "soon"}, service="translation")

        assert breaker.health.failed_requests == 1


class TestOpenCircuit:
    def test_an_open_circuit_sends_no_request(self, breakers):
        breaker = breakers["tts"]
        for _ in range(breaker.config.failure_threshold):
            breaker.record_failure("boom")
        assert breaker.state is CircuitState.OPEN

        with patch.object(ai_service_client.requests, "post") as post:
            with pytest.raises(CircuitBreakerOpenError):
                ai_service_client.call_ai_service(
                    breakers["tts"], "http://tts:8000/synthesize", json={}, timeout=45
                )

        post.assert_not_called()

    def test_the_error_carries_the_wait_the_caller_must_report(self, breakers):
        breaker = breakers["tts"]
        for _ in range(breaker.config.failure_threshold):
            breaker.record_failure("boom")

        with pytest.raises(CircuitBreakerOpenError) as caught:
            ai_service_client.call_ai_service(
                breakers["tts"], "http://tts:8000/synthesize", json={}, timeout=45
            )

        assert caught.value.retry_after_seconds >= 1
        assert caught.value.service_name == "tts"

    def test_enough_failures_open_the_circuit_through_this_path(self, breakers):
        breaker = breakers["asr"]

        for _ in range(breaker.config.failure_threshold):
            _post(breakers, 500)

        assert breaker.state is CircuitState.OPEN


class TestItUsesTheRegisteredBreakers:
    def test_the_breaker_is_the_one_the_status_routes_report(self, breakers):
        """A private breaker would leave /api/health/services describing nothing."""
        health = ServiceHealthManager()
        speech = HttpSpeechServices(health.circuit_breakers)

        audio = FakeResponse(200, {"content-type": "audio/wav"})
        with patch.object(ai_service_client.requests, "post", return_value=audio):
            speech.transcribe(b"", lang="de", debug=False)
            speech.translate({"text": "hallo"})
            speech.synthesize({"text": "hello"}, timeout=30)

        for service in ("asr", "translation", "tts"):
            assert health.circuit_breakers[service].health.successful_requests == 1, service

    def test_a_missing_breaker_is_a_programming_error(self):
        with pytest.raises(KeyError):
            HttpSpeechServices({})


class TestItDoesNotImposeTheHealthCheckTimeout:
    def test_the_call_timeout_is_the_callers(self, breakers):
        """``config.timeout`` is the /health budget: 8-10s against 60s inference."""
        breaker = breakers["asr"]
        assert breaker.config.timeout <= 10.0

        with patch.object(
            ai_service_client.requests, "post", return_value=FakeResponse(200)
        ) as post:
            ai_service_client.call_ai_service(
                breakers["asr"], "http://asr:8000/transcribe", files={"f": b""}, timeout=60
            )

        assert post.call_args.kwargs["timeout"] == 60


class TestAServedReplyIsMoreThanAStatusCode:
    """A 200 can still carry a failure, and TTS has done exactly that.

    _finish_tts_stage fails a 200 whose content-type is not audio/wav, and
    message_telemetry records that shape as historically reachable. Classifying
    on the status code alone left the breaker CLOSED forever while every
    synthesis failed -- the blind spot #219 exists to close.
    """

    @staticmethod
    def _audio(response) -> bool:
        return getattr(response, "headers", {}).get("content-type") == "audio/wav"

    def _call(self, breakers, status_code, headers, *, served=None):
        response = FakeResponse(status_code, headers)
        with patch.object(ai_service_client.requests, "post", return_value=response):
            return ai_service_client.call_ai_service(
                breakers["tts"], "http://tts:8000/synthesize", served=served, timeout=30
            )

    def test_a_200_without_the_expected_payload_is_a_failure(self, breakers):
        breaker = breakers["tts"]

        self._call(breakers, 200, {"content-type": "application/json"}, served=self._audio)

        assert breaker.health.failed_requests == 1
        assert breaker.health.successful_requests == 0

    def test_a_200_carrying_the_payload_is_a_success(self, breakers):
        breaker = breakers["tts"]

        self._call(breakers, 200, {"content-type": "audio/wav"}, served=self._audio)

        assert breaker.health.successful_requests == 1
        assert breaker.health.failed_requests == 0

    def test_a_4xx_is_still_not_a_service_fault(self, breakers):
        """Bad client input must not open a breaker, predicate or not."""
        breaker = breakers["tts"]

        self._call(breakers, 422, {"content-type": "application/json"}, served=self._audio)

        assert breaker.health.failed_requests == 0

    def test_without_a_predicate_the_status_code_still_decides(self, breakers):
        breaker = breakers["tts"]

        self._call(breakers, 200, {"content-type": "application/json"})

        assert breaker.health.successful_requests == 1
