"""Explicit tenant dependencies for API-gateway route tests."""

import pytest

from services.api_gateway.app import app
from services.api_gateway.studio_runtime_client import RuntimeConfiguration
from services.api_gateway.studio_runtime_flow import (
    ValidatedRuntimeConfiguration,
    require_validated_runtime_configuration,
)
from services.api_gateway.tenant_context import (
    StudioTenantContext,
    require_studio_tenant_context,
)

REVISION = f"sha256:{'a' * 64}"


def _configuration() -> RuntimeConfiguration:
    return RuntimeConfiguration.model_validate(
        {
            "contractVersion": "1.0",
            "configurationRevision": REVISION,
            "authorizationRevision": REVISION,
            "tenant": {
                "id": "tenant-test",
                "displayName": "Test Tenant",
                "timeZone": "Europe/Berlin",
            },
            "branding": {"logo": None, "icon": None},
            "localization": {
                "defaultLocale": "de-DE",
                "locales": [
                    {
                        "locale": "de-DE",
                        "authenticatedHomeExplanationHtml": "<p>Admin</p>",
                        "guestExplanationHtml": "<p>Guest</p>",
                        "conversationContentStorageQuestionHtml": "<p>Store?</p>",
                    }
                ],
            },
            "conversationContentStorage": {"mode": "ask"},
        }
    )


@pytest.fixture(autouse=True)
def tenant_dependencies():
    context = StudioTenantContext("tenant-test", REVISION)
    app.dependency_overrides[require_studio_tenant_context] = lambda: context
    app.dependency_overrides[require_validated_runtime_configuration] = lambda: (
        ValidatedRuntimeConfiguration(context, _configuration(), "test-correlation")
    )
    yield
    app.dependency_overrides.pop(require_studio_tenant_context, None)
    app.dependency_overrides.pop(require_validated_runtime_configuration, None)
