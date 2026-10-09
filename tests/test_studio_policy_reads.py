"""Every live Studio policy read is counted by stage and outcome, with no identifier."""

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.app import _build_studio
from services.api_gateway.consent import ConsentStatus
from services.api_gateway.gateway_metrics import GatewayMetrics
from services.api_gateway.session_lifecycle import TenantConflictError, _read_activation_policy
from services.api_gateway.studio_content import StudioContentCache
from services.api_gateway.studio_content_metrics import StudioContentMetrics
from services.api_gateway.studio_policy_reads import (
    OUTCOMES,
    STAGES,
    CountedPolicyReads,
    StudioPolicyReadMetrics,
    read_outcome,
)
from services.api_gateway.studio_runtime_flow import StudioRuntimeFlow, StudioRuntimeFlowError
from services.api_gateway.studio_runtime_token import StudioTokenError
from services.api_gateway.studio_runtime_v2_client import (
    EXPECTED_ERROR_CODES,
    StudioRuntimeV2ClientError,
)
from services.api_gateway.studio_wiring import wire_studio
from services.api_gateway.tenant_context import StudioTenantContext
from tests.runtime_policy_helpers import RecordingClient, runtime_read

READS = "ssf_studio_policy_read_total"


def _count(registry, stage, outcome):
    return registry.get_sample_value(READS, {"stage": stage, "outcome": outcome})


def _runtime_error(code):
    return StudioRuntimeV2ClientError(code, retryable=False)


def test_every_stage_and_outcome_is_exposed_at_zero():
    registry = CollectorRegistry()
    StudioPolicyReadMetrics(registry)

    for stage in STAGES:
        for outcome in OUTCOMES:
            assert _count(registry, stage, outcome) == 0.0


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (_runtime_error("tenant_suspended"), "tenant_conflict"),
        (_runtime_error("ssf_plugin_inactive"), "tenant_conflict"),
        (_runtime_error("ssf_tenant_not_ready"), "tenant_conflict"),
        (_runtime_error("runtime_configuration_unavailable"), "unavailable"),
        (_runtime_error("studio_runtime_network_error"), "unavailable"),
        (StudioTokenError("studio_token_network_error", retryable=True), "unavailable"),
        (StudioTokenError("studio_token_network_error", retryable=False), "unavailable"),
        (
            StudioTokenError("studio_token_authentication_failed", retryable=False),
            "contract_error",
        ),
        (_runtime_error("service_authentication_invalid"), "contract_error"),
        (_runtime_error("studio_runtime_tenant_mismatch"), "contract_error"),
        (ValueError("anything else"), "contract_error"),
    ],
)
def test_a_failure_is_classified_by_its_code(error, outcome):
    assert read_outcome(error) == outcome


@pytest.mark.parametrize(
    ("code", "status", "outcome"),
    [
        # A proxy in front of a down Studio answers HTML: no JSON, so no envelope.
        ("studio_runtime_response_invalid", 502, "unavailable"),
        ("studio_runtime_response_invalid", 504, "unavailable"),
        ("studio_runtime_unexpected_status", 503, "unavailable"),
        ("studio_runtime_response_invalid", 200, "contract_error"),
        ("studio_runtime_unexpected_status", 404, "contract_error"),
        ("studio_runtime_error_invalid", 400, "contract_error"),
    ],
)
def test_a_server_error_status_means_studio_did_not_answer(code, status, outcome):
    error = StudioRuntimeV2ClientError(code, retryable=False, status=status)

    assert read_outcome(error) == outcome


def test_a_token_endpoint_server_error_means_it_did_not_answer():
    # The token client sets retryable exactly when the token endpoint answered 5xx.
    error = StudioTokenError("studio_token_authentication_failed", retryable=True)

    assert read_outcome(error) == "unavailable"


def test_tenant_conflicts_are_the_codes_the_client_accepts_on_409():
    for code in EXPECTED_ERROR_CODES[409]:
        assert read_outcome(_runtime_error(code)) == "tenant_conflict"


def test_the_label_does_not_change_with_the_retryable_flag():
    assert read_outcome(
        StudioRuntimeV2ClientError("runtime_configuration_unavailable", retryable=True)
    ) == read_outcome(_runtime_error("runtime_configuration_unavailable"))


