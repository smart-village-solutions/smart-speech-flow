"""Prometheus counters for the refinement stage.

Refinement outcomes otherwise reach ClickHouse alone, which is queried by
dashboards but not by alerting. A stage that failed every request for two
weeks went unnoticed for exactly that reason.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter


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
