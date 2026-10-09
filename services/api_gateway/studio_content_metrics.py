"""Prometheus series for Studio content served to browsers.

Every label is a fixed vocabulary: no tenant, session or locale becomes one.
"""

from __future__ import annotations

from typing import Literal

from prometheus_client import CollectorRegistry, Counter, Gauge

from .studio_locales import SKIP_REASONS, SkipReason

ContentEndpoint = Literal[
    "installation", "guest_languages", "guest_content", "staff_content", "feedback"
]
ContentOutcome = Literal["cached", "live", "stale", "unavailable"]
ENDPOINTS: tuple[ContentEndpoint, ...] = (
    "installation",
    "guest_languages",
    "guest_content",
    "staff_content",
    # Not a browser route: the form a feedback submission is checked against.
    "feedback",
)
OUTCOMES: tuple[ContentOutcome, ...] = ("cached", "live", "stale", "unavailable")


class StudioContentMetrics:
    """One app's content series, registered once per app registry."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._fetches = Counter(
            "ssf_studio_content_fetch_total",
            "Content route answers, by route and by where their content came from",
            ("endpoint", "outcome"),
            registry=registry,
        )
        self._staleness = Gauge(
            "ssf_studio_content_staleness_seconds",
            "Age of the Studio content in each content route's latest answer",
            ("endpoint",),
            registry=registry,
        )
        self._skipped = Counter(
            "ssf_studio_content_locales_skipped_total",
            "Studio guest locales SSF does not offer, counted once per cached revision",
            ("reason",),
            registry=registry,
        )
        # Present from the first scrape, so increase() has a prior sample.
        for endpoint in ENDPOINTS:
            self._staleness.labels(endpoint=endpoint)
            for outcome in OUTCOMES:
                self._fetches.labels(endpoint=endpoint, outcome=outcome)
        for reason in SKIP_REASONS:
            self._skipped.labels(reason=reason)

    def answered(
        self, endpoint: ContentEndpoint, outcome: ContentOutcome, age_seconds: float | None
    ) -> None:
        self._fetches.labels(endpoint=endpoint, outcome=outcome).inc()
        if age_seconds is not None:
            self._staleness.labels(endpoint=endpoint).set(age_seconds)

    def skipped(self, reason: SkipReason) -> None:
        self._skipped.labels(reason=reason).inc()
