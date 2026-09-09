"""Behavior tests for the tenant-bound Studio runtime integration."""

import pytest

from services.api_gateway.studio_runtime_client import (
    RuntimeConfiguration,
    StudioRuntimeClientError,
)
from services.api_gateway.studio_runtime_flow import (
    StudioRuntimeFlow,
    StudioRuntimeFlowError,
)
from services.api_gateway.tenant_context import StudioTenantContext

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
