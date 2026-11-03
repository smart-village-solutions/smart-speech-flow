"""The tenant's recovery mode as Studio's recording policy sets it (#680)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.dependencies import get_studio_runtime_flow
from services.api_gateway.studio_v1 import StudioV1ClientError
from services.api_gateway.studio_v2 import StudioContractError
from services.api_gateway.tenant_context import require_studio_tenant_context

URL = "/api/admin/recording/ceremony/studio-mode"
TENANT = "tenant-kassel"
MANAGE = "ssf.configuration.tenant.manage"


class FakeClient:
    def __init__(self, answer) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    async def fetch(self, tenant_id: str, correlation_id: str):
        self.calls.append((tenant_id, correlation_id))
        if isinstance(self.answer, Exception):
            raise self.answer
        recording = None if self.answer is None else SimpleNamespace(recovery_mode=self.answer)
        return SimpleNamespace(policy=SimpleNamespace(recording=recording))


@pytest.fixture
def call():
    def run(answer, permission=MANAGE, *, studio=True):
        client = FakeClient(answer)
        claims = {"sub": "olga", "_ssf_verified_tenant_id": TENANT, "ssf_permissions": [permission]}
        app.dependency_overrides.pop(require_studio_tenant_context, None)
        app.dependency_overrides[require_ssf_user] = lambda: claims
        app.dependency_overrides[get_studio_runtime_flow] = lambda: (
            SimpleNamespace(client=client) if studio else None
        )
        return TestClient(app).get(URL), client

    yield run
    app.dependency_overrides.pop(require_ssf_user, None)
    app.dependency_overrides.pop(get_studio_runtime_flow, None)


@pytest.mark.parametrize("mode", ["standard", "enhanced"])
def test_an_administrator_reads_the_mode_studio_sets(call, mode):
    response, client = call(mode)
    assert (response.status_code, response.json()) == (200, {"recovery_mode": mode})
    assert [tenant for tenant, _ in client.calls] == [TENANT]


def test_without_a_recording_policy_there_is_no_mode(call):
    response, _ = call(None)
    assert response.json() == {"recovery_mode": None}


def test_without_studio_there_is_no_mode(call):
    response, client = call("enhanced", studio=False)
    assert response.json() == {"recovery_mode": None}
    assert client.calls == []


@pytest.mark.parametrize(
    "error",
    [StudioV1ClientError("studio_runtime_network_error", retryable=True), StudioContractError("x")],
)
def test_a_failed_read_says_studio_is_unavailable(call, error):
    response, _ = call(error)
    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "STUDIO_UNAVAILABLE"


def test_only_a_tenant_administrator_may_read_it(call):
    response, client = call("enhanced", "ssf.recording.recovery.custodian")
    assert response.status_code == 403
    assert client.calls == []
