"""The breaker has to be usable from the pipeline's worker thread.

``process_wav`` and ``process_text_pipeline`` are synchronous and run under
``PipelineAdmission`` on a thread from ``asyncio.to_thread`` (#189, #191). There
is no event loop there to await on, so the resilience path needs a synchronous
front door onto the same state machine ``await call()`` drives.

Every test here asserts the two doors agree. A second state machine that drifts
from the first would report a breaker closed while the other had opened it.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from services.api_gateway.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
)


@pytest.fixture
def running_loop():
    """A loop on its own thread, standing in for the gateway's.

    The sync API is only ever called from a worker thread while the gateway's
    loop runs elsewhere, so a loop the test thread does not own is the honest
    arrangement.
    """
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()


def _wait_for(predicate, timeout: float = 5.0, what: str = "condition") -> None:
    """Polls until ``predicate`` holds.

    A single round trip through the loop is not enough to see a dispatched
    callback: ``run_coroutine_threadsafe`` queues the task's *creation*, and
    the coroutine body runs on a later iteration. Polling for the result
    avoids depending on how many hops that takes.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def _breaker(**overrides) -> CircuitBreaker:
    """A breaker configured the way ``register_service`` configures the real ones."""
    settings = {
        "failure_threshold": 3,
        "recovery_timeout": 45,
        "success_threshold": 2,
        "timeout": 10.0,
    }
    settings.update(overrides)
    return CircuitBreaker("sync-test", CircuitBreakerConfig(**settings))


class TestGuard:
    def test_closed_circuit_admits_the_call(self):
        breaker = _breaker()

        with breaker.guard():
            pass

        assert breaker.state is CircuitState.CLOSED

    def test_open_circuit_refuses_before_the_call_runs(self):
        breaker = _breaker()
        for _ in range(3):
            breaker.record_failure("boom")
        assert breaker.state is CircuitState.OPEN

        entered = False
        with pytest.raises(CircuitBreakerOpenError):
            with breaker.guard():
                entered = True

        assert entered is False, "the body ran even though the circuit was open"

    def test_an_elapsed_recovery_timeout_admits_one_probe(self):
        breaker = _breaker()
        for _ in range(3):
            breaker.record_failure("boom")
        # Expire the wait rather than sleeping 45s for it.
        breaker.next_attempt_time = time.time() - 1

        with breaker.guard():
            pass

        assert breaker.state is CircuitState.HALF_OPEN

    def test_the_open_error_reports_the_remaining_wait(self):
        breaker = _breaker()
        for _ in range(3):
            breaker.record_failure("boom")

        with pytest.raises(CircuitBreakerOpenError) as caught:
            with breaker.guard():
                pass

        assert breaker.name in str(caught.value)
        assert breaker.time_until_next_attempt() > 0


class TestRecordingMatchesTheAsyncPath:
    """The same sequence through both doors must leave the same state."""

    @staticmethod
    def _drive_async(breaker: CircuitBreaker, outcomes: list[bool]) -> None:
        async def run() -> None:
            for succeeded in outcomes:

                async def call():
                    if not succeeded:
                        raise RuntimeError("boom")
                    return "ok"

                try:
                    await breaker.call(call)
                except RuntimeError:
                    pass

        asyncio.run(run())

    @staticmethod
    def _drive_sync(breaker: CircuitBreaker, outcomes: list[bool]) -> None:
        for succeeded in outcomes:
            try:
                with breaker.guard():
                    if succeeded:
                        breaker.record_success(0.01)
                    else:
                        raise RuntimeError("boom")
            except RuntimeError:
                breaker.record_failure("boom")

    @pytest.mark.parametrize(
        "outcomes",
        [
            pytest.param([False, False], id="below-threshold"),
            pytest.param([False, False, False], id="opens-on-threshold"),
            pytest.param([True, False, True, False], id="interleaved"),
            pytest.param([True, True, True], id="all-success"),
        ],
    )
    def test_both_doors_reach_the_same_state(self, outcomes):
        through_async = _breaker()
        through_sync = _breaker()

        self._drive_async(through_async, outcomes)
        self._drive_sync(through_sync, outcomes)

        assert through_sync.state == through_async.state
        assert through_sync.failure_count == through_async.failure_count
        assert through_sync.health.total_requests == through_async.health.total_requests
        assert through_sync.health.failed_requests == through_async.health.failed_requests

    def test_consecutive_failures_open_the_circuit(self):
        breaker = _breaker()

        for _ in range(2):
            breaker.record_failure("boom")
        assert breaker.state is CircuitState.CLOSED

        breaker.record_failure("boom")
        assert breaker.state is CircuitState.OPEN

    def test_a_success_resets_the_failure_count_while_closed(self):
        breaker = _breaker()

        breaker.record_failure("boom")
        breaker.record_failure("boom")
        breaker.record_success(0.01)

        assert breaker.failure_count == 0
        assert breaker.state is CircuitState.CLOSED

    def test_enough_half_open_successes_close_the_circuit(self):
        breaker = _breaker()
        for _ in range(3):
            breaker.record_failure("boom")
        breaker.next_attempt_time = time.time() - 1
        with breaker.guard():
            pass
        assert breaker.state is CircuitState.HALF_OPEN

        breaker.record_success(0.01)
        assert breaker.state is CircuitState.HALF_OPEN
        breaker.record_success(0.01)

        assert breaker.state is CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_a_half_open_failure_reopens_with_a_longer_wait(self):
        breaker = _breaker()
        for _ in range(3):
            breaker.record_failure("boom")
        first_timeout = breaker.current_recovery_timeout
        breaker.next_attempt_time = time.time() - 1
        with breaker.guard():
            pass

        breaker.record_failure("boom")

        assert breaker.state is CircuitState.OPEN
        assert breaker.current_recovery_timeout > first_timeout


