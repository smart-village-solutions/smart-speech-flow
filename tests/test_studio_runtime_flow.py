"""Behavior tests for the tenant-bound Studio runtime integration."""

import hashlib
import hmac
import json
from collections.abc import Mapping
from urllib.parse import urlsplit

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import services.api_gateway.studio_runtime_flow as runtime_flow_module
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.dependencies import get_studio_runtime_flow
from services.api_gateway.studio_runtime_flow import (
    StudioRuntimeFlow,
    StudioRuntimeFlowError,
    ValidatedRuntimeConfiguration,
    require_validated_runtime_configuration,
)
from services.api_gateway.studio_runtime_token import StudioTokenError
from services.api_gateway.studio_runtime_v2_client import (
    StudioRuntimeV2Client,
    StudioRuntimeV2ClientError,
)
from services.api_gateway.studio_v1 import StudioV1HttpResponse
from services.api_gateway.studio_v2 import RuntimeRead
from services.api_gateway.tenant_context import StudioTenantContext
from services.studio_mock.app import app as studio_mock_app
from tests.runtime_policy_helpers import runtime_read

REVISION = f"sha256:{'a' * 64}"
OTHER_REVISION = f"sha256:{'b' * 64}"


class StubRuntimeClient:
    def __init__(self, outcome: RuntimeRead | Exception) -> None:
        self.outcome = outcome
        self.requests: list[tuple[str, str]] = []

    async def fetch(self, tenant_id: str, correlation_id: str) -> RuntimeRead:
        self.requests.append((tenant_id, correlation_id))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _context(tenant_id: str = "tenant-kassel") -> StudioTenantContext:
    return StudioTenantContext(tenant_id=tenant_id, authorization_revision=REVISION)


@pytest.mark.asyncio
async def test_returns_configuration_only_when_tenant_and_revision_match() -> None:
    client = StubRuntimeClient(runtime_read("tenant-kassel"))
    flow = StudioRuntimeFlow(client)

    result = await flow.resolve(_context(), "correlation-1")

    assert result.context == _context()
    assert result.read.policy.tenant_id == "tenant-kassel"
    assert result.correlation_id == "correlation-1"
    assert client.requests == [("tenant-kassel", "correlation-1")]


@pytest.mark.asyncio
async def test_rejects_configuration_with_a_different_tenant() -> None:
    flow = StudioRuntimeFlow(StubRuntimeClient(runtime_read("tenant-fulda")))

    context = _context()
    with pytest.raises(StudioRuntimeFlowError) as caught:
        await flow.resolve(context, "correlation-1")

    assert caught.value.code == "studio_runtime_tenant_mismatch"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_rejects_a_non_ascii_studio_tenant_as_a_mismatch() -> None:
    flow = StudioRuntimeFlow(StubRuntimeClient(runtime_read("tenant-kässel")))

    with pytest.raises(StudioRuntimeFlowError) as caught:
        await flow.resolve(_context(), "correlation-1")

    assert caught.value.code == "studio_runtime_tenant_mismatch"


@pytest.mark.asyncio
async def test_compares_the_tenant_id_in_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    compared: list[tuple[object, object]] = []
    compare_digest = hmac.compare_digest

    def recording_compare_digest(left: bytes | str, right: bytes | str) -> bool:
        compared.append((left, right))
        return compare_digest(left, right)

    monkeypatch.setattr(runtime_flow_module.hmac, "compare_digest", recording_compare_digest)
    flow = StudioRuntimeFlow(StubRuntimeClient(runtime_read("tenant-kassel")))

    await flow.resolve(_context(), "correlation-1")

    assert (b"tenant-kassel", b"tenant-kassel") in compared


@pytest.mark.asyncio
async def test_accepts_configuration_whatever_the_token_revision() -> None:
    flow = StudioRuntimeFlow(StubRuntimeClient(runtime_read("tenant-kassel")))

    result = await flow.resolve(StudioTenantContext("tenant-kassel", OTHER_REVISION), "c-1")

    assert result.read.policy.tenant_id == "tenant-kassel"


@pytest.mark.asyncio
async def test_preserves_safe_upstream_failure_without_a_configuration() -> None:
    flow = StudioRuntimeFlow(
        StubRuntimeClient(
            StudioRuntimeV2ClientError("runtime_configuration_unavailable", retryable=True)
        )
    )

    context = _context()
    with pytest.raises(StudioRuntimeFlowError) as caught:
        await flow.resolve(context, "correlation-1")

    assert caught.value.code == "runtime_configuration_unavailable"
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_preserves_safe_service_token_failure_without_a_configuration() -> None:
    flow = StudioRuntimeFlow(
        StubRuntimeClient(StudioTokenError("studio_token_network_error", retryable=True))
    )

    context = _context()
    with pytest.raises(StudioRuntimeFlowError) as caught:
        await flow.resolve(context, "correlation-1")

    assert caught.value.code == "studio_token_network_error"
    assert caught.value.retryable is True


