"""Tests for the Studio runtime service-token provider."""

import asyncio
from typing import Mapping

import pytest

from services.api_gateway.studio_runtime_token import (
    DEFAULT_AUDIENCE,
    DEFAULT_CLIENT_ID,
    StudioRuntimeTokenProvider,
    StudioTokenConfig,
    StudioTokenError,
    TokenResponse,
)


class StubTransport:
    def __init__(self, responses: list[TokenResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Mapping[str, str], float]] = []

    async def post_form(
        self, url: str, data: Mapping[str, str], timeout_seconds: float
    ) -> TokenResponse:
        self.calls.append((url, data, timeout_seconds))
        await asyncio.sleep(0)
        return self.responses.pop(0)


def config(**overrides: object) -> StudioTokenConfig:
    values = {
        "token_url": "https://keycloak.test/token",
        "client_secret": "top-secret",
        "timeout_seconds": 2.0,
        "refresh_skew_seconds": 10.0,
    }
    values.update(overrides)
    return StudioTokenConfig(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_concurrent_calls_share_one_valid_token() -> None:
    transport = StubTransport([TokenResponse(200, {"access_token": "token-1", "expires_in": 60})])
    provider = StudioRuntimeTokenProvider(config(), transport=transport, clock=lambda: 100.0)

    tokens = await asyncio.gather(*(provider.get_token() for _ in range(5)))

    assert tokens == ["token-1"] * 5
    assert len(transport.calls) == 1
    _, form, timeout = transport.calls[0]
    assert form == {
        "grant_type": "client_credentials",
        "client_id": DEFAULT_CLIENT_ID,
        "client_secret": "top-secret",
        "audience": DEFAULT_AUDIENCE,
    }
    assert timeout == 2.0


@pytest.mark.asyncio
async def test_expiring_token_is_renewed_before_expiry() -> None:
    now = [100.0]
    transport = StubTransport(
        [
            TokenResponse(200, {"access_token": "token-1", "expires_in": 60}),
            TokenResponse(200, {"access_token": "token-2", "expires_in": 60}),
        ]
    )
    provider = StudioRuntimeTokenProvider(config(), transport=transport, clock=lambda: now[0])

    assert await provider.get_token() == "token-1"
    now[0] = 151.0
    assert await provider.get_token() == "token-2"


@pytest.mark.asyncio
async def test_fixed_token_avoids_network_for_local_contract_tests() -> None:
    transport = StubTransport([])
    provider = StudioRuntimeTokenProvider(
        config(fixed_token="fixed-mock-token"), transport=transport
    )

    assert await provider.get_token() == "fixed-mock-token"
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code", "retryable"),
    [
        (
            TokenResponse(401, {"error": "invalid_client"}),
            "studio_token_authentication_failed",
            False,
        ),
        (TokenResponse(503, {"error": "unavailable"}), "studio_token_authentication_failed", True),
        (
            TokenResponse(200, {"access_token": "secret-token"}),
            "studio_token_response_invalid",
            False,
        ),
    ],
)
async def test_failures_are_classified_without_exposing_response_values(
    response: TokenResponse, code: str, retryable: bool
) -> None:
    provider = StudioRuntimeTokenProvider(config(), transport=StubTransport([response]))

    with pytest.raises(StudioTokenError) as caught:
        await provider.get_token()

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert str(caught.value) == code
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_network_failure_is_retryable_and_redacted() -> None:
    class FailingTransport:
        async def post_form(
            self, url: str, data: Mapping[str, str], timeout_seconds: float
        ) -> TokenResponse:
            raise TimeoutError(f"leaked {data['client_secret']}")

    provider = StudioRuntimeTokenProvider(config(), transport=FailingTransport())

    with pytest.raises(StudioTokenError) as caught:
        await provider.get_token()

    assert caught.value.code == "studio_token_network_error"
    assert caught.value.retryable is True
    assert "top-secret" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_rejects_unbounded_or_incomplete_configuration() -> None:
    with pytest.raises(StudioTokenError):
        config(timeout_seconds=31.0)
    with pytest.raises(StudioTokenError):
        config(refresh_skew_seconds=-1.0)
    with pytest.raises(StudioTokenError):
        config(client_secret="")
