"""The Studio `recording` block (spec §14): strict on its own, never fatal to the read."""

from __future__ import annotations

import pytest

from services.api_gateway.studio_v2 import parse_runtime_configuration_v2
from services.studio_mock import contract_fixtures

TENANT = "tenant-kassel"


def _body(**recording: object) -> dict:
    body = contract_fixtures.runtime_configuration_v2(TENANT, None)
    body["recording"] = body["recording"] | recording
    return body


def test_the_mock_tenant_carries_an_enabled_policy() -> None:
    read = parse_runtime_configuration_v2(
        contract_fixtures.runtime_configuration_v2(TENANT, None), expected_tenant_id=TENANT
    )
    policy = read.policy.recording
    assert policy is not None
    assert (policy.enabled, policy.legal_basis, policy.signature) == (True, "consent", "optional")
    assert policy.timestamp_authority_url.startswith("https://")


def test_without_a_block_recording_is_unavailable() -> None:
    body = contract_fixtures.runtime_configuration_v2(TENANT, "recording-disabled")
    assert parse_runtime_configuration_v2(body, expected_tenant_id=TENANT).policy.recording is None


@pytest.mark.parametrize(
    "change",
    [
        {"retentionHours": 0},
        {"retentionHours": None},
        {"auditRetentionHours": 100, "retentionHours": 200},
        {"timestampAuthorityUrl": "http" + "://tsa.example.org"},
        {"signature": "sometimes"},
        {"enabled": "yes"},
    ],
    ids=[
        "no-retention",
        "unset-retention",
        "short-audit",
        "plain-http-tsa",
        "signature",
        "enabled",
    ],
)
def test_an_invalid_block_disables_recording_and_keeps_the_rest(change, caplog) -> None:
    read = parse_runtime_configuration_v2(_body(**change), expected_tenant_id=TENANT)
    assert read.policy.recording is None
    assert read.policy.tenant_id == TENANT
    assert read.content.guest_languages
    assert any("recording" in record.getMessage() for record in caplog.records)
