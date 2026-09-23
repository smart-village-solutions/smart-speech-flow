"""Prometheus counters for the refinement stage.

Refinement outcomes otherwise reach ClickHouse alone, which is queried by
dashboards but not by alerting. A stage that failed every request for two
weeks went unnoticed for exactly that reason.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter

#: Outcomes the in-path refiner (not the shadow candidate) can emit. Kept
#: separate from `RefinementOutcomeCode` because pre-creation is deliberately
#: narrower than the full enum -- see `pre_create_series`.
IN_PATH_OUTCOMES = ("success", "error", "skipped_language")


class RefinementMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.attempts = Counter(
            "refinement_attempts_total",
            "Refinement attempts by outcome and model",
            ["outcome", "model_ref"],
            registry=registry,
        )

    def record(self, outcome: str, model_ref: str) -> None:
        self.attempts.labels(outcome=outcome, model_ref=model_ref).inc()

    def pre_create_series(self, model_ref: str) -> None:
        """Touch each in-path outcome so `increase()` has a prior sample.

        A Prometheus series exists only once first incremented, so without
        this the very first refinement failure after a gateway restart is
        invisible to `increase()`-based alerting -- exactly the common case
        with a handful of messages a day and a restart on every deploy.
        Shadow-only outcomes (skipped_overload, submission_failed) are
        deliberately excluded: a backend not running a shadow comparison
        never emits them.
        """
        for outcome in IN_PATH_OUTCOMES:
            self.attempts.labels(outcome=outcome, model_ref=model_ref).inc(0)
