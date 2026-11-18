"""Approved v2 app does not expose the retired threshold-recovery workflow."""

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import create_app


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/admin/recording/ceremony"),
        ("GET", "/api/admin/recording/ceremony/studio-mode"),
        ("POST", "/api/admin/recording/ceremony"),
        ("GET", "/api/admin/recording/recovery/employees"),
        ("GET", "/api/admin/recording/recovery/own/candidates"),
        ("GET", "/api/admin/recording/recovery/approvals"),
    ],
)
def test_retired_threshold_routes_have_no_public_handler(method, path):
    response = TestClient(create_app()).request(method, path)
    assert response.status_code == 404
