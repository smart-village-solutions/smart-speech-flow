"""The Studio runtime configuration v2 client (tasks.md 1.3)."""

from __future__ import annotations

import asyncio
import hmac
from typing import Any, Mapping

import pytest

import services.api_gateway.studio_v2 as studio_v2_module
from services.api_gateway.studio_runtime_v2_client import (
    RUNTIME_V2_PATH,
    TENANT_CONFLICT_CODES,
    StudioRuntimeV2Client,
    StudioRuntimeV2ClientError,
)
from services.api_gateway.studio_v1 import StudioV1HttpResponse
from tests.studio_v2_fixtures import KASSEL, load_fixture

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


def client(outcome: Outcome) -> tuple[StudioRuntimeV2Client, StubTransport]:
    transport = StubTransport(outcome)

    async def token_provider() -> str:
        return "service-token"

    return (
        StudioRuntimeV2Client(
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


async def fetch_error(
    outcome: Outcome, tenant_id: str = "tenant-kassel"
) -> StudioRuntimeV2ClientError:
    runtime_client, _ = client(outcome)
    with pytest.raises(StudioRuntimeV2ClientError) as caught:
        await runtime_client.fetch(tenant_id, "c-1")
    return caught.value


async def test_fetches_the_v2_path_with_the_v1_headers() -> None:
    runtime_client, transport = client(StudioV1HttpResponse(200, load_fixture(KASSEL)))

    read = await runtime_client.fetch("tenant-kassel", "c-1")

    assert read.policy.tenant_id == "tenant-kassel"
    assert read.policy.retention_hours == 4320
    assert transport.calls == [
        (
            f"https://studio.test{RUNTIME_V2_PATH}",
            {
                "Authorization": "Bearer service-token",
                "X-Studio-Tenant-Id": "tenant-kassel",
                "X-Correlation-Id": "c-1",
            },
            2.0,
        )
    ]
    assert runtime_client.timeout_seconds == 2.0


async def test_invalid_content_does_not_fail_the_fetch() -> None:
    body = load_fixture(KASSEL)
    body["guestLanguages"][0]["feedback"]["questions"][0]["type"] = "emoji"
    runtime_client, _ = client(StudioV1HttpResponse(200, body))

    read = await runtime_client.fetch("tenant-kassel", "c-1")

    assert read.content.guest_languages == ()
    assert read.policy.mode == "ask"


async def test_an_invalid_policy_is_a_response_invalid_error() -> None:
    body = load_fixture(KASSEL)
    body["conversationContentStorage"]["retentionHours"] = None

    error = await fetch_error(StudioV1HttpResponse(200, body))

    assert (error.code, error.retryable, error.status) == (
        "studio_runtime_response_invalid",
        False,
        200,
    )


async def test_a_tenant_mismatch_is_reported_as_such() -> None:
    error = await fetch_error(StudioV1HttpResponse(200, load_fixture(KASSEL)), "tenant-fulda")

    assert (error.code, error.retryable, error.status) == (
        "studio_runtime_tenant_mismatch",
        False,
        200,
    )


@pytest.mark.parametrize("version", ["1.0", "2.0", "2.3"])
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (400, "malformed_request", False),
        (401, "service_authentication_invalid", False),
        (403, "service_action_forbidden", False),
        (404, "tenant_not_found", False),
        (409, "tenant_suspended", False),
        (409, "ssf_plugin_inactive", False),
        (409, "ssf_tenant_not_ready", True),
        (503, "runtime_configuration_unavailable", True),
    ],
)
async def test_error_envelopes_map_to_the_v1_codes(
    version: str, status: int, code: str, retryable: bool
) -> None:
    error = await fetch_error(
        StudioV1HttpResponse(status, envelope(code, version=version, retryable=retryable))
    )

    assert (error.code, error.retryable, error.status) == (code, retryable, status)


async def test_a_v2_409_tenant_suspended_is_a_tenant_conflict() -> None:
    error = await fetch_error(StudioV1HttpResponse(409, envelope("tenant_suspended")))

    assert error.code == "tenant_suspended"
    assert error.code in TENANT_CONFLICT_CODES


async def test_the_production_v2_404_is_tenant_not_found() -> None:
    body = {
        "contractVersion": "2.0",
        "error": {
            "code": "tenant_not_found",
            "message": "Tenant not found.",
            "retryable": False,
            "correlationId": "c-1",
        },
    }

    error = await fetch_error(StudioV1HttpResponse(404, body))

    assert (error.code, error.status, error.retryable) == ("tenant_not_found", 404, False)


