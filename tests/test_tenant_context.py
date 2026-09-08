from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.api_gateway.auth import require_ssf_user
from services.api_gateway.tenant_context import (
    StudioTenantContext,
    require_studio_tenant_context,
    studio_tenant_context_from_claims,
)


def test_canonical_validated_claim_creates_one_internal_tenant_context() -> None:
    context = studio_tenant_context_from_claims(
        {"sub": "user-1", "studio_tenant_id": "tenant-kassel"}
    )

    assert context == StudioTenantContext(tenant_id="tenant-kassel")


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"studio_tenant_id": ""},
        {"studio_tenant_id": "tenant kassel"},
        {"studio_tenant_id": ["tenant-kassel"]},
        {"tenant_id": "tenant-kassel"},
        {"studio_instance_id": "tenant-kassel"},
        {"studio_tenant_id": "tenant-kassel", "tenant_id": "tenant-berlin"},
    ],
)
def test_missing_malformed_or_legacy_claims_fail_closed(claims: dict[str, Any]) -> None:
    with pytest.raises(HTTPException) as error:
        studio_tenant_context_from_claims(claims)

    assert error.value.status_code == 401


def _tenant_test_client() -> TestClient:
    app = FastAPI()
    app.dependency_overrides[require_ssf_user] = lambda: {
        "sub": "user-1",
        "studio_tenant_id": "tenant-kassel",
    }

    @app.api_route("/tenant-operation", methods=["GET", "POST"])
    async def tenant_operation(
        context: StudioTenantContext = Depends(require_studio_tenant_context),
    ) -> dict[str, str]:
        return {"tenant_id": context.tenant_id}

    return TestClient(app)


def test_dependency_uses_only_the_validated_claim() -> None:
    response = _tenant_test_client().get("/tenant-operation")

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-kassel"}


@pytest.mark.parametrize(
    ("request_kwargs"),
    [
        {"params": {"tenantId": "tenant-berlin"}},
        {"json": {"tenant_id": "tenant-berlin"}},
        {"json": {"payload": [{"tenant_id": "tenant-berlin"}]}},
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
    method = client.post if {"json", "content"}.intersection(request_kwargs) else client.get

    response = method("/tenant-operation", **request_kwargs)

    assert response.status_code == 400
