"""Bounded admission control for GPU pipeline work.

A single RTX 4000 Ada serves ASR, translation and TTS, and each of those
services holds one shared model instance without a lock of its own. Once the
gateway stopped serialising pipelines on its event loop (#189), nothing bounded
how many reached that card at the same time. This module supplies the bound.

The component is owned by the application lifespan rather than module import, so
the semaphore belongs to the running app and tests can build their own. The
bound is process-local by design: coordinating across replicas is #227.

A slot may only be held by running work, and it must always come back. ``run()``
is the sole entry point for both reasons: the pipeline functions are synchronous
and execute on a worker thread, so the slot has two possible owners and exactly
one of them must return it.

``asyncio.to_thread`` cannot interrupt a call it has started, but it does cancel
a work item that is still queued. So a cancelled request has two very different
shapes. If the thread is already running, releasing from the awaiting task would
hand capacity to the next caller while this request's uninterruptible thread was
still on the GPU. If the work item was cancelled before any thread picked it up,
releasing only from the thread loses the slot for the life of the process. Both
are real; ``_SlotClaim`` decides between them.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, NoReturn, Optional, TypeVar

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_MAX_CONCURRENT_PIPELINES = 2
DEFAULT_QUEUE_WAIT_SECONDS = 10.0

# Spread across the plausible wait range: most requests should be seated
# immediately, and anything near the timeout is a capacity signal.
QUEUE_WAIT_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, float("inf"))


def _env_int(name: str, default: int) -> int:
    """Reads an int env var, falling back rather than blocking gateway boot."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Ignoring unparseable %s=%r; using default %s", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring unparseable %s=%r; using default %s", name, raw, default)
        return default


@dataclass(frozen=True)
class PipelineAdmissionConfig:
    """How many pipelines may run at once, and how long a request may queue.

    ``MAX_CONCURRENT_PIPELINES`` defaults deliberately low: the figure is
    inferred from the hardware, not measured, and the metrics in this module
    exist so load tests can raise it. Exactly ``0`` disables the bound.

    ``PIPELINE_QUEUE_WAIT_SECONDS`` must exceed the p95 pipeline duration or
    queued requests can never be seated: a slot is held for the whole round trip
    through ASR, translation and TTS, so with a wait shorter than that, every
    request arriving at saturation burns the wait and is then rejected. Exactly
    ``0`` opts out of queueing altogether and sheds immediately instead.

    Both settings treat a negative value as a typo and fall back to the default:
    only an exact ``0`` is an opt-out.

    Defaults are read per instance rather than at import, so the values are
    testable and a container can set them without reload tricks.
    """

    max_concurrent: int = field(
        default_factory=lambda: _env_int(
            "MAX_CONCURRENT_PIPELINES", DEFAULT_MAX_CONCURRENT_PIPELINES
        )
    )
    queue_wait_seconds: float = field(
        default_factory=lambda: _env_float(
            "PIPELINE_QUEUE_WAIT_SECONDS", DEFAULT_QUEUE_WAIT_SECONDS
        )
    )

    def __post_init__(self) -> None:
        # A negative limit is a typo, not a request to run unbounded, and
        # silently removing the bound is the dangerous reading of it. Only an
        # explicit 0 disables.
        if self.max_concurrent < 0:
            logger.warning(
                "MAX_CONCURRENT_PIPELINES=%s is negative; using default %s. "
                "Set exactly 0 to disable the bound.",
                self.max_concurrent,
                DEFAULT_MAX_CONCURRENT_PIPELINES,
            )
            object.__setattr__(self, "max_concurrent", DEFAULT_MAX_CONCURRENT_PIPELINES)

        if self.queue_wait_seconds < 0:
            logger.warning(
                "PIPELINE_QUEUE_WAIT_SECONDS=%s is negative; using default %s. "
                "Set exactly 0 to shed instead of queueing.",
                self.queue_wait_seconds,
                DEFAULT_QUEUE_WAIT_SECONDS,
            )
            object.__setattr__(self, "queue_wait_seconds", DEFAULT_QUEUE_WAIT_SECONDS)