class TestThreadSafety:
    def test_concurrent_recording_loses_no_request(self):
        """The pipeline runs several worker threads at once under #191.

        Read-modify-write on the counters without a lock drops increments, and
        the loss is silent: the breaker simply under-reports traffic and opens
        later than it should.
        """
        breaker = _breaker(failure_threshold=10_000)
        threads_count = 8
        per_thread = 200
        barrier = threading.Barrier(threads_count)

        def hammer() -> None:
            barrier.wait()
            for _ in range(per_thread):
                breaker.record_success(0.001)

        threads = [threading.Thread(target=hammer) for _ in range(threads_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert breaker.health.total_requests == threads_count * per_thread
        assert breaker.health.successful_requests == threads_count * per_thread

    def test_concurrent_failures_open_the_circuit_exactly_once(self, running_loop):
        """Two hundred failures past the threshold must announce one opening.

        A loop is bound here because that is the production arrangement -- the
        gateway's loop is running while pipeline threads record outcomes -- and
        it is the only way to observe the transition count rather than infer it.
        """
        breaker = _breaker(failure_threshold=5)
        breaker.bind_loop(running_loop)
        transitions: list[tuple] = []
        lock = threading.Lock()

        async def on_change(name, old, new, health):
            with lock:
                transitions.append((old, new))

        breaker.on_state_change = on_change
        barrier = threading.Barrier(8)

        def hammer() -> None:
            barrier.wait()
            for _ in range(25):
                breaker.record_failure("boom")

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert breaker.state is CircuitState.OPEN
        assert breaker.health.total_requests == 200

        _wait_for(lambda: len(transitions) >= 1, what="the open notification")
        # Give any duplicate a chance to arrive before declaring there is none.
        time.sleep(0.1)
        opened = [pair for pair in transitions if pair[1] is CircuitState.OPEN]
        assert len(opened) == 1, f"circuit opened {len(opened)} times, expected once"


class TestNotificationWithoutALoop:
    def test_a_transition_on_a_bare_thread_still_happens(self):
        """A missing loop may cost a log line. It must never cost a transition."""
        breaker = _breaker()
        seen: list[tuple] = []

        async def on_change(name, old, new, health):
            seen.append((old, new))

        breaker.on_state_change = on_change

        def hammer() -> None:
            for _ in range(3):
                breaker.record_failure("boom")

        thread = threading.Thread(target=hammer)
        thread.start()
        thread.join()

        assert breaker.state is CircuitState.OPEN

    def test_a_failing_callback_cannot_break_the_breaker(self):
        breaker = _breaker()

        async def on_change(name, old, new, health):
            raise RuntimeError("notification exploded")

        breaker.on_state_change = on_change

        for _ in range(3):
            breaker.record_failure("boom")

        assert breaker.state is CircuitState.OPEN
