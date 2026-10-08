"""The Studio content series: fixed labels, present from the first scrape."""

from __future__ import annotations

from prometheus_client import CollectorRegistry

from services.api_gateway.gateway_metrics import GatewayMetrics
from services.api_gateway.studio_content_metrics import StudioContentMetrics

FETCH = "ssf_studio_content_fetch_total"
STALENESS = "ssf_studio_content_staleness_seconds"
SKIPPED = "ssf_studio_content_locales_skipped_total"


def test_every_series_exists_before_the_first_answer() -> None:
    registry = CollectorRegistry()
    StudioContentMetrics(registry)

    for endpoint in ("installation", "guest_languages", "guest_content", "staff_content"):
        assert registry.get_sample_value(STALENESS, {"endpoint": endpoint}) == 0
        for outcome in ("cached", "live", "stale", "unavailable"):
            labels = {"endpoint": endpoint, "outcome": outcome}
            assert registry.get_sample_value(FETCH, labels) == 0
    for reason in ("unsupported", "duplicate"):
        assert registry.get_sample_value(SKIPPED, {"reason": reason}) == 0


def test_answers_count_by_outcome_and_set_the_age() -> None:
    registry = CollectorRegistry()
    metrics = StudioContentMetrics(registry)

    metrics.answered("staff_content", "stale", 125.0)
    metrics.answered("staff_content", "unavailable", None)
    metrics.skipped("duplicate")

    assert registry.get_sample_value(FETCH, {"endpoint": "staff_content", "outcome": "stale"}) == 1
    assert registry.get_sample_value(STALENESS, {"endpoint": "staff_content"}) == 125.0
    assert (
        registry.get_sample_value(FETCH, {"endpoint": "staff_content", "outcome": "unavailable"})
        == 1
    )
    assert registry.get_sample_value(SKIPPED, {"reason": "duplicate"}) == 1


def test_the_app_registry_serves_the_content_series() -> None:
    metrics = GatewayMetrics.build()

    metrics.studio_content.answered("installation", "live", 0.0)

    labels = {"endpoint": "installation", "outcome": "live"}
    assert metrics.registry.get_sample_value(FETCH, labels) == 1
