"""The Studio installation content v2 client (tasks.md 1.3)."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

import pytest

from services.api_gateway.studio_installation_client import (
    INSTALLATION_PATH,
    StudioInstallationClient,
    StudioInstallationClientError,
)
from services.api_gateway.studio_v1 import StudioV1HttpResponse
from tests.studio_v2_fixtures import INSTALLATION, load_fixture

Outcome = StudioV1HttpResponse | BaseException


class StubTransport:
    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, dict[str, str], float]] = []

    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> StudioV1HttpResponse:
        self.calls.append((url, dict(headers), timeout_seconds))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def client(outcome: Outcome) -> tuple[StudioInstallationClient, StubTransport]:
    transport = StubTransport(outcome)

    async def token_provider() -> str:
        return "service-token"

    return (
        StudioInstallationClient(
            "https://studio.test", token_provider, transport=transport, timeout_seconds=2.0
        ),
        transport,
    )


def envelope(code: str, *, version: str = "2.0", retryable: bool = False) -> dict[str, Any]:
    return {
        "contractVersion": version,
        "error": {
            "code": code,
            "message": "Unavailable.",
            "retryable": retryable,
            "correlationId": "c-1",
        },
    }


async def fetch_error(outcome: Outcome) -> StudioInstallationClientError:
    installation_client, _ = client(outcome)
    with pytest.raises(StudioInstallationClientError) as caught:
        await installation_client.fetch("c-1")
    return caught.value


async def test_fetches_installation_content_without_a_tenant_header() -> None:
    installation_client, transport = client(StudioV1HttpResponse(200, load_fixture(INSTALLATION)))

    content = await installation_client.fetch("c-1")

    assert content.legal.privacy_policy_url == "https://www.kassel.de/datenschutzerklaerung.php"
    assert content.feedback is not None
    assert transport.calls == [
        (
            f"https://studio.test{INSTALLATION_PATH}",
            {"Authorization": "Bearer service-token", "X-Correlation-Id": "c-1"},
            2.0,
        )
    ]


async def test_an_invalid_form_does_not_fail_the_fetch() -> None:
    body = load_fixture(INSTALLATION)
    body["localization"]["feedback"]["questions"][0]["type"] = "emoji"
    installation_client, _ = client(StudioV1HttpResponse(200, body))

    content = await installation_client.fetch("c-1")

    assert content.feedback is None


async def test_invalid_legal_links_fail_the_fetch() -> None:
    body = load_fixture(INSTALLATION)
    body["legal"]["imprintUrl"] = "http://www.kassel.de/impressum.php"

    error = await fetch_error(StudioV1HttpResponse(200, body))

    assert (error.code, error.status, error.retryable) == (
        "studio_installation_response_invalid",
        200,
        False,
    )


@pytest.mark.parametrize("version", ["1.0", "2.0"])
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (400, "malformed_request", False),
        (401, "service_authentication_invalid", False),
        (403, "service_action_forbidden", False),
        (503, "installation_content_unavailable", True),
        (503, "runtime_configuration_unavailable", True),
    ],
)
async def test_error_envelopes_map_to_studio_codes(
    version: str, status: int, code: str, retryable: bool
) -> None:
    error = await fetch_error(
        StudioV1HttpResponse(status, envelope(code, version=version, retryable=retryable))
    )

    assert (error.code, error.retryable, error.status) == (code, retryable, status)


async def test_a_tenant_error_is_unexpected_for_installation_content() -> None:
    error = await fetch_error(StudioV1HttpResponse(404, envelope("tenant_not_found")))

    assert (error.code, error.retryable) == ("studio_installation_unexpected_status", False)


async def test_a_timeout_is_a_retryable_network_error() -> None:
    error = await fetch_error(asyncio.TimeoutError())

    assert (error.code, error.retryable) == ("studio_installation_network_error", True)


async def test_rejects_an_unsafe_correlation_id_before_any_request() -> None:
    installation_client, transport = client(StudioV1HttpResponse(200, load_fixture(INSTALLATION)))

    with pytest.raises(ValueError):
        await installation_client.fetch("c-1\r\nX: y")

    assert transport.calls == []
