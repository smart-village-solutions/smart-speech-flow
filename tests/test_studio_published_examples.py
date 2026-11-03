"""Studio's own published examples, run through SSF's consumers (#612).

The two JSON files are copied verbatim from sva-studio `docs/api/` at merge
6f5963a6c (Studio PR #2041). Replace them when Studio changes its examples;
a failure here is then a contract change to agree before either side ships.
"""

from __future__ import annotations

import pytest

from services.api_gateway.studio_recording_directory_client import RecordingDirectory
from services.api_gateway.studio_v2 import parse_runtime_configuration_v2
from tests.studio_v2_fixtures import load_fixture

DIRECTORY = "studio-recording-directory.example.json"
RUNTIME = "studio-runtime-configuration.example.json"
TENANT = "tenant-kassel"
# The policy Studio's own tests resolve (packages/plugin-ssf/tests/content-v2-recording.test.ts).
STUDIO_POLICY = {
    "legalBasis": "consent",
    "signature": "optional",
    "idCheck": "off",
    "verificationRequired": True,
    "recoveryMode": "standard",
    "timestampAuthorityUrl": "https://tsa.example.org/tsr",
    "auditRetentionHours": 8760,
}


def _runtime_with(recording: dict) -> dict:
    body = load_fixture(RUNTIME)
    body["recording"] = recording
    return body


def test_the_directory_example_parses_with_its_regional_language_tag():
    directory = RecordingDirectory.model_validate(load_fixture(DIRECTORY))
    reviewer = directory.holders_of("ssf.recording.review.sworn")["synthetic-reviewer"]
    assert reviewer.languages == ("de", "en-US")
    assert set(directory.holders_of("ssf.recording.recovery.custodian")) == {"synthetic-custodian"}


def test_the_runtime_example_without_a_recording_block_leaves_recording_unavailable():
    read = parse_runtime_configuration_v2(load_fixture(RUNTIME), expected_tenant_id=TENANT)
    assert read.policy.recording is None
    assert read.content.guest_languages  # the retired storage fields Studio forces are ignored


@pytest.mark.parametrize("enabled", [True, False])
def test_the_block_studio_resolves_parses_as_sent(enabled):
    """Studio emits a complete block, enabled only by the tenant, with 720 h by default."""
    texts = [{"locale": "pt-BR", "consentHtml": "<p>Sim</p>", "resumePromptHtml": "<p>Ok</p>"}]
    recording = {**STUDIO_POLICY, "enabled": enabled, "retentionHours": 720, "texts": texts}
    read = parse_runtime_configuration_v2(_runtime_with(recording), expected_tenant_id=TENANT)
    policy = read.policy.recording
    assert policy is not None
    assert (policy.enabled, policy.retention_hours, policy.audit_retention_hours) == (
        enabled,
        720,
        8760,
    )
    assert [text.locale for text in policy.texts] == ["pt-BR"]


# Studio's own bound (content-v2-recording.ts), not SSF's constant: the two must agree.
@pytest.mark.parametrize(("hours", "accepted"), [(8760, True), (8761, False)])
def test_studios_retention_maximum_is_ssfs(hours, accepted):
    # Audit retention above both, so only the retention maximum decides.
    recording = {
        **STUDIO_POLICY,
        "enabled": True,
        "retentionHours": hours,
        "auditRetentionHours": 100_000,
    }
    read = parse_runtime_configuration_v2(_runtime_with(recording), expected_tenant_id=TENANT)
    assert (read.policy.recording is not None) is accepted
