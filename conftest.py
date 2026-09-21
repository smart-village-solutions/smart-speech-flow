"""Test isolation that has to apply to every suite, not just ``tests/``.

Lives at the repository root so it also covers ``services/*/tests/``, which
``tests/conftest.py`` cannot reach.
"""

from __future__ import annotations

import pytest

from services.api_gateway.circuit_breaker import CircuitBreakerFactory, CircuitState, ServiceHealth


@pytest.fixture(autouse=True)
def reset_circuit_breakers():
    """Hands every test a set of breakers in their start-of-process state.

    The breakers are process-wide singletons (``CircuitBreakerFactory._instances``)
    and, since the pipeline calls through them, ordinary pipeline tests now move
    their state. Three failures in one test would otherwise leave a breaker OPEN
    and the next test would be refused before it sent a request -- a failure
    that depends on test order and reads as a bug in the code under test.

    Cleaning up afterwards rather than beforehand keeps a failing test's final
    breaker state visible while it is being debugged.

    ``CircuitBreaker.reset()`` is the admin reset and deliberately keeps the
    lifetime counters, which is right for an operator and wrong here, so the
    health record is replaced as well.
    """
    yield

    for circuit in CircuitBreakerFactory.get_all_circuits().values():
        pristine = (
            circuit.state is CircuitState.CLOSED
            and circuit.health.total_requests == 0
            and circuit.failure_count == 0
        )
        if pristine:
            # Skipping the common case keeps ~2000 tests from each logging a
            # manual-reset warning they did not cause.
            continue
        circuit.reset()
        circuit.health = ServiceHealth(service_name=circuit.name)
        circuit.response_times.clear()
