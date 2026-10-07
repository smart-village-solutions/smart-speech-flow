"""The Studio mock and the gateway's clients must agree on the V1 and v2 contracts (#346).

The mock is what the clients are tested against, so a disagreement here means
green tests and a broken integration. #308 was one such disagreement.
"""

from typing import Mapping, get_args
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from services.api_gateway import (
    studio_installation_client,
    studio_login_directory_client,
    studio_runtime_client,
    studio_runtime_v2_client,
)
from services.api_gateway.session_lifecycle import _TENANT_CONFLICT_CODES
from services.api_gateway.studio_installation_client import (
    StudioInstallationClient,
    StudioInstallationClientError,
)
from services.api_gateway.studio_login_directory_client import (
    StudioLoginDirectoryClient,
    StudioLoginDirectoryClientError,
)
from services.api_gateway.studio_runtime_client import (
    StudioRuntimeClient,
    StudioRuntimeClientError,
)
from services.api_gateway.studio_runtime_v2_client import (
    StudioRuntimeV2Client,
    StudioRuntimeV2ClientError,
)
from services.api_gateway.studio_v1 import StudioV1HttpResponse
from services.studio_mock import app as mock
from services.studio_mock import fixtures

AUTHORIZED = "studio-mock-authorized-token"
UNAUTHORIZED = "studio-mock-unauthorized-token"


class MockTransport:
    """Reach the mock at its HTTP boundary, as the deployed client would."""

    def __init__(self, scenario: str | None = None) -> None:
        self.client = TestClient(mock.app)
        self.scenario = scenario

    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> StudioV1HttpResponse:
        sent = dict(headers)
        if self.scenario:
            sent["X-Mock-Scenario"] = self.scenario
        response = self.client.get(urlsplit(url).path, headers=sent)
        return StudioV1HttpResponse(response.status_code, response.json())


def _token(value: str):
    async def provide() -> str:
        return value

    return provide


def _runtime(token: str = AUTHORIZED, scenario: str | None = None) -> StudioRuntimeClient:
    return StudioRuntimeClient(
        "http://studio-mock.test", _token(token), transport=MockTransport(scenario)
    )


def _directory(token: str = AUTHORIZED, scenario: str | None = None) -> StudioLoginDirectoryClient:
    return StudioLoginDirectoryClient(
        "http://studio-mock.test", _token(token), transport=MockTransport(scenario)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", sorted(mock.TENANT_CONFIGURATION_TEMPLATES))
async def test_every_mock_tenant_validates_in_the_runtime_client(tenant_id: str) -> None:
    configuration = await _runtime().fetch(tenant_id, "contract-correlation")

    assert configuration.tenant.id == tenant_id


@pytest.mark.parametrize("tenant_id", sorted(mock.TENANT_CONFIGURATION_TEMPLATES))
def test_the_response_model_serves_the_configuration_unchanged(tenant_id: str) -> None:
    """The client's models must not rewrite what the revision was computed over."""
    response = TestClient(mock.app).get(
        "/internal/plugins/ssf/v1/runtime-configuration",
        headers={
            "Authorization": f"Bearer {AUTHORIZED}",
            "X-Studio-Tenant-Id": tenant_id,
            "X-Correlation-Id": "contract-correlation",
        },
    )

    assert response.json() == mock._configuration_for(tenant_id)


def test_the_response_model_serves_the_directory_unchanged() -> None:
    response = TestClient(mock.app).get(
        "/internal/plugins/ssf/v1/admin-login-tenants",
        headers={"Authorization": f"Bearer {AUTHORIZED}", "X-Correlation-Id": "c"},
    )

    assert response.json() == mock._login_directory()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token", "scenario", "tenant_id", "code"),
    [
        ("not-a-mock-token", None, "tenant-kassel", "service_authentication_invalid"),
        (UNAUTHORIZED, None, "tenant-kassel", "service_action_forbidden"),
        (AUTHORIZED, None, "tenant-unknown", "tenant_not_found"),
        (AUTHORIZED, "suspended", "tenant-kassel", "tenant_suspended"),
        (AUTHORIZED, "plugin-inactive", "tenant-kassel", "ssf_plugin_inactive"),
        (AUTHORIZED, "tenant-not-ready", "tenant-kassel", "ssf_tenant_not_ready"),
        (AUTHORIZED, "unavailable", "tenant-kassel", "runtime_configuration_unavailable"),
    ],
)
async def test_every_mock_runtime_error_is_one_the_client_accepts(
    token: str, scenario: str | None, tenant_id: str, code: str
) -> None:
    runtime_client = _runtime(token, scenario)

    with pytest.raises(StudioRuntimeClientError) as caught:
        await runtime_client.fetch(tenant_id, "contract-correlation")

    assert caught.value.code == code


