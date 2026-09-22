"""The breakers are singletons, so one test's failures must not reach the next.

These two tests are deliberately order-dependent: the first leaves a breaker
OPEN through the same factory the gateway uses, and the second asserts it
arrived closed. Without the autouse fixture in the root ``conftest.py`` the
second fails, and it fails only when run after the first -- which is exactly
the shape of bug the fixture exists to prevent.

The order is declaration order, which is what pytest gives us: no test
randomiser is installed, and ``pytest.ini`` sets ``--strict-markers``, so an
ordering mark would have to be registered before it meant anything. If a
randomiser is ever added, pin these two with it rather than deleting them.
"""

from __future__ import annotations

from services.api_gateway.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerFactory,
    CircuitState,
)
from services.api_gateway.graceful_degradation import (
    ServiceMode,
    graceful_degradation_manager,
)

SHARED_NAME = "isolation-probe"


def _shared_breaker():
    return CircuitBreakerFactory.get_circuit_breaker(
        SHARED_NAME, CircuitBreakerConfig(failure_threshold=2)
    )


def test_a_first_test_can_leave_a_breaker_open():
    breaker = _shared_breaker()

    breaker.record_failure("boom")
    breaker.record_failure("boom")

    assert breaker.state is CircuitState.OPEN
    assert breaker.health.total_requests == 2


def test_the_next_test_gets_a_closed_breaker():
    breaker = _shared_breaker()

    assert breaker.state is CircuitState.CLOSED, (
        "a previous test's failures leaked into this one; the autouse "
        "reset_circuit_breakers fixture in the root conftest.py is not running"
    )
    assert breaker.failure_count == 0
    assert breaker.health.total_requests == 0


def test_a_first_test_can_leave_the_degradation_mode_dirty():
    """Breaker transitions now move this singleton too, via #219's callback."""
    graceful_degradation_manager.apply_service_states(
        {"asr": True, "translation": True, "tts": False}
    )

    assert graceful_degradation_manager.current_mode is ServiceMode.DEGRADED
    assert graceful_degradation_manager.mode_history


def test_the_next_test_gets_a_clean_degradation_mode():
    assert graceful_degradation_manager.current_mode is ServiceMode.FULL, (
        "a previous test's outage leaked into this one; the autouse "
        "reset_circuit_breakers fixture is not resetting the degradation manager"
    )
    assert graceful_degradation_manager.mode_history == []


def test_a_first_test_can_leave_a_closed_loop_bound():
    """Binding a loop and closing it is what the mode-follows-breakers tests do."""
    import asyncio

    breaker = _shared_breaker()
    loop = asyncio.new_event_loop()
    breaker.bind_loop(loop)
    loop.close()

    assert breaker._notify_loop is loop


def test_the_next_test_gets_no_bound_loop():
    """_dispatch drops every transition onto a dead loop, silently."""
    breaker = _shared_breaker()

    assert breaker._notify_loop is None, (
        "a previous test's closed loop is still bound; transitions after this "
        "point are dropped with a log line and assertions pass by collection order"
    )
