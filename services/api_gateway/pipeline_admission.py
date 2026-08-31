"""Bounded admission control for GPU pipeline work.

A single RTX 4000 Ada serves ASR, translation and TTS, and each of those
services holds one shared model instance without a lock of its own. Once the
gateway stopped serialising pipelines on its event loop (#189), nothing bounded
how many reached that card at the same time. This module supplies the bound.

The component is owned by the application lifespan rather than module import, so
the semaphore belongs to the running app and tests can build their own. The
bound is process-local by design: coordinating across replicas is #227.

A slot may only be held by running work. ``run()`` is the sole entry point for
that reason: the pipeline functions are synchronous and execute on a worker
thread, and ``asyncio.to_thread`` cannot interrupt a call it has started. If the
slot were released by the awaiting task instead, a cancelled request would hand
its capacity to the next caller while its own thread was still on the GPU, and
real concurrency could exceed the limit.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

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
                "PIPELINE_QUEUE_WAIT_SECONDS=%s is negative; using default %s.",
                self.queue_wait_seconds,
                DEFAULT_QUEUE_WAIT_SECONDS,
            )
            object.__setattr__(self, "queue_wait_seconds", DEFAULT_QUEUE_WAIT_SECONDS)


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

        def guarded() -> T:
            try:
                return func(*args, **kwargs)
            finally:
                # Released from inside the worker thread, so the slot is tied to
                # the pipeline's real lifetime rather than to the awaiting task.
                # A cancelled request therefore cannot free capacity that its
                # own uninterruptible thread is still using.
                try:
                    loop.call_soon_threadsafe(self._release)
                except RuntimeError:
                    # Loop already closed during shutdown; nothing left to bound.
                    logger.debug("Event loop closed before pipeline slot release")

        return await asyncio.to_thread(guarded)

    async def _acquire(self) -> None:
        started = time.perf_counter()
        try:
            # Python 3.11+ returns the permit if the waiter is cancelled, so a
            # timeout here cannot leak capacity.
            await asyncio.wait_for(
                self._semaphore.acquire(), timeout=self._config.queue_wait_seconds
            )
        except TimeoutError:
            # Recorded on the rejection path too: a histogram that only sees
            # admitted requests reports "everyone seated instantly" during the
            # very saturation it exists to measure.
            self._observe_wait(time.perf_counter() - started)
            if self._metrics:
                self._metrics.rejected.inc()
            raise PipelineBusyError(
                max_concurrent=self._config.max_concurrent,
                queue_wait_seconds=self._config.queue_wait_seconds,
                waited_seconds=time.perf_counter() - started,
            ) from None

        self._in_flight += 1
        if self._metrics:
            self._metrics.in_flight.inc()
        self._observe_wait(time.perf_counter() - started)

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
