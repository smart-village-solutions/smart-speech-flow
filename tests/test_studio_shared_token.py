"""All Studio clients share one service token (tasks.md 1.4)."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

import pytest

from services.api_gateway.app import app, lifespan
from services.api_gateway.studio_content import ContentRecordingFetcher
from services.api_gateway.studio_installation_client import StudioInstallationClient
from services.api_gateway.studio_login_directory_client import StudioLoginDirectoryClient
from services.api_gateway.studio_runtime_token import (
    AiohttpTokenTransport,
    StudioRuntimeTokenProvider,
    StudioTokenConfig,
    TokenResponse,
)
from services.api_gateway.studio_runtime_v2_client import StudioRuntimeV2Client
from services.api_gateway.studio_v1 import AiohttpStudioV1Transport, StudioV1HttpResponse

_TOKEN_VARIABLES = (
    "STUDIO_RUNTIME_FIXED_TOKEN",
    "STUDIO_RUNTIME_TOKEN_URL",
    "STUDIO_RUNTIME_CLIENT_SECRET",
)


class CountingTokenTransport:
    def __init__(self) -> None:
        self.calls = 0

    async def post_form(
        self, url: str, data: Mapping[str, str], timeout_seconds: float
    ) -> TokenResponse:
        self.calls += 1
        await asyncio.sleep(0.01)
        return TokenResponse(200, {"access_token": "shared-token", "expires_in": 300})


class RecordingStudioTransport:
    def __init__(self) -> None:
        self.authorizations: list[str] = []

    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> StudioV1HttpResponse:
        self.authorizations.append(headers["Authorization"])
        return StudioV1HttpResponse(503, None)


@pytest.fixture(autouse=True)
def quiet_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSF_QUALITY_TELEMETRY_MODE", "disabled")


async def test_concurrent_clients_make_one_token_request() -> None:
    token_transport = CountingTokenTransport()
    provider = StudioRuntimeTokenProvider(
        StudioTokenConfig(token_url="https://keycloak.test/token", client_secret="placeholder"),
        transport=token_transport,
    )
    studio = RecordingStudioTransport()
    base = "https://studio.test"

    await asyncio.gather(
        StudioRuntimeV2Client(base, provider.get_token, transport=studio).fetch(
            "tenant-kassel", "c-2"
        ),
        StudioLoginDirectoryClient(base, provider.get_token, transport=studio).fetch("c-3"),
        StudioInstallationClient(base, provider.get_token, transport=studio).fetch("c-4"),
        return_exceptions=True,
    )

    assert token_transport.calls == 1
    assert studio.authorizations == ["Bearer shared-token"] * 3


def _route_studio_traffic(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[CountingTokenTransport, RecordingStudioTransport]:
    token_transport = CountingTokenTransport()
    studio = RecordingStudioTransport()

    def post_form(_self: Any, *args: Any) -> Any:
        return token_transport.post_form(*args)

    def get(_self: Any, *args: Any) -> Any:
        return studio.get(*args)

    monkeypatch.setattr(AiohttpTokenTransport, "post_form", post_form)
    monkeypatch.setattr(AiohttpStudioV1Transport, "get", get)
    return token_transport, studio


async def test_the_lifespan_gives_every_studio_client_one_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "https://studio.test")
    monkeypatch.delenv("STUDIO_RUNTIME_FIXED_TOKEN", raising=False)
    monkeypatch.setenv("STUDIO_RUNTIME_TOKEN_URL", "https://keycloak.test/token")
    monkeypatch.setenv("STUDIO_RUNTIME_CLIENT_SECRET", "placeholder")
    token_transport, studio = _route_studio_traffic(monkeypatch)

    async with lifespan(app):
        dependencies = app.state.dependencies
        assert dependencies.studio_token_provider is not None
        # The runtime client sits behind the content cache's recording fetcher.
        assert isinstance(dependencies.studio_runtime_flow.client, ContentRecordingFetcher)
        await asyncio.gather(
            dependencies.studio_runtime_flow.client.fetch("tenant-kassel", "c-1"),
            dependencies.login_directory.get("c-2"),
            dependencies.studio_content.installation_content("c-3"),
            return_exceptions=True,
        )

    assert token_transport.calls == 1
    assert studio.authorizations == ["Bearer shared-token"] * 3


async def test_no_provider_and_no_studio_clients_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "https://studio.test")
    for name in _TOKEN_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    async with lifespan(app):
        dependencies = app.state.dependencies
        assert dependencies.studio_token_provider is None
        assert dependencies.studio_runtime_flow is None
        assert dependencies.login_directory is None
