import logging
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.api_gateway.auth import require_ssf_user
from services.api_gateway.tenant_context import (
    StudioTenantContext,
    require_studio_tenant_context,
    studio_tenant_context_from_principal,
)
from tests.auth_helpers import REVISION, principal

AUTH_LOGGER = "services.api_gateway.auth_rejections"


def test_principal_creates_one_internal_tenant_context() -> None:
    context = studio_tenant_context_from_principal(principal("tenant-kassel", "user-1"))

    assert context == StudioTenantContext(
        tenant_id="tenant-kassel", authorization_revision=REVISION
    )


def test_a_legacy_tenant_claim_fails_closed() -> None:
    legacy = principal("tenant-kassel", carries_legacy_tenant_claim=True)
    with pytest.raises(HTTPException) as error:
        studio_tenant_context_from_principal(legacy)

    assert error.value.status_code == 401


def _tenant_test_client(*, carries_legacy_tenant_claim: bool = False) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[require_ssf_user] = lambda: principal(
        "tenant-kassel", "user-1", carries_legacy_tenant_claim=carries_legacy_tenant_claim
    )

    @app.api_route("/tenant-operation", methods=["GET", "POST"])
    @app.get("/tenant-operation/{studio_tenant_id}")
    async def tenant_operation(
        context: StudioTenantContext = Depends(require_studio_tenant_context),
    ) -> dict[str, str]:
        return {"tenant_id": context.tenant_id}

    return TestClient(app)


def test_dependency_uses_only_the_authenticated_principal() -> None:
    response = _tenant_test_client().get("/tenant-operation")

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-kassel"}


def test_dependency_rejects_and_logs_a_legacy_tenant_claim(caplog) -> None:
    caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)

    response = _tenant_test_client(carries_legacy_tenant_claim=True).get(
        "/tenant-operation", headers={"X-Correlation-Id": "corr-legacy"}
    )

    assert response.status_code == 401
    assert [
        (record.reason, record.correlation_id)
        for record in caplog.records
        if record.name == AUTH_LOGGER
    ] == [("legacy_tenant_claim", "corr-legacy")]


def test_dependency_rejects_path_tenant_selectors() -> None:
    response = _tenant_test_client().get("/tenant-operation/tenant-berlin")

    assert response.status_code == 400


@pytest.mark.parametrize(
    ("request_kwargs"),
    [
        {"params": {"tenantId": "tenant-berlin"}},
        {"params": {"TENANT_ID": "tenant-berlin"}},
        {"json": {"tenant_id": "tenant-berlin"}},
        {"json": {"payload": [{"tenant_id": "tenant-berlin"}]}},
        {"json": {"payload": [[{"TenantId": "tenant-berlin"}]]}},
        {
            "content": '{"payload":{"tenant_id":"tenant-berlin"}}',
            "headers": {"Content-Type": "application/vnd.api+json"},
        },
        {"headers": {"X-Studio-Tenant-Id": "tenant-berlin"}},
        {"cookies": {"studio_tenant_id": "tenant-berlin"}},
    ],
)
def test_dependency_rejects_browser_controlled_tenant_selectors(
    request_kwargs: dict[str, Any],
) -> None:
    client = _tenant_test_client()
    method = (
        client.post if {"json", "content"}.intersection(request_kwargs) else client.get
    )

    response = method("/tenant-operation", **request_kwargs)

    assert response.status_code == 400
