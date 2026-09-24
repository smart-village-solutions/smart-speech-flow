from prometheus_client import CollectorRegistry

from services.api_gateway.refinement_metrics import RefinementMetrics


def test_counts_each_outcome_separately():
    registry = CollectorRegistry()
    metrics = RefinementMetrics(registry)

    metrics.record("success", "gemma-4-e4b-qat")
    metrics.record("error", "gemma-4-e4b-qat")
    metrics.record("error", "gemma-4-e4b-qat")

    value = registry.get_sample_value(
        "refinement_attempts_total", {"outcome": "error", "model_ref": "gemma-4-e4b-qat"}
    )
    assert value == 2.0


def test_pre_create_series_touches_the_in_path_outcomes_at_zero():
    """Prometheus increase() needs a prior sample; a series that first
    appears on the first failure makes that failure invisible to the alert.
    Shadow-only outcomes are deliberately not pre-created here."""
    registry = CollectorRegistry()
    metrics = RefinementMetrics(registry)

    metrics.pre_create_series("gemma-4-e4b-qat")

    for outcome in ("success", "error", "skipped_language"):
        value = registry.get_sample_value(
            "refinement_attempts_total",
            {"outcome": outcome, "model_ref": "gemma-4-e4b-qat"},
        )
        assert value == 0.0, f"{outcome} series missing or non-zero before any refinement"

    for outcome in ("skipped_overload", "submission_failed"):
        value = registry.get_sample_value(
            "refinement_attempts_total",
            {"outcome": outcome, "model_ref": "gemma-4-e4b-qat"},
        )
        assert value is None, f"shadow-only outcome {outcome} must not be pre-created"


class TestTheCounterSurvivesTheRegistryBoundary:
    """A counter is not a signal until /metrics can scrape it.

    Building a RefinementMetrics(CollectorRegistry()) proves the class works
    but nothing about wiring: a series left on a registry the gateway does not
    serve is invisible to Prometheus. This exercises the real module-level
    object the gateway attaches to the refiner, through the same `metrics()`
    endpoint function the running gateway would serve, and reads it off
    `app.state.prometheus_registry` -- the registry /metrics actually renders.
    """

    def test_the_module_level_counter_is_in_the_served_registry(self):
        import services.api_gateway.app as gateway_app
        from services.api_gateway.routes.metrics import metrics

        gateway_app.refinement_metrics.record("error", "vllm-shadow-test")

        body = metrics().body.decode("utf-8")

        assert "refinement_attempts_total" in body, (
            "the refinement counter is not in the scraped registry; it would "
            "look wired up while alerting could never see it"
        )
        assert 'refinement_attempts_total{model_ref="vllm-shadow-test",outcome="error"}' in body
