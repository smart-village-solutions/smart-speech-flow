"""The one path every ASR, translation and TTS request takes (#219).

Before this module the pipeline called those services with bare
``requests.post``, and the circuit breakers were driven only by the 30-second
``/health`` poll in :mod:`.service_health`. ``/api/health/services`` could
therefore report every breaker closed and every service healthy while every
real request was failing: a health ping and an inference request fail for
different reasons, and only the ping was being measured.

The transport stays ``requests``. The pipeline functions are synchronous and
run on a worker thread under :class:`~.pipeline_admission.PipelineAdmission`,
so an async client would mean either making the whole pipeline async -- which
reopens the GPU bound from #191 and every route -- or bridging back to a loop
for each call. The breaker does not need either: it needs to be told what
happened, which :meth:`~.circuit_breaker.CircuitBreaker.guard` and the
``record_*`` methods allow from any thread.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

import requests

from .circuit_breaker import CircuitBreaker
from .service_health import service_health_manager


def breaker_for(service: str) -> CircuitBreaker:
    """The breaker the status routes already report on, never a private one.

    Taken from the health manager rather than ``CircuitBreakerFactory`` on
    purpose: the factory hands out a default-configured breaker for an unknown
    name and then keeps it forever, so a call made before the service was
    registered would silently pin the wrong thresholds. ``KeyError`` here is a
    typo in a call site, which is a programming error, not a runtime condition.
    """
    return service_health_manager.circuit_breakers[service]


def _sheds_load(response: Any) -> bool:
    """True for a working service deliberately refusing work.

    Since #190 the GPU services answer ``503`` with a ``Retry-After`` when they
    are at capacity. That is the admission control doing its job, and the
    client already has everything it needs to come back later. Counting it as a
    breaker failure would turn a queue into an outage at exactly the moment the
    system is busiest -- the breaker would open and start refusing the requests
    that the service was merely asking to defer.

    It is not a success either, and that half is easy to get wrong: a shed
    request was never served, so it says nothing about whether the service can
    serve one. Recording it as a success would reset ``failure_count`` in
    CLOSED -- letting a service that sheds between its 500s stay below the
    threshold forever -- and would count toward ``success_threshold`` in
    HALF_OPEN, closing the circuit on two replies that carried no work.
    """
    if getattr(response, "status_code", None) != 503:
        return False
    headers = getattr(response, "headers", None) or {}
    try:
        return int(headers.get("Retry-After", "")) >= 0
    except (TypeError, ValueError):
        # A 503 with no usable Retry-After is indistinguishable from a service
        # that is simply broken, so it is treated as one.
        return False


def _is_service_fault(response: Any) -> bool:
    """Whether this reply says the service itself is unwell.

    A 4xx does not: the service understood the request, judged it invalid and
    answered correctly. Opening a breaker on malformed client input would take
    a working service offline for every other caller.
    """
    status = getattr(response, "status_code", 0)
    if status < 500:
        return False
    return not _sheds_load(response)


def call_ai_service(
    service: str,
    url: str,
    *,
    served: Optional[Callable[[Any], bool]] = None,
    **kwargs: Any,
) -> requests.Response:
    """POSTs to an AI service through its circuit breaker.

    Returns the response untouched, including error responses: classifying an
    upstream reply into a pipeline result is the caller's job and it already
    does it well. This function's only additions are refusing to send when the
    circuit is open, and telling the breaker what happened -- which for a
    deliberate load shed means telling it nothing at all.

    ``served`` decides whether a 2xx actually carried the work. A status code
    is not always enough: TTS answers ``200`` with a JSON error body when
    synthesis fails, and ``_finish_tts_stage`` has always treated that as a
    failure. Without the predicate the breaker recorded it as a success and
    stayed CLOSED while every synthesis failed. It is consulted only for 2xx,
    so malformed client input still cannot open a breaker.

    Raises:
        CircuitBreakerOpenError: the circuit is open, or half-open with a
            probe already in flight; no request was sent.
        requests.RequestException: whatever the transport raised, after it has
            been recorded as a failure.
    """
    breaker = breaker_for(service)

    with breaker.guard():
        started = time.perf_counter()
        try:
            response = requests.post(url, **kwargs)
        except Exception as exc:
            breaker.record_failure(f"{type(exc).__name__}: {exc}")
            raise

    elapsed = time.perf_counter() - started
    if _sheds_load(response):
        # Deliberate refusal: no outcome to record in either direction, and
        # the microseconds it took must not enter the latency average.
        return response
    status = getattr(response, "status_code", 0)
    if _is_service_fault(response):
        breaker.record_failure(f"HTTP {status}")
    elif 200 <= status < 300 and served is not None and not served(response):
        breaker.record_failure(f"HTTP {status} without the expected payload")
    else:
        breaker.record_success(elapsed)
    return response
