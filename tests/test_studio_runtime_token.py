"""Tests for the Studio runtime service-token provider."""

import asyncio
from typing import Mapping

import pytest

from services.api_gateway.studio_runtime_token import (
    AiohttpTokenTransport,
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


@pytest.mark.asyncio
async def test_unexpected_transport_failure_is_not_retryable_and_redacted() -> None:
    class FailingTransport:
        async def post_form(
            self, url: str, data: Mapping[str, str], timeout_seconds: float
        ) -> TokenResponse:
            raise RuntimeError(f"leaked {data['client_secret']}")

    provider = StudioRuntimeTokenProvider(config(), transport=FailingTransport())

    with pytest.raises(StudioTokenError) as caught:
        await provider.get_token()

    assert caught.value.code == "studio_token_network_error"
    assert caught.value.retryable is False
    assert "top-secret" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_aiohttp_transport_preserves_non_2xx_status_with_non_mapping_json(
    monkeypatch,
) -> None:
    class FakeResponse:
        status = 401

        async def json(self) -> list[str]:
            return ["invalid_client"]

        async def __aenter__(self) -> "FakeResponse":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeSession:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def post(self, url: str, data: Mapping[str, str]) -> FakeResponse:
            return FakeResponse()

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        "services.api_gateway.studio_runtime_token.aiohttp.ClientSession", FakeSession
    )

    response = await AiohttpTokenTransport().post_form(
        "https://keycloak.test/token", {"grant_type": "client_credentials"}, 2.0
    )

    assert response.status == 401
    assert response.payload == {}


def test_rejects_unbounded_or_incomplete_configuration() -> None:
    with pytest.raises(StudioTokenError):
        config(timeout_seconds=31.0)
    with pytest.raises(StudioTokenError):
        config(refresh_skew_seconds=-1.0)
    with pytest.raises(StudioTokenError):
        config(client_secret="")


def test_loads_contract_defaults_and_fixed_token_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_RUNTIME_FIXED_TOKEN", "  local-token  ")
    monkeypatch.delenv("STUDIO_RUNTIME_TOKEN_URL", raising=False)
    monkeypatch.delenv("STUDIO_RUNTIME_CLIENT_SECRET", raising=False)

    loaded = StudioTokenConfig.from_env()

    assert loaded.fixed_token == "local-token"
    assert loaded.client_id == DEFAULT_CLIENT_ID
    assert loaded.audience == DEFAULT_AUDIENCE


def test_rejects_whitespace_only_client_secret_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_RUNTIME_TOKEN_URL", "https://keycloak.test/token")
    monkeypatch.setenv("STUDIO_RUNTIME_CLIENT_SECRET", "   ")
    monkeypatch.delenv("STUDIO_RUNTIME_FIXED_TOKEN", raising=False)

    with pytest.raises(StudioTokenError) as caught:
        StudioTokenConfig.from_env()

    assert caught.value.code == "studio_token_configuration_invalid"


def test_normalizes_configuration_values_and_redacts_sensitive_repr() -> None:
    loaded = StudioTokenConfig(
        token_url="  https://keycloak.test/token  ",
        client_secret="  top-secret  ",
        client_id="  runtime-client  ",
        audience="  runtime-audience  ",
        fixed_token="  fixed-token  ",
    )

    assert loaded.token_url == "https://keycloak.test/token"
    assert loaded.client_secret == "top-secret"
    assert loaded.client_id == "runtime-client"
    assert loaded.audience == "runtime-audience"
    assert loaded.fixed_token == "fixed-token"
    assert "top-secret" not in repr(loaded)
    assert "fixed-token" not in repr(loaded)


def test_classifies_invalid_numeric_environment_configuration(monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_RUNTIME_FIXED_TOKEN", "local-token")
    monkeypatch.setenv("STUDIO_RUNTIME_TOKEN_TIMEOUT_SECONDS", "invalid")

    with pytest.raises(StudioTokenError) as caught:
        StudioTokenConfig.from_env()

    assert caught.value.code == "studio_token_configuration_invalid"
