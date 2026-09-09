"""Behavior tests for the tenant-bound Studio runtime integration."""

import hashlib
import json
from collections.abc import Mapping
from urllib.parse import urlsplit

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import services.api_gateway.studio_runtime_flow as runtime_flow_module
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.studio_runtime_client import (
    RuntimeConfiguration,
    RuntimeHttpResponse,
    StudioRuntimeClient,
    StudioRuntimeClientError,
)
from services.api_gateway.studio_runtime_flow import (
    StudioRuntimeFlow,
    StudioRuntimeFlowError,
    ValidatedRuntimeConfiguration,
    require_validated_runtime_configuration,
)
from services.api_gateway.studio_runtime_token import StudioTokenError
from services.api_gateway.tenant_context import StudioTenantContext
from services.studio_mock.app import app as studio_mock_app

REVISION = f"sha256:{'a' * 64}"
OTHER_REVISION = f"sha256:{'b' * 64}"


def _configuration(tenant_id: str, authorization_revision: str) -> RuntimeConfiguration:
    return RuntimeConfiguration.model_validate(
        {
            "contractVersion": "1.0",
            "configurationRevision": REVISION,
            "authorizationRevision": authorization_revision,
            "tenant": {
                "id": tenant_id,
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
    )


class StubRuntimeClient:
    def __init__(self, outcome: RuntimeConfiguration | Exception) -> None:
        self.outcome = outcome
        self.requests: list[tuple[str, str]] = []

    async def fetch(self, tenant_id: str, correlation_id: str) -> RuntimeConfiguration:
        self.requests.append((tenant_id, correlation_id))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _context(tenant_id: str = "tenant-kassel") -> StudioTenantContext:
    return StudioTenantContext(tenant_id=tenant_id, authorization_revision=REVISION)


@pytest.mark.asyncio
async def test_returns_configuration_only_when_tenant_and_revision_match() -> None:
    client = StubRuntimeClient(_configuration("tenant-kassel", REVISION))
    flow = StudioRuntimeFlow(client)

    result = await flow.resolve(_context(), "correlation-1")

    assert result.context == _context()
    assert result.configuration.tenant.id == "tenant-kassel"
    assert result.correlation_id == "correlation-1"
    assert client.requests == [("tenant-kassel", "correlation-1")]


@pytest.mark.asyncio
async def test_rejects_configuration_with_a_different_tenant() -> None:
    flow = StudioRuntimeFlow(StubRuntimeClient(_configuration("tenant-fulda", REVISION)))

    with pytest.raises(StudioRuntimeFlowError) as caught:
        await flow.resolve(_context(), "correlation-1")

    assert caught.value.code == "studio_runtime_tenant_mismatch"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_rejects_configuration_with_a_different_authorization_revision() -> None:
    flow = StudioRuntimeFlow(StubRuntimeClient(_configuration("tenant-kassel", OTHER_REVISION)))

    with pytest.raises(StudioRuntimeFlowError) as caught:
        await flow.resolve(_context(), "correlation-1")

    assert caught.value.code == "studio_runtime_authorization_mismatch"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_preserves_safe_upstream_failure_without_a_configuration() -> None:
    flow = StudioRuntimeFlow(
        StubRuntimeClient(
            StudioRuntimeClientError("runtime_configuration_unavailable", retryable=True)
        )
    )

    with pytest.raises(StudioRuntimeFlowError) as caught:
        await flow.resolve(_context(), "correlation-1")

    assert caught.value.code == "runtime_configuration_unavailable"
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_preserves_safe_service_token_failure_without_a_configuration() -> None:
    flow = StudioRuntimeFlow(
        StubRuntimeClient(StudioTokenError("studio_token_network_error", retryable=True))
    )

    with pytest.raises(StudioRuntimeFlowError) as caught:
        await flow.resolve(_context(), "correlation-1")

    assert caught.value.code == "studio_token_network_error"
    assert caught.value.retryable is True


class MockStudioTransport:
    """Run the V1 client against the local Studio mock at its HTTP boundary."""

    def __init__(self) -> None:
        self.client = TestClient(studio_mock_app)

    async def get(
        self,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> RuntimeHttpResponse:
        response = self.client.get(urlsplit(url).path, headers=dict(headers))
        return RuntimeHttpResponse(status=response.status_code, payload=response.json())


def _mock_authorization_revision(tenant_id: str) -> str:
    authorization = {
        "permissions": ["ssf.runtime-configuration.read"],
        "tenantId": tenant_id,
    }
    encoded = json.dumps(authorization, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@pytest.mark.asyncio
async def test_mock_backed_flow_accepts_only_the_matching_tenant_revision() -> None:
    tenant_id = "tenant-kassel"
    authorization_revision = _mock_authorization_revision(tenant_id)

    async def service_token() -> str:
        return "studio-mock-authorized-token"

    flow = StudioRuntimeFlow(
        StudioRuntimeClient(
            "http://studio-mock.test",
            service_token,
            transport=MockStudioTransport(),
        )
    )

    result = await flow.resolve(
        StudioTenantContext(tenant_id, authorization_revision),
        "mock-flow-correlation",
    )

    assert result.configuration.tenant.id == tenant_id
    assert result.configuration.authorization_revision == authorization_revision


@pytest.mark.asyncio
async def test_mock_backed_flow_rejects_a_token_revision_that_does_not_match() -> None:
    async def service_token() -> str:
        return "studio-mock-authorized-token"

    flow = StudioRuntimeFlow(
        StudioRuntimeClient(
            "http://studio-mock.test",
            service_token,
            transport=MockStudioTransport(),
        )
    )

    with pytest.raises(StudioRuntimeFlowError) as caught:
        await flow.resolve(
            StudioTenantContext("tenant-kassel", OTHER_REVISION),
            "mock-flow-correlation",
        )

    assert caught.value.code == "studio_runtime_authorization_mismatch"


class StubRuntimeFlow:
    def __init__(self, outcome: ValidatedRuntimeConfiguration | Exception) -> None:
        self.outcome = outcome
        self.requests: list[tuple[StudioTenantContext, str]] = []

    async def resolve(
        self,
        context: StudioTenantContext,
        correlation_id: str,
    ) -> ValidatedRuntimeConfiguration:
        self.requests.append((context, correlation_id))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return ValidatedRuntimeConfiguration(
            context=context,
            configuration=self.outcome.configuration,
            correlation_id=correlation_id,
        )


def _dependency_client(
    monkeypatch: pytest.MonkeyPatch,
    runtime_flow: StubRuntimeFlow,
) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[require_ssf_user] = lambda: {
        "sub": "user-1",
        "studio_tenant_id": "tenant-kassel",
        "ssf_authorization_revision": REVISION,
    }
    monkeypatch.setattr(runtime_flow_module, "runtime_flow_from_environment", lambda: runtime_flow)

    @app.get("/runtime-operation")
    async def runtime_operation(
        result: ValidatedRuntimeConfiguration = Depends(require_validated_runtime_configuration),
    ) -> dict[str, str]:
        return {
            "tenant_id": result.context.tenant_id,
            "correlation_id": result.correlation_id,
        }

    return TestClient(app)


def test_dependency_forwards_valid_correlation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context()
    flow = StubRuntimeFlow(
        ValidatedRuntimeConfiguration(context, _configuration("tenant-kassel", REVISION), "unused")
    )

    response = _dependency_client(monkeypatch, flow).get(
        "/runtime-operation", headers={"X-Correlation-Id": "request-123"}
    )

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-kassel", "correlation_id": "request-123"}
    assert flow.requests == [(context, "request-123")]


def test_dependency_generates_correlation_id_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context()
    flow = StubRuntimeFlow(
        ValidatedRuntimeConfiguration(context, _configuration("tenant-kassel", REVISION), "unused")
    )

    response = _dependency_client(monkeypatch, flow).get("/runtime-operation")

    assert response.status_code == 200
    correlation_id = response.json()["correlation_id"]
    assert len(correlation_id) == 36
    assert flow.requests == [(context, correlation_id)]


def test_dependency_returns_safe_error_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    flow = StubRuntimeFlow(
        StudioRuntimeFlowError("runtime_configuration_unavailable", retryable=True)
    )

    response = _dependency_client(monkeypatch, flow).get("/runtime-operation")

    assert response.status_code == 503
    assert response.json() == {"detail": "runtime_configuration_unavailable"}
