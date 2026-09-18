"""Prometheus series for conversation-content policy decisions.

There are deliberately no cache metrics: the design records that no cache
exists, so their absence is a decision rather than an omission.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from prometheus_client import CollectorRegistry, Counter, Histogram

from .runtime_policy import PolicyDecision, PolicyReason

logger = logging.getLogger(__name__)

_Collector = TypeVar("_Collector", Counter, Histogram)

DECISION_COUNTER_NAME = "ssf_runtime_policy_decision_total"
READ_DURATION_NAME = "ssf_runtime_policy_read_duration_seconds"
DISCARDED_COUNTER_NAME = "ssf_runtime_policy_content_discarded_total"


class RuntimePolicyMetrics:
    """Record one decision per write, with no identifier in any label."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._decisions = _registered(
            registry,
            Counter,
            DECISION_COUNTER_NAME,
            "Conversation-content persistence decisions",
            ("decision", "reason"),
        )
        self._discarded = _registered(
            registry,
            Counter,
            DISCARDED_COUNTER_NAME,
            "Conversation-content writes refused and discarded",
            ("reason",),
        )
        self._duration = _registered(
            registry,
            Histogram,
            READ_DURATION_NAME,
            "Duration of one live Studio policy read",
        )

    def record_decision(self, decision: PolicyDecision, duration_seconds: float) -> None:
        label = "authorized" if decision.authorized else "refused"
        self._decisions.labels(decision=label, reason=decision.reason.value).inc()
        self._duration.observe(duration_seconds)

    def record_discarded(self, reason: PolicyReason) -> None:
        self._discarded.labels(reason=reason.value).inc()


def _registered(
    registry: CollectorRegistry,
    collector_type: type[_Collector],
    name: str,
    documentation: str,
    labels: tuple[str, ...] = (),
) -> _Collector:
    """Register once per registry and reuse the series on a repeat lifespan.

    The gateway's registry outlives a single lifespan, and prometheus_client
    raises on a second registration of one name. Mirrors
    quality_telemetry._events_counter, private lookup included: telemetry is
    optional, so a name this cannot claim costs a scrape gap, never startup.
    """
    try:
        return collector_type(name, documentation, labels, registry=registry)
    except ValueError:
        existing = getattr(registry, "_names_to_collectors", {}).get(name)
        if isinstance(existing, collector_type):
            return existing
    logger.warning(
        "%s is not available on the gateway registry; " "runtime policy series will not be scraped",
        name,
    )
    return collector_type(name, documentation, labels, registry=CollectorRegistry())
