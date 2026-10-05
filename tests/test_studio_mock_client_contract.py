"""The Studio mock and the gateway's clients must agree on the V1 contracts (#346).

The mock is what the clients are tested against, so a disagreement here means
green tests and a broken integration. #308 was one such disagreement.
"""

from typing import Mapping, get_args
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from services.api_gateway import studio_login_directory_client, studio_runtime_client
from services.api_gateway.studio_login_directory_client import (
    StudioLoginDirectoryClient,
    StudioLoginDirectoryClientError,
)
from services.api_gateway.studio_runtime_client import (
    StudioRuntimeClient,
    StudioRuntimeClientError,
)
from services.api_gateway.studio_v1 import StudioV1HttpResponse
from services.studio_mock import app as mock

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
    with pytest.raises(StudioRuntimeClientError) as caught:
        await _runtime(token, scenario).fetch(tenant_id, "contract-correlation")

    assert caught.value.code == code


@pytest.mark.asyncio
async def test_the_mock_directory_validates_in_the_directory_client() -> None:
    directory = await _directory().fetch("contract-correlation")

    assert {tenant.id for tenant in directory.tenants} == set(mock.TENANT_CONFIGURATION_TEMPLATES)


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
    with pytest.raises(StudioLoginDirectoryClientError) as caught:
        await _directory(token, scenario).fetch("contract-correlation")

    assert caught.value.code == code


def test_mock_emits_only_codes_the_clients_accept() -> None:
    runtime_codes = set().union(*studio_runtime_client.EXPECTED_ERROR_CODES.values())
    directory_codes = set().union(*studio_login_directory_client.EXPECTED_ERROR_CODES.values())

    assert set(get_args(mock.RuntimeErrorCode)) <= runtime_codes
    # 404 tenant_not_found answers tenant selectors, which the directory client never sends.
    assert set(get_args(mock.DirectoryErrorCode)) - {"tenant_not_found"} <= directory_codes