async def test_a_successful_read_counts_ok_under_its_stage():
    registry = CollectorRegistry()
    reads = CountedPolicyReads(
        RecordingClient(runtime_read()), StudioPolicyReadMetrics(registry), "message"
    )

    await reads.fetch("tenant-kassel", "cid")

    assert _count(registry, "message", "ok") == 1.0


async def test_a_failed_read_is_counted_and_raised_unchanged():
    registry = CollectorRegistry()
    error = _runtime_error("runtime_configuration_unavailable")
    reads = CountedPolicyReads(RecordingClient(error), StudioPolicyReadMetrics(registry), "message")

    with pytest.raises(StudioRuntimeV2ClientError) as raised:
        await reads.fetch("tenant-kassel", "cid")

    assert raised.value is error
    assert _count(registry, "message", "unavailable") == 1.0
    assert _count(registry, "message", "ok") == 0.0


async def test_session_create_counts_its_read():
    registry = CollectorRegistry()
    flow = StudioRuntimeFlow(
        RecordingClient(_runtime_error("runtime_configuration_unavailable")),
        policy_reads=StudioPolicyReadMetrics(registry),
    )

    with pytest.raises(StudioRuntimeFlowError):
        await flow.resolve(StudioTenantContext("tenant-kassel"), "cid")

    assert _count(registry, "session_create", "unavailable") == 1.0


async def test_activation_counts_its_read_including_a_tenant_conflict():
    registry = CollectorRegistry()
    flow = StudioRuntimeFlow(
        RecordingClient(_runtime_error("tenant_suspended")),
        policy_reads=StudioPolicyReadMetrics(registry),
    )

    with pytest.raises(TenantConflictError):
        await _read_activation_policy(lambda: "cid", "tenant-kassel", flow)

    assert _count(registry, "activation", "tenant_conflict") == 1.0


async def test_the_persistence_gate_counts_one_read_per_message():
    registry = CollectorRegistry()
    wiring = wire_studio(
        RecordingClient(runtime_read()),
        None,
        StudioContentCache(),
        policy_registry=CollectorRegistry(),
        content_metrics=StudioContentMetrics(CollectorRegistry()),
        policy_reads=StudioPolicyReadMetrics(registry),
    )
    assert wiring.runtime_policy is not None

    await wiring.runtime_policy.authorize("tenant-kassel", ConsentStatus.GRANTED, "cid")

    assert _count(registry, "message", "ok") == 1.0
    assert sum(_count(registry, stage, "ok") for stage in STAGES) == 1.0


def test_a_flow_without_metrics_hands_out_its_own_client():
    client = RecordingClient(runtime_read())

    assert StudioRuntimeFlow(client).reads("message") is client


def test_the_app_owns_one_set_of_policy_read_series():
    metrics = GatewayMetrics.build()

    metrics.studio_policy_reads.record("activation", "ok")

    assert metrics.registry.get_sample_value(READS, {"stage": "activation", "outcome": "ok"}) == 1.0


GATE_BOUND = "ssf_studio_policy_gate_bound"


class _Tokens:
    async def get_token(self) -> str:
        return "t"


def test_the_gate_reads_as_unbound_until_the_lifespan_binds_it():
    registry = CollectorRegistry()
    StudioPolicyReadMetrics(registry)

    assert registry.get_sample_value(GATE_BOUND) == 0.0


def test_a_configured_studio_marks_the_gate_bound(monkeypatch):
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "http://studio-mock:8000")
    registry = CollectorRegistry()

    _build_studio(
        CollectorRegistry(),
        _Tokens(),
        StudioContentMetrics(CollectorRegistry()),
        StudioPolicyReadMetrics(registry),
    )

    assert registry.get_sample_value(GATE_BOUND) == 1.0


def test_an_unconfigured_studio_marks_the_gate_unbound(monkeypatch):
    # No read ever happens then, so the read counter alone would stay silent.
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "http://studio-mock:8000")
    registry = CollectorRegistry()
    metrics = StudioPolicyReadMetrics(registry)
    _build_studio(
        CollectorRegistry(), _Tokens(), StudioContentMetrics(CollectorRegistry()), metrics
    )

    _build_studio(CollectorRegistry(), None, StudioContentMetrics(CollectorRegistry()), metrics)

    assert registry.get_sample_value(GATE_BOUND) == 0.0
