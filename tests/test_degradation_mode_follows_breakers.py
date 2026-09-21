"""`/api/circuit-breaker/degradation-status` has to describe the live system.

Its mode used to be moved only by ``handle_service_failure``, which no
production code called, so the endpoint reported FULL for the life of the
process no matter what the services did. And the transition was a one-way
ratchet -- the recovery branch was a literal ``pass`` -- so the one thing that
could move it could never move it back.

The mode is now derived from breaker state, which means it recovers on its own.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from services.api_gateway.circuit_breaker import CircuitState
from services.api_gateway.graceful_degradation import ServiceMode, graceful_degradation_manager
from services.api_gateway.service_health import service_health_manager

ALL_SERVICES = ("asr", "translation", "tts")


@pytest.fixture(autouse=True)
def restore_mode():
    yield
    graceful_degradation_manager.current_mode = ServiceMode.FULL
    graceful_degradation_manager.mode_history.clear()


def _states(**overrides) -> dict:
    states = {name: True for name in ALL_SERVICES}
    states.update(overrides)
    return states


class TestTheModeIsDerived:
    def test_everything_up_is_full_service(self):
        graceful_degradation_manager.apply_service_states(_states())

        assert graceful_degradation_manager.current_mode is ServiceMode.FULL

    def test_one_service_down_is_degraded(self):
        graceful_degradation_manager.apply_service_states(_states(tts=False))

        assert graceful_degradation_manager.current_mode is ServiceMode.DEGRADED

    def test_two_services_down_is_minimal(self):
        graceful_degradation_manager.apply_service_states(_states(tts=False, translation=False))

        assert graceful_degradation_manager.current_mode is ServiceMode.MINIMAL

    def test_everything_down_is_offline(self):
        graceful_degradation_manager.apply_service_states({name: False for name in ALL_SERVICES})

        assert graceful_degradation_manager.current_mode is ServiceMode.OFFLINE

    def test_it_recovers(self):
        """The old ratchet could not do this; its recovery branch was `pass`."""
        graceful_degradation_manager.apply_service_states(_states(tts=False))
        assert graceful_degradation_manager.current_mode is ServiceMode.DEGRADED

        graceful_degradation_manager.apply_service_states(_states())

        assert graceful_degradation_manager.current_mode is ServiceMode.FULL

    def test_a_change_is_recorded_in_the_history(self):
        graceful_degradation_manager.apply_service_states(_states(asr=False))

        last = graceful_degradation_manager.mode_history[-1]
        assert last["old_mode"] == "full"
        assert last["new_mode"] == "degraded"
        assert "asr" in last["trigger_service"]

    def test_no_change_writes_no_history(self):
        graceful_degradation_manager.apply_service_states(_states())
        graceful_degradation_manager.apply_service_states(_states())

        assert graceful_degradation_manager.mode_history == []

    def test_the_status_endpoint_payload_carries_the_mode(self):
        graceful_degradation_manager.apply_service_states(_states(tts=False))

        status = graceful_degradation_manager.get_degradation_status()

        assert status["current_mode"] == "degraded"


class TestItFollowsRealBreakers:
    """The wiring, not just the calculation."""

    @pytest.fixture
    def running_loop(self):
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            yield loop
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            loop.close()

    @staticmethod
    def _wait_for(predicate, timeout: float = 5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("the degradation mode never followed the breaker")

    def test_opening_a_breaker_degrades_the_reported_mode(self, running_loop):
        breaker = service_health_manager.circuit_breakers["tts"]
        breaker.bind_loop(running_loop)

        for _ in range(breaker.config.failure_threshold):
            breaker.record_failure("forced open by test")
        assert breaker.state is CircuitState.OPEN

        self._wait_for(lambda: graceful_degradation_manager.current_mode is ServiceMode.DEGRADED)

    def test_closing_it_again_restores_full_service(self, running_loop):
        breaker = service_health_manager.circuit_breakers["tts"]
        breaker.bind_loop(running_loop)

        for _ in range(breaker.config.failure_threshold):
            breaker.record_failure("forced open by test")
        self._wait_for(lambda: graceful_degradation_manager.current_mode is ServiceMode.DEGRADED)

        breaker.next_attempt_time = time.time() - 1
        with breaker.guard():
            pass
        for _ in range(breaker.config.success_threshold):
            breaker.record_success(0.01)
        assert breaker.state is CircuitState.CLOSED

        self._wait_for(lambda: graceful_degradation_manager.current_mode is ServiceMode.FULL)

    def test_an_admin_reset_also_restores_the_mode(self, running_loop):
        """An operator closing a breaker by hand must not leave a stale mode.

        ``reset()`` is reachable from ``/api/admin/circuit-breakers/{name}/reset``
        and closes the circuit without going through the failure path, so it has
        to announce the transition like any other.
        """
        breaker = service_health_manager.circuit_breakers["tts"]
        breaker.bind_loop(running_loop)

        for _ in range(breaker.config.failure_threshold):
            breaker.record_failure("forced open by test")
        self._wait_for(lambda: graceful_degradation_manager.current_mode is ServiceMode.DEGRADED)

        breaker.reset()

        assert breaker.state is CircuitState.CLOSED
        self._wait_for(lambda: graceful_degradation_manager.current_mode is ServiceMode.FULL)