@pytest.mark.asyncio
async def test_the_mock_directory_validates_in_the_directory_client() -> None:
    directory = await _directory().fetch("contract-correlation")

    assert {tenant.id for tenant in directory.tenants} == {
        tenant["id"] for tenant in fixtures.login_directory_tenants()
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token", "scenario", "code"),
    [
        ("not-a-mock-token", None, "service_authentication_invalid"),
        (UNAUTHORIZED, None, "service_action_forbidden"),
        (AUTHORIZED, "unavailable", "admin_login_directory_unavailable"),
    ],
)
async def test_every_reachable_mock_directory_error_is_one_the_client_accepts(
    token: str, scenario: str | None, code: str
) -> None:
    directory_client = _directory(token, scenario)

    with pytest.raises(StudioLoginDirectoryClientError) as caught:
        await directory_client.fetch("contract-correlation")

    assert caught.value.code == code


def test_mock_emits_only_codes_the_clients_accept() -> None:
    runtime_codes = set().union(*studio_runtime_client.EXPECTED_ERROR_CODES.values())
    directory_codes = set().union(*studio_login_directory_client.EXPECTED_ERROR_CODES.values())

    assert set(get_args(mock.RuntimeErrorCode)) <= runtime_codes
    # 404 tenant_not_found answers tenant selectors, which the directory client never sends.
    assert set(get_args(mock.DirectoryErrorCode)) - {"tenant_not_found"} <= directory_codes


def _runtime_v2(token: str = AUTHORIZED, scenario: str | None = None) -> StudioRuntimeV2Client:
    return StudioRuntimeV2Client(
        "http://studio-mock.test", _token(token), transport=MockTransport(scenario)
    )


