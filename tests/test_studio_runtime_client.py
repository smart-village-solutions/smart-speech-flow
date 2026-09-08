"""Contract and negative-path tests for the Studio Runtime Configuration V1 client."""

from copy import deepcopy
from typing import Any, Mapping

import pytest

from services.api_gateway.studio_runtime_client import (
    RUNTIME_PATH,
    RuntimeHttpResponse,
    StudioRuntimeClient,
    StudioRuntimeClientError,
)

REVISION = f"sha256:{'a' * 64}"


def valid_configuration() -> dict[str, Any]:
    return {
        "contractVersion": "1.0",
        "configurationRevision": REVISION,
        "authorizationRevision": REVISION,
        "tenant": {
            "id": "tenant-kassel",
            "displayName": "Kassel Test Municipality",
            "timeZone": "Europe/Berlin",
        },
        "branding": {"logo": None, "icon": None},
        "localization": {
            "defaultLocale": "de-DE",
            "locales": [
                {
                    "locale": "de-DE",
                    "authenticatedHomeExplanationHtml": "<p>Authenticated</p>",
                    "guestExplanationHtml": "<p>Guest</p>",
                    "conversationContentStorageQuestionHtml": "<p>Store?</p>",
                }
            ],
        },
        "conversationContentStorage": {"mode": "ask"},
    }


class StubTransport:
    def __init__(self, response: RuntimeHttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, Mapping[str, str], float]] = []

    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> RuntimeHttpResponse:
        self.calls.append((url, headers, timeout_seconds))
        return self.response


def client(response: RuntimeHttpResponse) -> tuple[StudioRuntimeClient, StubTransport]:
    transport = StubTransport(response)

    async def token_provider() -> str:
        return "service-token"

    return (
        StudioRuntimeClient(
            "https://studio.test", token_provider, transport=transport, timeout_seconds=2.0
        ),
        transport,
    )


@pytest.mark.asyncio
async def test_accepts_valid_response_and_sends_fixed_contract_request() -> None:
    runtime_client, transport = client(RuntimeHttpResponse(200, valid_configuration()))

    configuration = await runtime_client.fetch("tenant-kassel", "correlation-1")

    assert configuration.tenant.id == "tenant-kassel"
    assert transport.calls == [
        (
            f"https://studio.test{RUNTIME_PATH}",
            {
                "Authorization": "Bearer service-token",
                "X-Studio-Tenant-Id": "tenant-kassel",
                "X-Correlation-Id": "correlation-1",
            },
            2.0,
        )
    ]


@pytest.mark.asyncio
async def test_accepts_unknown_optional_v1_fields() -> None:
    payload = valid_configuration()
    payload["optionalExtension"] = {"enabled": True}
    payload["tenant"]["optionalTenantField"] = "value"
    runtime_client, _ = client(RuntimeHttpResponse(200, payload))

    configuration = await runtime_client.fetch("tenant-kassel", "correlation-1")

    assert configuration.contract_version == "1.0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(configurationRevision="sha256:INVALID"),
        lambda payload: payload.update(authorizationRevision="missing-prefix"),
        lambda payload: payload.update(contractVersion="2.0"),
        lambda payload: payload["tenant"].update(timeZone="Not/A-Timezone"),
        lambda payload: payload["localization"].update(defaultLocale="en-US"),
        lambda payload: payload["conversationContentStorage"].update(mode="unsupported"),
    ],
)
async def test_rejects_invalid_known_contract_fields(mutate: Any) -> None:
    payload = valid_configuration()
    mutate(payload)
    runtime_client, _ = client(RuntimeHttpResponse(200, payload))

    with pytest.raises(StudioRuntimeClientError) as caught:
        await runtime_client.fetch("tenant-kassel", "correlation-1")

    assert caught.value.code == "studio_runtime_response_invalid"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_rejects_tenant_mismatch() -> None:
    payload = valid_configuration()
    payload["tenant"]["id"] = "tenant-fulda"
    runtime_client, _ = client(RuntimeHttpResponse(200, payload))

    with pytest.raises(StudioRuntimeClientError) as caught:
        await runtime_client.fetch("tenant-kassel", "correlation-1")

    assert caught.value.code == "studio_runtime_tenant_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (400, "malformed_request", False),
        (401, "service_authentication_invalid", False),
        (403, "service_action_forbidden", False),
        (404, "tenant_not_found", False),
        (409, "ssf_tenant_not_ready", True),
        (503, "runtime_configuration_unavailable", True),
    ],
)
async def test_preserves_stable_error_retryability(status: int, code: str, retryable: bool) -> None:
    payload = {
        "contractVersion": "1.0",
        "error": {
            "code": code,
            "message": "Runtime configuration is unavailable.",
            "retryable": retryable,
            "correlationId": "correlation-1",
        },
    }
    runtime_client, _ = client(RuntimeHttpResponse(status, payload))

    with pytest.raises(StudioRuntimeClientError) as caught:
        await runtime_client.fetch("tenant-kassel", "correlation-1")

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert caught.value.status == status


@pytest.mark.asyncio
async def test_rejects_invalid_error_envelope_and_unexpected_status() -> None:
    invalid_error_client, _ = client(RuntimeHttpResponse(404, {"error": "tenant secret"}))
    wrong_code_client, _ = client(
        RuntimeHttpResponse(
            400,
            {
                "contractVersion": "1.0",
                "error": {
                    "code": "unexpected_code",
                    "message": "Unavailable.",
                    "retryable": False,
                    "correlationId": "correlation-1",
                },
            },
        )
    )
    unexpected_client, _ = client(RuntimeHttpResponse(502, {"secret": "do-not-expose"}))

    with pytest.raises(StudioRuntimeClientError) as invalid_error:
        await invalid_error_client.fetch("tenant-kassel", "correlation-1")
    with pytest.raises(StudioRuntimeClientError) as wrong_code:
        await wrong_code_client.fetch("tenant-kassel", "correlation-1")
    with pytest.raises(StudioRuntimeClientError) as unexpected:
        await unexpected_client.fetch("tenant-kassel", "correlation-1")

    assert str(invalid_error.value) == "studio_runtime_error_invalid"
    assert str(wrong_code.value) == "studio_runtime_error_invalid"
    assert str(unexpected.value) == "studio_runtime_unexpected_status"
    assert unexpected.value.retryable is True


@pytest.mark.asyncio
async def test_rejects_disabled_storage_with_non_null_question() -> None:
    payload = deepcopy(valid_configuration())
    payload["conversationContentStorage"]["mode"] = "disabled"
    runtime_client, _ = client(RuntimeHttpResponse(200, payload))

    with pytest.raises(StudioRuntimeClientError) as caught:
        await runtime_client.fetch("tenant-kassel", "correlation-1")

    assert caught.value.code == "studio_runtime_response_invalid"


@pytest.mark.asyncio
async def test_rejects_header_control_characters_before_transport() -> None:
    runtime_client, transport = client(RuntimeHttpResponse(200, valid_configuration()))

    with pytest.raises(ValueError):
        await runtime_client.fetch("tenant-kassel\r\nX-Forged: true", "correlation-1")

    assert transport.calls == []


def test_rejects_base_url_that_could_change_the_fixed_path() -> None:
    async def token_provider() -> str:
        return "service-token"

    with pytest.raises(ValueError):
        StudioRuntimeClient("https://studio.test/prefix", token_provider)
    with pytest.raises(ValueError):
        StudioRuntimeClient("https://user:secret@studio.test", token_provider)
