"""One live read per message decides the fate of every artefact it produced."""

import pytest

from services.api_gateway.consent import ConsentStatus
from services.api_gateway.persistence_authorization import (
    ArtifactAuthorization,
    authorize_message_artifacts,
)
from services.api_gateway.runtime_policy import RuntimePolicyGate
from services.api_gateway.studio_runtime_v2_client import StudioRuntimeV2ClientError
from tests.runtime_policy_helpers import RecordingClient, runtime_read


async def test_granted_and_ask_authorises_every_artefact():
    gate = RuntimePolicyGate(RecordingClient(runtime_read(mode="ask")))
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
    gate = RuntimePolicyGate(RecordingClient(runtime_read(mode="ask")))
    result = await authorize_message_artifacts(
        gate=gate,
        tenant_id="tenant-kassel",
        consent_status=status,
        correlation_id="c1",
        has_original_audio=True,
        has_translated_audio=True,
    )
    assert not any((result.record, result.original_audio, result.translated_audio))


async def test_mode_flip_between_two_messages_of_one_session():
    # #299's central criterion: the first message is authorised, the second is not.
    client = RecordingClient(runtime_read(mode="ask"), runtime_read(mode="disabled"))
    gate = RuntimePolicyGate(client)

    first, second = [
        await authorize_message_artifacts(
            gate=gate,
            tenant_id="tenant-kassel",
            consent_status=ConsentStatus.GRANTED,
            correlation_id=correlation_id,
            has_original_audio=True,
            has_translated_audio=True,
        )
        for correlation_id in ("c1", "c2")
    ]

    assert first == ArtifactAuthorization(True, True, True)
    assert second == ArtifactAuthorization(False, False, False)
    assert client.calls == 2


@pytest.mark.parametrize(
    ("original", "translated"), [(False, False), (True, False), (False, True), (True, True)]
)
async def test_one_read_decides_every_artefact_of_a_message(original, translated):
    client = RecordingClient(runtime_read(mode="ask"))
    gate = RuntimePolicyGate(client)

    result = await authorize_message_artifacts(
        gate=gate,
        tenant_id="tenant-kassel",
        consent_status=ConsentStatus.GRANTED,
        correlation_id="c1",
        has_original_audio=original,
        has_translated_audio=translated,
    )

    assert client.calls == 1
    assert result == ArtifactAuthorization(True, original, translated)


async def test_a_refused_read_is_not_retried_for_a_later_artefact():
    # A retry in place would turn one refusal into a split decision.
    client = RecordingClient(
        StudioRuntimeV2ClientError("studio_runtime_network_error", retryable=True),
        runtime_read(mode="ask"),
    )

    result = await authorize_message_artifacts(
        gate=RuntimePolicyGate(client),
        tenant_id="tenant-kassel",
        consent_status=ConsentStatus.GRANTED,
        correlation_id="c1",
        has_original_audio=True,
        has_translated_audio=True,
    )

    assert client.calls == 1
    assert result == ArtifactAuthorization(False, False, False)


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
    client = RecordingClient(runtime_read(tenant_id="tenant-fulda", mode="ask"))
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
    client = RecordingClient(StudioRuntimeV2ClientError(code, retryable=retryable))
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
    assert client.calls == 1
