"""Every persistence decision is a live read that fails closed."""

import pytest

from services.api_gateway.consent import ConsentStatus
from services.api_gateway.runtime_policy import PolicyReason, RuntimePolicyGate
from services.api_gateway.studio_runtime_client import StudioRuntimeClientError
from services.api_gateway.studio_runtime_token import StudioTokenError
from tests.runtime_policy_helpers import RecordingClient, configuration


async def _authorize(client, consent=ConsentStatus.GRANTED):
    return await RuntimePolicyGate(client).authorize("tenant-kassel", consent, "cid")


async def test_ask_plus_granted_authorises():
    decision = await _authorize(RecordingClient(configuration()))

    assert decision.authorized is True
    assert decision.reason is PolicyReason.GRANTED


@pytest.mark.parametrize(
    "consent, reason",
    [
        (ConsentStatus.PENDING, PolicyReason.CONSENT_PENDING),
        (ConsentStatus.DECLINED, PolicyReason.CONSENT_DECLINED),
        (ConsentStatus.POLICY_DISABLED, PolicyReason.POLICY_DISABLED),
    ],
)
async def test_ask_without_granted_consent_refuses(consent, reason):
    decision = await _authorize(RecordingClient(configuration()), consent)

    assert decision.authorized is False
    assert decision.reason is reason


async def test_disabled_refuses_even_when_consent_says_granted():
    decision = await _authorize(RecordingClient(configuration(mode="disabled")))

    assert decision.authorized is False
    assert decision.reason is PolicyReason.POLICY_DISABLED


async def test_a_mode_flip_between_two_writes_stops_the_second():
    client = RecordingClient(configuration(), configuration(mode="disabled"))
    gate = RuntimePolicyGate(client)

    first = await gate.authorize("tenant-kassel", ConsentStatus.GRANTED, "cid")
    second = await gate.authorize("tenant-kassel", ConsentStatus.GRANTED, "cid")

    assert first.authorized is True
    assert second.authorized is False
    assert second.reason is PolicyReason.POLICY_DISABLED
    assert client.calls == 2


@pytest.mark.parametrize(
    "code, reason",
    [
        ("tenant_suspended", PolicyReason.TENANT_UNAVAILABLE),
        ("ssf_plugin_inactive", PolicyReason.TENANT_UNAVAILABLE),
        ("ssf_tenant_not_ready", PolicyReason.TENANT_UNAVAILABLE),
        ("runtime_configuration_unavailable", PolicyReason.STUDIO_UNAVAILABLE),
        ("studio_runtime_network_error", PolicyReason.STUDIO_UNAVAILABLE),
        ("studio_runtime_response_invalid", PolicyReason.VALIDATION_FAILED),
        ("studio_runtime_tenant_mismatch", PolicyReason.VALIDATION_FAILED),
        ("studio_runtime_error_invalid", PolicyReason.VALIDATION_FAILED),
        ("malformed_request", PolicyReason.STUDIO_ERROR),
        ("service_authentication_invalid", PolicyReason.STUDIO_ERROR),
        ("service_action_forbidden", PolicyReason.STUDIO_ERROR),
        ("tenant_not_found", PolicyReason.STUDIO_ERROR),
        ("studio_runtime_unexpected_status", PolicyReason.STUDIO_ERROR),
        ("studio_runtime_token_invalid", PolicyReason.STUDIO_ERROR),
    ],
)
async def test_every_runtime_client_failure_refuses_under_its_reason(code, reason):
    decision = await _authorize(
        RecordingClient(StudioRuntimeClientError(code, retryable=False))
    )

    assert decision.authorized is False
    assert decision.reason is reason


@pytest.mark.parametrize(
    "code, reason",
    [
        ("studio_token_network_error", PolicyReason.STUDIO_UNAVAILABLE),
        ("studio_token_authentication_failed", PolicyReason.STUDIO_ERROR),
        ("studio_token_response_invalid", PolicyReason.STUDIO_ERROR),
        ("studio_token_configuration_invalid", PolicyReason.STUDIO_ERROR),
    ],
)
async def test_every_token_failure_refuses_under_its_reason(code, reason):
    decision = await _authorize(RecordingClient(StudioTokenError(code, retryable=False)))

    assert decision.authorized is False
    assert decision.reason is reason


async def test_the_reason_follows_the_code_not_the_retryable_flag():
    retryable = await _authorize(
        RecordingClient(StudioTokenError("studio_token_network_error", retryable=True))
    )
    final = await _authorize(
        RecordingClient(StudioTokenError("studio_token_network_error", retryable=False))
    )

    assert retryable.reason is final.reason is PolicyReason.STUDIO_UNAVAILABLE


async def test_a_retryable_failure_is_not_retried_in_place():
    client = RecordingClient(
        StudioRuntimeClientError("runtime_configuration_unavailable", retryable=True)
    )

    await _authorize(client)

    assert client.calls == 1


async def test_the_gate_rechecks_the_tenant_of_any_fetcher():
    decision = await _authorize(RecordingClient(configuration("tenant-fulda")))

    assert decision.authorized is False
    assert decision.reason is PolicyReason.VALIDATION_FAILED


async def test_an_unexpected_error_refuses_rather_than_propagating():
    decision = await _authorize(RecordingClient(RuntimeError("boom")))

    assert decision.authorized is False
    assert decision.reason is PolicyReason.STUDIO_ERROR


async def test_only_the_granted_member_authorises_not_a_lookalike():
    decision = await _authorize(RecordingClient(configuration()), consent="granted")

    assert decision.authorized is False
    assert decision.reason is PolicyReason.CONSENT_PENDING