class _SlotClaim:
    """Settles which of two threads returns one slot, exactly once.

    The awaiting task and the worker thread can both believe they own the
    release, and a plain boolean is not enough to separate them: cancelling an
    ``asyncio.to_thread`` resolves the awaiting task a loop tick *before* the
    queued work item is cancelled, so the task's cleanup can observe "not
    started" while the thread is on its way into the call. Whoever claims first
    owns the release; the loser does nothing.
    """

    __slots__ = ("_lock", "_claimed")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claimed = False

    def claim(self) -> bool:
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True


class _WorkAbandoned(BaseException):
    """The awaiting task gave up before this thread started; do not run the call.

    Derived from BaseException so an ``except Exception`` inside a pipeline
    function cannot swallow it. Never reaches a caller: by the time it is raised
    the awaiting future is already cancelled, so the result is discarded.
    """


class PipelineBusyError(RuntimeError):
    """Raised when no pipeline slot came free within the configured wait."""

    def __init__(
        self,
        *,
        max_concurrent: int,
        queue_wait_seconds: float,
        waited_seconds: float,
    ) -> None:
        super().__init__(
            f"No pipeline slot available within {queue_wait_seconds:.2f}s "
            f"(limit {max_concurrent})"
        )
        self.max_concurrent = max_concurrent
        self.queue_wait_seconds = queue_wait_seconds
        self.waited_seconds = waited_seconds
        # Whole seconds and never below one, so a client reading the body and a
        # client reading the Retry-After header wait the same amount of time.
        self.retry_after_seconds = max(1, math.ceil(queue_wait_seconds))

    @property
    def retry_after_header(self) -> str:
        return str(self.retry_after_seconds)


class PipelineAdmissionMetrics:
    """Prometheus series for capacity tuning.

    Registered once per process against the gateway's own registry; the
    admission component itself is rebuilt per lifespan, which is why these are
    passed in rather than created alongside the semaphore.
    """

    def __init__(self, registry: CollectorRegistry) -> None:
        self.in_flight = Gauge(
            "gateway_pipeline_in_flight",
            "Pipelines currently holding an admission slot",
            registry=registry,
        )
        self.queue_wait = Histogram(
            "gateway_pipeline_queue_wait_seconds",
            "Time a request waited for a pipeline slot, admitted or rejected",
            buckets=QUEUE_WAIT_BUCKETS,
            registry=registry,
        )
        self.rejected = Counter(
            "gateway_pipeline_rejected_total",
            "Requests rejected with SYSTEM_BUSY because no slot came free",
            registry=registry,
        )


