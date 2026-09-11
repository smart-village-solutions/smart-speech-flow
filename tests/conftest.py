import asyncio
import inspect
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
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


def _test_runtime_configuration() -> RuntimeConfiguration:
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


try:  # pragma: no cover - optional dependency detection
    import pytest_asyncio  # type: ignore  # noqa: F401

    HAS_PYTEST_ASYNCIO = True
except ImportError:  # pragma: no cover
    HAS_PYTEST_ASYNCIO = False


HERMETIC_INTEGRATION_TESTS = {"test_tenant_isolation_matrix.py"}


def pytest_addoption(parser):  # pragma: no cover - exercised via pytest hooks
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that exercise live local services.",
    )
    parser.addoption(
        "--run-load",
        action="store_true",
        default=False,
        help="Run load tests that can put significant pressure on local services.",
    )

    if not HAS_PYTEST_ASYNCIO:
        parser.addini(
            "asyncio_mode",
            "Compatibility shim when pytest-asyncio is not installed",
            default="auto",
        )


def pytest_configure(config):  # pragma: no cover - exercised via pytest hooks
    config.addinivalue_line(
        "markers",
        "asyncio: mark test as requiring asyncio event loop",
    )
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring live local services or broader integration setup",
    )
    config.addinivalue_line(
        "markers",
        "load: mark test as generating significant load against local services",
    )


@pytest.fixture(autouse=True)
def bypass_admin_auth_for_legacy_route_tests(request):
    """Keep pre-auth route tests focused on their domain behavior.

    Authorization behavior is covered explicitly in
    ``services/api_gateway/tests/test_auth.py``.  Existing route, OpenAPI, and
    pipeline tests create sessions through the administrative endpoint and are
    not authentication tests, so supply a test principal for their duration.
    """
    if request.path.name == "test_auth.py":
        yield
        return

    context = StudioTenantContext("tenant-test", REVISION)
    configuration = _test_runtime_configuration()
    app.dependency_overrides[require_ssf_user] = lambda: {
        "sub": "test-admin",
        "studio_tenant_id": context.tenant_id,
        "ssf_authorization_revision": REVISION,
    }
    app.dependency_overrides[require_studio_tenant_context] = lambda: context
    app.dependency_overrides[require_validated_runtime_configuration] = lambda: (
        ValidatedRuntimeConfiguration(context, configuration, "test-correlation")
    )
    yield
    app.dependency_overrides.pop(require_ssf_user, None)
    app.dependency_overrides.pop(require_studio_tenant_context, None)
    app.dependency_overrides.pop(require_validated_runtime_configuration, None)


def pytest_collection_modifyitems(config, items):  # pragma: no cover - exercised via pytest hooks
    run_integration = config.getoption("--run-integration")
    run_load = config.getoption("--run-load")

    skip_integration = pytest.mark.skip(
        reason="integration tests are skipped by default; use --run-integration to include them",
    )
    skip_load = pytest.mark.skip(
        reason="load tests are skipped by default; use --run-load to include them",
    )

    for item in items:
        item_path = Path(str(item.fspath))
        path_parts = item_path.parts

        if "tests" in path_parts and "integration" in path_parts:
            item.add_marker(pytest.mark.integration)
            if not run_integration and item_path.name not in HERMETIC_INTEGRATION_TESTS:
                item.add_marker(skip_integration)

        if "tests" in path_parts and "load" in path_parts:
            item.add_marker(pytest.mark.load)
            if not run_load:
                item.add_marker(skip_load)


if not HAS_PYTEST_ASYNCIO:

    def pytest_pyfunc_call(pyfuncitem):  # pragma: no cover - exercised via pytest hooks
        test_func = pyfuncitem.obj
        if not inspect.iscoroutinefunction(test_func):
            return None

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            signature = inspect.signature(test_func)
            call_kwargs = {}
            for name, value in pyfuncitem.funcargs.items():
                if name not in signature.parameters:
                    continue
                if inspect.isawaitable(value):
                    value = loop.run_until_complete(value)
                    pyfuncitem.funcargs[name] = value
                call_kwargs[name] = value

            coro = test_func(**call_kwargs)
            loop.run_until_complete(coro)

            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
        return True


__all__ = []
