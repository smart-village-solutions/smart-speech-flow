"""Passphrase-file policy is optional and bound to recording staff's verified tenant."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.dependencies import get_studio_runtime_flow
from services.api_gateway.studio_v1 import StudioV1ClientError
from services.api_gateway.studio_v2 import StudioContractError
from services.api_gateway.tenant_context import require_studio_tenant_context

URL = "/api/admin/recording/key-policy"
TENANT = "tenant-kassel"


@pytest.fixture
def call():
    calls = []
    app.dependency_overrides.pop(require_studio_tenant_context, None)

    def run(value=None, *, permission="ssf.recording.review", studio=True, suffix=""):
        async def fetch(tenant_id, correlation_id):
            calls.append(tenant_id)
            if isinstance(value, Exception):
                raise value
            recording = None if value is None else SimpleNamespace(passphrase_file_enabled=value)
            return SimpleNamespace(policy=SimpleNamespace(recording=recording))

        app.dependency_overrides[require_ssf_user] = lambda: {
            "sub": "alice",
            "_ssf_verified_tenant_id": TENANT,
            "ssf_permissions": [permission],
        }
        app.dependency_overrides[get_studio_runtime_flow] = lambda: (
            SimpleNamespace(client=SimpleNamespace(fetch=fetch)) if studio else None
        )
        return TestClient(app).get(URL + suffix)

    yield run, calls
    app.dependency_overrides.pop(require_ssf_user, None)
    app.dependency_overrides.pop(get_studio_runtime_flow, None)


@pytest.mark.parametrize("value", [True, False, None])
def test_staff_reads_effective_policy(call, value):
    run, calls = call
    response = run(value)
    assert response.status_code == 200
    assert response.json() == {"passphrase_file_enabled": value is True}
    assert calls == [TENANT]


@pytest.mark.parametrize(
    "value",
    [
        StudioV1ClientError("studio_runtime_network_error", retryable=True),
        StudioContractError("invalid"),
    ],
)
def test_unavailable_policy_disables_file_workflow(call, value):
    run, _ = call
    assert run(value).json() == {"passphrase_file_enabled": False}


def test_without_studio_files_are_disabled(call):
    run, calls = call
    assert run(True, studio=False).json() == {"passphrase_file_enabled": False}
    assert calls == []


def test_non_recording_staff_is_refused(call):
    run, calls = call
    assert run(True, permission="ssf.configuration.tenant.manage").status_code == 403
    assert calls == []


def test_caller_cannot_choose_another_tenant(call):
    run, calls = call
    assert run(True, suffix="?tenantId=other").status_code == 400
    assert calls == []


def test_anonymous_is_refused():
    app.dependency_overrides.pop(require_ssf_user, None)
    app.dependency_overrides.pop(require_studio_tenant_context, None)
    assert TestClient(app).get(URL).status_code == 401