class PipelineAdmission:
    """Bounds concurrent pipeline work and reports on the queue."""

    def __init__(
        self,
        config: Optional[PipelineAdmissionConfig] = None,
        *,
        metrics: Optional[PipelineAdmissionMetrics] = None,
    ) -> None:
        self._config = config or PipelineAdmissionConfig()
        self._metrics = metrics
        self._in_flight = 0
        # Only meaningful when the bound is enabled; sized once so the limit
        # cannot drift from the configuration it was built with.
        self._semaphore = asyncio.Semaphore(max(1, self._config.max_concurrent))

    @property
    def config(self) -> PipelineAdmissionConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        return self._config.max_concurrent > 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    async def run(self, func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        """Runs a synchronous pipeline function on a worker thread under the bound.

        Raises ``PipelineBusyError`` if no slot comes free within the configured
        wait. Pass only the GPU call: work done outside it occupies capacity it
        does not need.
        """
        if not self.enabled:
            return await asyncio.to_thread(func, *args, **kwargs)

        await self._acquire()
        loop = asyncio.get_running_loop()
        claim = _SlotClaim()

        def guarded() -> T:
            if not claim.claim():
                # The awaiting task is gone and has already returned the slot.
                # Starting the GPU call now would exceed the bound to produce a
                # result nobody is waiting for.
                raise _WorkAbandoned
            try:
                return func(*args, **kwargs)
            finally:
                # Released from inside the worker thread, so the slot is tied to
                # the pipeline's real lifetime rather than to the awaiting task.
                # A cancelled request therefore cannot free capacity that its
                # own uninterruptible thread is still using.
                self._schedule_release(loop)

        try:
            return await asyncio.to_thread(guarded)
        finally:
            # Only wins the claim when the work item was cancelled while still
            # queued, in which case ``guarded`` will never run and no thread
            # will ever release. Already on the loop thread, so release directly.
            if claim.claim():
                self._release()

    def _schedule_release(self, loop: asyncio.AbstractEventLoop) -> None:
        """Hands the slot back on the loop thread.

        The semaphore is not thread-safe, so the release has to be marshalled
        out of the worker thread. This runs in a ``finally`` inside that thread
        and must never raise: at shutdown the loop can already be gone, and by
        then there is no capacity left to account for.
        """
        try:
            loop.call_soon_threadsafe(self._release)
        except RuntimeError:
            logger.debug("Event loop closed before pipeline slot release")

    async def _acquire(self) -> None:
        started = time.perf_counter()

        if self._config.queue_wait_seconds == 0:
            # "Do not queue": shed straight away. This cannot go through
            # wait_for, which wraps the acquire in a task and cancels it before
            # it ever runs when the timeout is zero — rejecting every request,
            # including on a completely idle gateway.
            if self._semaphore.locked():
                self._reject(time.perf_counter() - started)
            # Uncontended, so this returns without suspending; there is no
            # await point between the check above and the permit being taken.
            await self._semaphore.acquire()
        else:
            try:
                # Python 3.11+ returns the permit if the waiter is cancelled, so
                # a timeout here cannot leak capacity.
                await asyncio.wait_for(
                    self._semaphore.acquire(), timeout=self._config.queue_wait_seconds
                )
            except TimeoutError:
                self._reject(time.perf_counter() - started)

        self._in_flight += 1
        if self._metrics:
            self._metrics.in_flight.inc()
        self._observe_wait(time.perf_counter() - started)

    def _reject(self, waited: float) -> NoReturn:
        """Records the rejection and raises. One clock read, used everywhere.

        The wait is observed on this path too: a histogram that only sees
        admitted requests reports "everyone seated instantly" during the very
        saturation it exists to measure. Reading the clock again for the error
        body would make the metric and the response disagree about one request.
        """
        self._observe_wait(waited)
        if self._metrics:
            self._metrics.rejected.inc()
        raise PipelineBusyError(
            max_concurrent=self._config.max_concurrent,
            queue_wait_seconds=self._config.queue_wait_seconds,
            waited_seconds=waited,
        ) from None

    def _observe_wait(self, waited: float) -> None:
        if self._metrics:
            self._metrics.queue_wait.observe(waited)

    def _release(self) -> None:
        self._semaphore.release()
        self._in_flight -= 1
        if self._metrics:
            self._metrics.in_flight.dec()


def get_pipeline_admission(request: Any) -> Optional[PipelineAdmission]:
    """The running app's admission component, or ``None`` when there isn't one.

    The isinstance check is load-bearing: handlers are also driven by mock
    requests in tests, where attribute access invents a truthy object rather
    than raising. Falling through to unbounded work is the right answer there
    and for any route reached before lifespan startup.
    """
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    candidate = getattr(state, "pipeline_admission", None)
    return candidate if isinstance(candidate, PipelineAdmission) else None


async def run_pipeline(request: Any, func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Runs a pipeline function under the app's bound, unbounded if there is none."""
    admission = get_pipeline_admission(request)
    if admission is None:
        return await asyncio.to_thread(func, *args, **kwargs)

    return await admission.run(func, *args, **kwargs)
