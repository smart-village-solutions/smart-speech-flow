"""Contract tests for the Studio administrative login-directory V1 client."""

from copy import deepcopy
from typing import Any, Mapping

import pytest

from services.api_gateway.studio_login_directory_client import (
    DIRECTORY_PATH,
    DirectoryHttpResponse,
    StudioLoginDirectoryClient,
    StudioLoginDirectoryClientError,
)

REVISION = f"sha256:{'a' * 64}"


def valid_directory() -> dict[str, object]:
    return {
        "contractVersion": "1.0",
        "directoryRevision": REVISION,
        "tenants": [
            {
                "id": "tenant-kassel",
                "displayName": "Stadt Kassel",
                "realm": "kassel-ssf-2025",
            }
        ],
    }


class StubTokenProvider:
    async def get_token(self) -> str:
        return "service-token"


class StubTransport:
    def __init__(self, response: DirectoryHttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, Mapping[str, str], float]] = []

    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> DirectoryHttpResponse:
        self.calls.append((url, headers, timeout_seconds))
        return self.response


def client(
    response: DirectoryHttpResponse,
) -> tuple[StudioLoginDirectoryClient, StubTransport]:
    transport = StubTransport(response)
    return (
        StudioLoginDirectoryClient(
            "https://studio.test",
            StubTokenProvider(),
            transport=transport,
            timeout_seconds=2.0,
        ),
        transport,
    )


@pytest.mark.asyncio
async def test_accepts_valid_directory_and_sends_tenant_unbound_request() -> None:
    directory_client, transport = client(DirectoryHttpResponse(200, valid_directory()))

    directory = await directory_client.fetch("correlation-1")

    assert directory.directory_revision == REVISION
    assert directory.tenants[0].model_dump(by_alias=True) == {
        "id": "tenant-kassel",
        "displayName": "Stadt Kassel",
        "realm": "kassel-ssf-2025",
    }
    assert transport.calls == [
        (
            f"https://studio.test{DIRECTORY_PATH}",
            {
                "Authorization": "Bearer service-token",
                "X-Correlation-Id": "correlation-1",
            },
            2.0,
        )
    ]


@pytest.mark.asyncio
async def test_accepts_an_empty_tenant_directory() -> None:
    payload = valid_directory()
    payload["tenants"] = []
    directory_client, _ = client(DirectoryHttpResponse(200, payload))

    directory = await directory_client.fetch("correlation-1")

    assert directory.tenants == ()


@pytest.mark.asyncio
async def test_accepts_unknown_optional_v1_fields() -> None:
    payload = valid_directory()
    payload["optionalDirectoryField"] = {"enabled": True}
    tenants = payload["tenants"]
    assert isinstance(tenants, list)
    tenant = tenants[0]
    assert isinstance(tenant, dict)
    tenant["optionalTenantField"] = "value"
    directory_client, _ = client(DirectoryHttpResponse(200, payload))

    directory = await directory_client.fetch("correlation-1")

    assert directory.contract_version == "1.0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(contractVersion="2.0"),
        lambda payload: payload.update(directoryRevision="sha256:INVALID"),
        lambda payload: payload["tenants"][0].update(id="tenant kassel"),
        lambda payload: payload["tenants"][0].update(realm="kassel/unsafe"),
        lambda payload: payload.update(
            tenants=[payload["tenants"][0], deepcopy(payload["tenants"][0])]
        ),
        lambda payload: payload.update(
            tenants=[
                payload["tenants"][0],
                {
                    "id": "tenant-fulda",
                    "displayName": "Stadt Fulda",
                    "realm": "kassel-ssf-2025",
                },
            ]
        ),
        lambda payload: payload["tenants"][0].update(displayName=""),
    ],
)
async def test_rejects_invalid_known_directory_fields(mutate: Any) -> None:
    payload = valid_directory()
    mutate(payload)
    directory_client, _ = client(DirectoryHttpResponse(200, payload))

    with pytest.raises(StudioLoginDirectoryClientError) as caught:
        await directory_client.fetch("correlation-1")

    assert caught.value.code == "studio_login_directory_response_invalid"
    assert caught.value.retryable is False
    assert caught.value.status == 200


