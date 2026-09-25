"""A refusal records the fact, never the content."""

import logging

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.consent import ConsentStatus
from services.api_gateway import message_processing
from services.api_gateway.runtime_policy import (
    PolicyDecision,
    PolicyReason,
    RuntimePolicyGate,
)
from services.api_gateway.runtime_policy_metrics import RuntimePolicyMetrics
from services.api_gateway.session_manager import ClientType
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot
from tests.runtime_policy_helpers import RecordingClient, configuration

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


@pytest.fixture
def policy_metrics_registry() -> CollectorRegistry:
    return CollectorRegistry()


async def test_refusal_log_contains_no_conversation_content(
    caplog, policy_metrics_registry, session_manager
):
    secret_original = "mein geheimes anliegen"
    secret_translated = "my secret request"

    session_manager.reset(clear_persistence=True)
    session = await session_manager.create_admin_session("tenant-test", SNAPSHOT)
    session.consent_status = ConsentStatus.DECLINED
    session_manager.store.save(session)

    gate = RuntimePolicyGate(
        RecordingClient(configuration(tenant_id="tenant-test", mode="ask")),
        metrics=RuntimePolicyMetrics(policy_metrics_registry),
    )
    session_manager.runtime_policy = gate

    with caplog.at_level(logging.DEBUG):
        message = await message_processing.create_session_message(
            session.key,
            ClientType.CUSTOMER,
            secret_original,
            secret_translated,
            "de",
            "en",
            sessions=session_manager,
            translated_audio_available=True,
        )

    assert message.record_authorized is False
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_original not in combined
    assert secret_translated not in combined


async def test_refusal_metrics_carry_no_identifiers(policy_metrics_registry):
    gate = RuntimePolicyGate(
        RecordingClient(configuration(tenant_id="tenant-kassel", mode="disabled")),
        metrics=RuntimePolicyMetrics(policy_metrics_registry),
    )
    decision = await gate.authorize(
        "tenant-kassel", ConsentStatus.GRANTED, "correlation-1"
    )
    assert decision == PolicyDecision(False, PolicyReason.POLICY_DISABLED)

    for metric in policy_metrics_registry.collect():
        for sample in metric.samples:
            assert "tenant_id" not in sample.labels
            assert "session_id" not in sample.labels
            # `le` is the histogram's own bucket boundary, not an identifier.
            assert set(sample.labels) <= {"decision", "reason", "le"}