class MockStudioTransport:
    """Run the v2 client against the local Studio mock at its HTTP boundary."""

    def __init__(self) -> None:
        self.client = TestClient(studio_mock_app)

    async def get(
        self,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> StudioV1HttpResponse:
        response = self.client.get(urlsplit(url).path, headers=dict(headers))
        return StudioV1HttpResponse(status=response.status_code, payload=response.json())


async def _mock_service_token() -> str:
    return "studio-mock-authorized-token"


def _mock_backed_flow() -> StudioRuntimeFlow:
    return StudioRuntimeFlow(
        StudioRuntimeV2Client(
            "http://studio-mock.test", _mock_service_token, transport=MockStudioTransport()
        )
    )


@pytest.mark.asyncio
async def test_mock_backed_flow_resolves_the_tenants_v2_policy() -> None:
    result = await _mock_backed_flow().resolve(_context("tenant-kassel"), "mock-flow-correlation")

    assert result.read.policy.tenant_id == "tenant-kassel"
    assert (result.read.policy.mode, result.read.policy.retention_hours) == ("ask", 4320)
    assert result.read.policy.contract_version == "2.0"


@pytest.mark.asyncio
async def test_mock_backed_flow_ignores_a_token_revision_that_does_not_match() -> None:
    context = StudioTenantContext("tenant-kassel", OTHER_REVISION)

    result = await _mock_backed_flow().resolve(context, "mock-flow-correlation")

    assert result.read.policy.tenant_id == "tenant-kassel"


class _InvalidContentTransport(MockStudioTransport):
    async def get(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> StudioV1HttpResponse:
        response = await super().get(url, headers, timeout_seconds)
        body = dict(response.payload)
        body["staff"] = {"locale": 7}
        body["guestLanguages"] = [{"locale": "en", "feedback": {"questions": "none"}}]
        return StudioV1HttpResponse(status=response.status, payload=body)


@pytest.mark.asyncio
async def test_invalid_content_still_resolves_the_policy() -> None:
    flow = StudioRuntimeFlow(
        StudioRuntimeV2Client(
            "http://studio-mock.test", _mock_service_token, transport=_InvalidContentTransport()
        )
    )

    result = await flow.resolve(_context("tenant-kassel"), "mock-flow-correlation")

    assert result.read.policy.mode == "ask"
    assert result.read.content.staff is None
    assert result.read.content.guest_languages == ()


class _TokenProvider:
    async def get_token(self) -> str:
        return "token"


def test_the_environment_builds_the_v2_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "https://studio.example")

    flow = runtime_flow_module.runtime_flow_from_environment(_TokenProvider())

    assert isinstance(flow.client, StudioRuntimeV2Client)


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
            read=self.outcome.read,
            correlation_id=correlation_id,
        )


def _dependency_client(runtime_flow: StubRuntimeFlow | StudioRuntimeFlow) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[require_ssf_user] = lambda: {
        "sub": "user-1",
        "_ssf_verified_tenant_id": "tenant-kassel",
    }
    app.dependency_overrides[get_studio_runtime_flow] = lambda: runtime_flow

    @app.get("/runtime-operation")
    async def runtime_operation(
        result: ValidatedRuntimeConfiguration = Depends(require_validated_runtime_configuration),
    ) -> dict[str, str]:
        return {
            "tenant_id": result.context.tenant_id,
            "correlation_id": result.correlation_id,
        }

    return TestClient(app)


def test_dependency_forwards_valid_correlation_id() -> None:
    context = _context()
    flow = StubRuntimeFlow(
        ValidatedRuntimeConfiguration(context, runtime_read("tenant-kassel"), "unused")
    )

    response = _dependency_client(flow).get(
        "/runtime-operation", headers={"X-Correlation-Id": "request-123"}
    )

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-kassel", "correlation_id": "request-123"}
    assert flow.requests == [(StudioTenantContext("tenant-kassel"), "request-123")]


def test_dependency_generates_correlation_id_when_absent() -> None:
    context = _context()
    flow = StubRuntimeFlow(
        ValidatedRuntimeConfiguration(context, runtime_read("tenant-kassel"), "unused")
    )

    response = _dependency_client(flow).get("/runtime-operation")

    assert response.status_code == 200
    correlation_id = response.json()["correlation_id"]
    assert len(correlation_id) == 36
    assert flow.requests == [(StudioTenantContext("tenant-kassel"), correlation_id)]


def test_dependency_returns_safe_error_without_fallback() -> None:
    flow = StubRuntimeFlow(
        StudioRuntimeFlowError("runtime_configuration_unavailable", retryable=True)
    )

    response = _dependency_client(flow).get("/runtime-operation")

    assert response.status_code == 503
    assert response.json() == {"detail": "runtime_configuration_unavailable"}


def test_dependency_reports_a_non_ascii_tenant_mismatch_as_502() -> None:
    flow = StudioRuntimeFlow(StubRuntimeClient(runtime_read("tenant-kässel")))

    response = _dependency_client(flow).get("/runtime-operation")

    assert response.status_code == 502
    assert response.json() == {"detail": "studio_runtime_tenant_mismatch"}
