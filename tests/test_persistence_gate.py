"""The gate decides each artefact's fate from its own live read."""

import pytest

from services.api_gateway.consent import ConsentStatus
from services.api_gateway.persistence_authorization import (
    authorize_message_artifacts,
)
from services.api_gateway.runtime_policy import RuntimePolicyGate
from services.api_gateway.studio_runtime_client import StudioRuntimeClientError
from tests.runtime_policy_helpers import RecordingClient, configuration


async def test_granted_and_ask_authorises_every_artefact():
    gate = RuntimePolicyGate(RecordingClient(configuration(mode="ask")))
    result = await authorize_message_artifacts(
        gate=gate,
        tenant_id="tenant-kassel",
        consent_status=ConsentStatus.GRANTED,
        correlation_id="c1",
        has_original_audio=True,
        has_translated_audio=True,
    )
    assert (result.record, result.original_audio, result.translated_audio) == (
        True,
        True,
        True,
    )


@pytest.mark.parametrize(
    "status",
    [ConsentStatus.PENDING, ConsentStatus.DECLINED, ConsentStatus.POLICY_DISABLED],
)
async def test_consent_not_granted_refuses_every_artefact(status):
    gate = RuntimePolicyGate(RecordingClient(configuration(mode="ask")))
    result = await authorize_message_artifacts(
        gate=gate,
        tenant_id="tenant-kassel",
        consent_status=status,
        correlation_id="c1",
        has_original_audio=True,
        has_translated_audio=True,
    )
    assert not any((result.record, result.original_audio, result.translated_audio))


async def test_mode_flip_between_writes_of_one_session():
    # #299's central criterion: the first write is authorised, the second is not.
    # One artefact per call, so the scripted sequence is one read each.
    client = RecordingClient(configuration(mode="ask"), configuration(mode="disabled"))
    gate = RuntimePolicyGate(client)
    first = await authorize_message_artifacts(
        gate=gate,
        tenant_id="tenant-kassel",
        consent_status=ConsentStatus.GRANTED,
        correlation_id="c1",
        has_original_audio=False,
        has_translated_audio=False,
    )
    second = await authorize_message_artifacts(
        gate=gate,
        tenant_id="tenant-kassel",
        consent_status=ConsentStatus.GRANTED,
        correlation_id="c2",
        has_original_audio=False,
        has_translated_audio=False,
    )
    assert first.record is True
    assert second.record is False
    assert client.calls == 2


async def test_one_read_per_artefact_and_no_retry():
    client = RecordingClient(configuration(mode="ask"))
    gate = RuntimePolicyGate(client)
    await authorize_message_artifacts(
        gate=gate,
        tenant_id="tenant-kassel",
        consent_status=ConsentStatus.GRANTED,
        correlation_id="c1",
        has_original_audio=True,
        has_translated_audio=True,
    )
    assert client.calls == 3


async def test_absent_artefacts_are_not_read_for():
    client = RecordingClient(configuration(mode="ask"))
    gate = RuntimePolicyGate(client)
    await authorize_message_artifacts(
        gate=gate,
        tenant_id="tenant-kassel",
        consent_status=ConsentStatus.GRANTED,
        correlation_id="c1",
        has_original_audio=False,
        has_translated_audio=False,
    )
    assert client.calls == 1


async def test_unbound_gate_refuses_everything():
    result = await authorize_message_artifacts(
        gate=None,
        tenant_id="tenant-kassel",
        consent_status=ConsentStatus.GRANTED,
        correlation_id="c1",
        has_original_audio=True,
        has_translated_audio=True,
    )
    assert not any((result.record, result.original_audio, result.translated_audio))


async def test_cross_tenant_response_refuses():
    # The gate compares the echoed tenant against the one it asked for.
    client = RecordingClient(configuration(tenant_id="tenant-fulda", mode="ask"))
    gate = RuntimePolicyGate(client)
    result = await authorize_message_artifacts(
        gate=gate,
        tenant_id="tenant-kassel",
        consent_status=ConsentStatus.GRANTED,
        correlation_id="c1",
        has_original_audio=False,
        has_translated_audio=False,
    )
    assert result.record is False


@pytest.mark.parametrize(
    ("code", "retryable"),
    [
        ("runtime_configuration_unavailable", True),
        ("tenant_suspended", False),
        ("studio_runtime_network_error", True),
        ("studio_runtime_response_invalid", False),
    ],
)
async def test_every_failure_refuses(code, retryable):
    client = RecordingClient(StudioRuntimeClientError(code, retryable=retryable))
    gate = RuntimePolicyGate(client)
    result = await authorize_message_artifacts(
        gate=gate,
        tenant_id="tenant-kassel",
        consent_status=ConsentStatus.GRANTED,
        correlation_id="c1",
        has_original_audio=True,
        has_translated_audio=True,
    )
    assert not any((result.record, result.original_audio, result.translated_audio))
    # Exactly one read per artefact even when every one fails: no retry in place.
    assert client.calls == 3