@pytest.mark.parametrize("version", ["3.0", "2", "v2.0", "2.01", "0.9"])
async def test_an_envelope_of_another_major_version_is_invalid(version: str) -> None:
    error = await fetch_error(
        StudioV1HttpResponse(409, envelope("tenant_suspended", version=version))
    )

    assert error.code == "studio_runtime_error_invalid"


async def test_an_unexpected_code_for_the_status_is_invalid() -> None:
    error = await fetch_error(StudioV1HttpResponse(404, envelope("tenant_suspended")))

    assert error.code == "studio_runtime_error_invalid"


async def test_a_non_json_body_is_invalid_with_its_status() -> None:
    error = await fetch_error(StudioV1HttpResponse(502, None))

    assert (error.code, error.status, error.retryable) == (
        "studio_runtime_response_invalid",
        502,
        False,
    )


async def test_a_timeout_is_a_retryable_network_error() -> None:
    error = await fetch_error(asyncio.TimeoutError())

    assert (error.code, error.retryable) == ("studio_runtime_network_error", True)


async def test_rejects_unsafe_headers_before_any_request() -> None:
    runtime_client, transport = client(StudioV1HttpResponse(200, load_fixture(KASSEL)))

    with pytest.raises(ValueError):
        await runtime_client.fetch("tenant-kassel\r\nX: y", "c-1")
    with pytest.raises(ValueError):
        await runtime_client.fetch("tenant-kassel", "c-1\n")

    assert transport.calls == []


async def test_rejects_a_non_ascii_studio_tenant_as_a_mismatch() -> None:
    body = load_fixture(KASSEL)
    body["tenant"]["id"] = "tenant-kässel"

    error = await fetch_error(StudioV1HttpResponse(200, body))

    assert error.code == "studio_runtime_tenant_mismatch"


async def test_compares_the_tenant_id_in_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    compared: list[tuple[object, object]] = []
    compare_digest = hmac.compare_digest

    def recording_compare_digest(left: bytes | str, right: bytes | str) -> bool:
        compared.append((left, right))
        return compare_digest(left, right)

    monkeypatch.setattr(studio_v2_module.hmac, "compare_digest", recording_compare_digest)
    runtime_client, _ = client(StudioV1HttpResponse(200, load_fixture(KASSEL)))

    await runtime_client.fetch("tenant-kassel", "c-1")

    assert (b"tenant-kassel", b"tenant-kassel") in compared


async def test_a_body_that_is_no_envelope_is_an_invalid_error() -> None:
    error = await fetch_error(StudioV1HttpResponse(404, {"error": "tenant secret"}))

    assert error.code == "studio_runtime_error_invalid"
    assert "tenant secret" not in str(error)


async def test_an_undocumented_status_is_a_retryable_unexpected_status() -> None:
    error = await fetch_error(StudioV1HttpResponse(502, {"secret": "do-not-expose"}))

    assert (error.code, error.retryable) == ("studio_runtime_unexpected_status", True)
    assert "do-not-expose" not in str(error)


@pytest.mark.parametrize("token", ["", "service-token\r\nX-Forged: true"])
async def test_rejects_an_unusable_service_token_before_any_request(token: str) -> None:
    transport = StubTransport(StudioV1HttpResponse(200, load_fixture(KASSEL)))

    async def token_provider() -> str:
        return token

    runtime_client = StudioRuntimeV2Client(
        "https://studio.test", token_provider, transport=transport
    )

    with pytest.raises(StudioRuntimeV2ClientError) as caught:
        await runtime_client.fetch("tenant-kassel", "c-1")

    assert (caught.value.code, caught.value.retryable) == ("studio_runtime_token_invalid", False)
    assert transport.calls == []


async def test_a_timeout_does_not_chain_the_transport_error() -> None:
    error = await fetch_error(TimeoutError("transport details"))

    assert error.__cause__ is None
    assert "transport details" not in str(error)


@pytest.mark.parametrize(
    "base_url", ["https://studio.test/prefix", "https://user:secret@studio.test"]
)
def test_rejects_a_base_url_that_could_change_the_fixed_path(base_url: str) -> None:
    async def token_provider() -> str:
        return "service-token"

    with pytest.raises(ValueError):
        StudioRuntimeV2Client(base_url, token_provider)