@pytest.mark.asyncio
async def test_rejects_a_non_object_success_payload() -> None:
    directory_client, _ = client(DirectoryHttpResponse(200, ["Studio secret"]))  # type: ignore[arg-type]

    with pytest.raises(StudioLoginDirectoryClientError) as caught:
        await directory_client.fetch("correlation-1")

    assert caught.value.code == "studio_login_directory_response_invalid"
    assert "Studio secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_rejects_correlation_id_control_characters_before_transport() -> None:
    directory_client, transport = client(DirectoryHttpResponse(200, valid_directory()))

    with pytest.raises(ValueError):
        await directory_client.fetch("correlation-1\r\nX-Forged: true")

    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "service_authentication_invalid", False),
        (403, "service_action_forbidden", False),
        (503, "admin_login_directory_unavailable", True),
    ],
)
async def test_preserves_stable_error_retryability(status: int, code: str, retryable: bool) -> None:
    directory_client, _ = client(
        DirectoryHttpResponse(
            status,
            {
                "contractVersion": "1.0",
                "error": {
                    "code": code,
                    "message": "Directory is unavailable.",
                    "retryable": retryable,
                    "correlationId": "correlation-1",
                },
            },
        )
    )

    with pytest.raises(StudioLoginDirectoryClientError) as caught:
        await directory_client.fetch("correlation-1")

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert caught.value.status == status


@pytest.mark.asyncio
async def test_rejects_malformed_error_envelopes_and_unexpected_statuses_without_studio_content() -> (
    None
):
    malformed_error_client, _ = client(DirectoryHttpResponse(401, {"error": "Studio secret"}))
    wrong_error_code_client, _ = client(
        DirectoryHttpResponse(
            403,
            {
                "contractVersion": "1.0",
                "error": {
                    "code": "unexpected_code",
                    "message": "Studio secret",
                    "retryable": False,
                    "correlationId": "correlation-1",
                },
            },
        )
    )
    unexpected_status_client, _ = client(DirectoryHttpResponse(502, {"secret": "Studio secret"}))

    with pytest.raises(StudioLoginDirectoryClientError) as malformed_error:
        await malformed_error_client.fetch("correlation-1")
    with pytest.raises(StudioLoginDirectoryClientError) as wrong_error_code:
        await wrong_error_code_client.fetch("correlation-1")
    with pytest.raises(StudioLoginDirectoryClientError) as unexpected_status:
        await unexpected_status_client.fetch("correlation-1")

    assert malformed_error.value.code == "studio_login_directory_error_invalid"
    assert wrong_error_code.value.code == "studio_login_directory_error_invalid"
    assert unexpected_status.value.code == "studio_login_directory_unexpected_status"
    for error in (
        malformed_error.value,
        wrong_error_code.value,
        unexpected_status.value,
    ):
        assert "Studio secret" not in str(error)


@pytest.mark.asyncio
async def test_rejects_invalid_service_token_before_transport() -> None:
    class InvalidTokenProvider:
        async def get_token(self) -> str:
            return "service-token\r\nX-Forged: true"

    transport = StubTransport(DirectoryHttpResponse(200, valid_directory()))
    directory_client = StudioLoginDirectoryClient(
        "https://studio.test", InvalidTokenProvider(), transport=transport
    )

    with pytest.raises(StudioLoginDirectoryClientError) as caught:
        await directory_client.fetch("correlation-1")

    assert caught.value.code == "studio_login_directory_token_invalid"
    assert caught.value.retryable is False
    assert transport.calls == []


@pytest.mark.asyncio
async def test_classifies_transport_timeout_as_retryable_network_error() -> None:
    class TimeoutTransport:
        async def get(
            self, url: str, headers: Mapping[str, str], timeout_seconds: float
        ) -> DirectoryHttpResponse:
            raise TimeoutError("Studio secret")

    directory_client = StudioLoginDirectoryClient(
        "https://studio.test", StubTokenProvider(), transport=TimeoutTransport()
    )

    with pytest.raises(StudioLoginDirectoryClientError) as caught:
        await directory_client.fetch("correlation-1")

    assert caught.value.code == "studio_login_directory_network_error"
    assert caught.value.retryable is True
    assert caught.value.__cause__ is None


def test_rejects_base_urls_that_could_change_the_fixed_directory_path() -> None:
    with pytest.raises(ValueError):
        StudioLoginDirectoryClient("https://studio.test/prefix", StubTokenProvider())
    with pytest.raises(ValueError):
        StudioLoginDirectoryClient("https://user:secret@studio.test", StubTokenProvider())
