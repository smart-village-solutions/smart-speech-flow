"""Policy metrics stay low-cardinality and carry no identifier."""

from prometheus_client import CollectorRegistry

from services.api_gateway.consent import ConsentStatus
from services.api_gateway.runtime_policy import (
    PolicyDecision,
    PolicyReason,
    RuntimePolicyGate,
)
from services.api_gateway.runtime_policy_metrics import RuntimePolicyMetrics
from tests.runtime_policy_helpers import RecordingClient, configuration

DECISIONS = "ssf_runtime_policy_decision_total"
DURATION_COUNT = "ssf_runtime_policy_read_duration_seconds_count"
DISCARDED = "ssf_runtime_policy_content_discarded_total"


def _value(registry, name, **labels):
    return registry.get_sample_value(name, labels) or 0.0


async def _authorize(registry, client):
    gate = RuntimePolicyGate(client, metrics=RuntimePolicyMetrics(registry))
    return await gate.authorize("tenant-kassel", ConsentStatus.GRANTED, "cid")


async def test_an_authorised_decision_is_counted_once():
    registry = CollectorRegistry()

    await _authorize(registry, RecordingClient(configuration()))

    assert _value(registry, DECISIONS, decision="authorized", reason="granted") == 1.0


async def test_a_refusal_is_counted_under_its_reason():
    registry = CollectorRegistry()

    await _authorize(registry, RecordingClient(configuration(mode="disabled")))

    assert (
        _value(registry, DECISIONS, decision="refused", reason="policy_disabled") == 1.0
    )


async def test_every_read_observes_one_duration():
    registry = CollectorRegistry()

    await _authorize(registry, RecordingClient(configuration()))

    assert _value(registry, DURATION_COUNT) == 1.0


async def test_a_refusal_counts_its_content_as_discarded():
    registry = CollectorRegistry()

    await _authorize(registry, RecordingClient(configuration(mode="disabled")))

    assert _value(registry, DISCARDED, reason="policy_disabled") == 1.0


async def test_an_authorised_write_discards_nothing():
    registry = CollectorRegistry()

    await _authorize(registry, RecordingClient(configuration()))

    discarded = [
        sample
        for metric in registry.collect()
        for sample in metric.samples
        if sample.name == DISCARDED
    ]
    assert discarded == []


def test_no_metric_carries_a_tenant_or_session_label():
    registry = CollectorRegistry()
    metrics = RuntimePolicyMetrics(registry)
    metrics.record_decision(PolicyDecision(True, PolicyReason.GRANTED), 0.01)
    metrics.record_discarded(PolicyReason.STUDIO_UNAVAILABLE)

    samples = [sample for metric in registry.collect() for sample in metric.samples]
    assert samples, "the assertion below is vacuous unless samples exist"
    for sample in samples:
        assert set(sample.labels) <= {"decision", "reason", "le"}


def test_a_second_registration_on_one_registry_shares_the_series():
    registry = CollectorRegistry()
    RuntimePolicyMetrics(registry)

    RuntimePolicyMetrics(registry).record_discarded(PolicyReason.STUDIO_ERROR)

    assert _value(registry, DISCARDED, reason="studio_error") == 1.0
