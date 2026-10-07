"""Explicit tenant dependencies for API-gateway route tests."""

import pytest

from services.api_gateway.app import app
from services.api_gateway.studio_runtime_flow import (
    ValidatedRuntimeConfiguration,
    require_validated_runtime_configuration,
)
from services.api_gateway.tenant_context import StudioTenantContext, require_studio_tenant_context
from tests.audio_base_dir import isolated_audio_base_dir  # noqa: F401 - autouse fixture
from tests.gateway_container import installed_gateway_dependencies
from tests.runtime_policy_helpers import runtime_read

REVISION = f"sha256:{'a' * 64}"


@pytest.fixture(autouse=True)
def gateway_dependencies():
    """A fresh dependency container on the shared app, which these suites drive without its lifespan."""
    with installed_gateway_dependencies(app) as dependencies:
        yield dependencies


@pytest.fixture
def session_manager(gateway_dependencies):
    """The tenant session manager the shared app's routes see in this test."""
    return gateway_dependencies.session_manager


@pytest.fixture(autouse=True)
def tenant_dependencies():
    context = StudioTenantContext("tenant-test", REVISION)
    app.dependency_overrides[require_studio_tenant_context] = lambda: context
    app.dependency_overrides[require_validated_runtime_configuration] = lambda: (
        ValidatedRuntimeConfiguration(
            context, runtime_read(context.tenant_id, revision=REVISION), "test-correlation"
        )
    )
    yield
    app.dependency_overrides.pop(require_studio_tenant_context, None)
    app.dependency_overrides.pop(require_validated_runtime_configuration, None)