def _installation(token: str = AUTHORIZED, scenario: str | None = None) -> StudioInstallationClient:
    return StudioInstallationClient(
        "http://studio-mock.test", _token(token), transport=MockTransport(scenario)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", fixtures.RUNTIME_V2_TENANTS)
async def test_every_v2_tenant_validates_in_the_v2_client(tenant_id: str) -> None:
    read = await _runtime_v2().fetch(tenant_id, "contract-correlation")

    served = fixtures.runtime_configuration_v2(tenant_id, None)
    assert read.policy.tenant_id == tenant_id
    assert read.policy.contract_version == "2.0"
    assert read.policy.configuration_revision == served["configurationRevision"]
    assert len(read.content.guest_languages) == len(served["guestLanguages"])


@pytest.mark.asyncio
async def test_the_ask_tenant_carries_every_guest_language_shape() -> None:
    read = await _runtime_v2().fetch("tenant-kassel", "contract-correlation")
    languages = {language.locale: language for language in read.content.guest_languages}

    assert (read.policy.mode, read.policy.retention_hours) == ("ask", 4320)
    assert list(languages) == ["en", "tr", "ar", "kmr", "pt-BR"]
    assert languages["tr"].icon is not None
    assert languages["ar"].icon is None
    assert all(language.storage_question_html for language in languages.values())
    assert read.content.staff is not None
    assert read.content.staff.feedback is not None
    assert {question.type for question in read.content.staff.feedback.questions} == {
        "rating",
        "scale",
        "longText",
    }


@pytest.mark.asyncio
async def test_the_disabled_tenant_has_null_retention_and_questions() -> None:
    read = await _runtime_v2().fetch("tenant-fulda", "contract-correlation")

    assert (read.policy.mode, read.policy.retention_hours) == ("disabled", None)
    assert read.content.guest_languages
    assert all(language.storage_question_html is None for language in read.content.guest_languages)


@pytest.mark.asyncio
async def test_the_zero_retention_tenant_reads_zero() -> None:
    read = await _runtime_v2().fetch("tenant-marburg", "contract-correlation")

    assert (read.policy.mode, read.policy.retention_hours) == ("ask", 0)


@pytest.mark.asyncio
async def test_storage_disabled_reaches_the_client_as_disabled() -> None:
    client = _runtime_v2(scenario="storage-disabled")

    read = await client.fetch("tenant-kassel", "contract-correlation")

    assert (read.policy.mode, read.policy.retention_hours) == ("disabled", None)
    assert len(read.content.guest_languages) == 5
    assert all(language.storage_question_html is None for language in read.content.guest_languages)


@pytest.mark.asyncio
async def test_invalid_content_drops_one_guest_language_and_keeps_the_policy() -> None:
    client = _runtime_v2(scenario="invalid-content")

    read = await client.fetch("tenant-kassel", "contract-correlation")

    assert (read.policy.mode, read.policy.retention_hours) == ("ask", 4320)
    assert [language.locale for language in read.content.guest_languages] == [
        "tr",
        "ar",
        "kmr",
        "pt-BR",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", fixtures.RUNTIME_V2_TENANTS)
async def test_invalid_content_keeps_every_tenants_policy(tenant_id: str) -> None:
    plain = await _runtime_v2().fetch(tenant_id, "contract-correlation")

    read = await _runtime_v2(scenario="invalid-content").fetch(tenant_id, "contract-correlation")

    assert read.policy.mode == plain.policy.mode
    assert read.policy.retention_hours == plain.policy.retention_hours
    assert read.content.guest_languages == plain.content.guest_languages[1:]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token", "scenario", "tenant_id", "code", "status"),
    [
        ("not-a-mock-token", None, "tenant-kassel", "service_authentication_invalid", 401),
        (UNAUTHORIZED, None, "tenant-kassel", "service_action_forbidden", 403),
        (AUTHORIZED, None, "tenant-unknown", "tenant_not_found", 404),
        (AUTHORIZED, "suspended", "tenant-kassel", "tenant_suspended", 409),
        (AUTHORIZED, "plugin-inactive", "tenant-kassel", "ssf_plugin_inactive", 409),
        (AUTHORIZED, "tenant-not-ready", "tenant-kassel", "ssf_tenant_not_ready", 409),
        (AUTHORIZED, "unavailable", "tenant-kassel", "runtime_configuration_unavailable", 503),
    ],
)
async def test_every_mock_v2_runtime_error_is_one_the_v2_client_accepts(
    token: str, scenario: str | None, tenant_id: str, code: str, status: int
) -> None:
    client = _runtime_v2(token, scenario)

    with pytest.raises(StudioRuntimeV2ClientError) as caught:
        await client.fetch(tenant_id, "contract-correlation")

    assert (caught.value.code, caught.value.status) == (code, status)


@pytest.mark.asyncio
async def test_a_v2_409_suspension_is_a_tenant_conflict() -> None:
    client = _runtime_v2(scenario="suspended")

    with pytest.raises(StudioRuntimeV2ClientError) as caught:
        await client.fetch("tenant-kassel", "contract-correlation")

    assert caught.value.code == "tenant_suspended"
    assert caught.value.code in _TENANT_CONFLICT_CODES


@pytest.mark.asyncio
async def test_the_installation_content_validates_in_the_installation_client() -> None:
    content = await _installation().fetch("contract-correlation")

    served = fixtures.installation_content_v2(None)
    assert content.configuration_revision == served["configurationRevision"]
    assert content.locale == "de-DE"
    assert content.legal.imprint_url == "https://example.org/impressum"
    assert content.feedback is not None
    assert {question.type for question in content.feedback.questions} == {
        "rating",
        "scale",
        "longText",
    }


@pytest.mark.asyncio
async def test_invalid_installation_content_keeps_everything_but_the_form() -> None:
    content = await _installation(scenario="invalid-content").fetch("contract-correlation")

    assert content.feedback is None
    assert content.startpage.enter_code
    assert content.legal.privacy_policy_url == "https://example.org/datenschutz"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token", "scenario", "code"),
    [
        ("not-a-mock-token", None, "service_authentication_invalid"),
        (UNAUTHORIZED, None, "service_action_forbidden"),
        (AUTHORIZED, "unavailable", "installation_content_unavailable"),
    ],
)
async def test_every_reachable_installation_error_is_one_the_client_accepts(
    token: str, scenario: str | None, code: str
) -> None:
    client = _installation(token, scenario)

    with pytest.raises(StudioInstallationClientError) as caught:
        await client.fetch("contract-correlation")

    assert caught.value.code == code


def test_the_mock_v2_routes_emit_only_codes_the_v2_clients_accept() -> None:
    runtime_codes = set().union(*studio_runtime_v2_client.EXPECTED_ERROR_CODES.values())
    installation_codes = set().union(*studio_installation_client.EXPECTED_ERROR_CODES.values())

    assert set(get_args(mock.RuntimeErrorCode)) <= runtime_codes
    assert set(get_args(mock.InstallationErrorCode)) <= installation_codes


def test_every_directory_tenant_is_readable_through_both_runtime_versions() -> None:
    directory_ids = {tenant["id"] for tenant in mock._login_directory()["tenants"]}

    assert directory_ids <= set(fixtures.RUNTIME_V2_TENANTS)
    assert directory_ids <= set(mock.TENANT_CONFIGURATION_TEMPLATES)
