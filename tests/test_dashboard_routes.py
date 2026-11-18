"""Dashboard routes admit ordinary staff and restrict finished-review metadata."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api_gateway.auth import require_ssf_user
from services.api_gateway.dashboard import Dashboard, DashboardCursor
from services.api_gateway.routes.dashboard import get_dashboard, get_dashboard_records, router
from services.api_gateway.session_pseudonym import SessionPseudonymizer
from tests.test_dashboard_overview import Sessions, session


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_ssf_user] = lambda: {
        "sub": "alice",
        "_ssf_verified_tenant_id": "tenant-a",
        "ssf_permissions": [],
    }
    app.dependency_overrides[get_dashboard] = lambda: Dashboard(
        Sessions([session()]), None, SessionPseudonymizer(key=b"test"), DashboardCursor(bytes(32))
    )
    return app, TestClient(app)


def test_ordinary_staff_without_recording_permission_can_list(client):
    _, call = client
    assert call.get("/api/admin/dashboard/conversations").status_code == 200


def test_invalid_cursor_is_value_free(client):
    _, call = client
    response = call.get("/api/admin/dashboard/conversations?cursor=PRIVATE_MARKER")
    assert response.status_code == 400
    assert "PRIVATE_MARKER" not in response.text


def test_invalid_page_size_is_rejected(client):
    _, call = client
    assert call.get("/api/admin/dashboard/conversations?limit=101").status_code == 422


class Results:
    def __init__(self):
        self.calls = []

    async def completed_result(self, tenant, sub, verification_id):
        self.calls.append((tenant, sub, verification_id))
        return {
            "verification_id": verification_id,
            "status": "approved",
            "outcome": "approved",
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "requested_by_name": None,
        }


def test_completed_result_requires_review_permission(client):
    app, call = client
    results = Results()
    app.dependency_overrides[get_dashboard_records] = lambda: results
    path = "/api/admin/recording/verifications/00000000-0000-0000-0000-000000000001/result"
    assert call.get(path).status_code == 403
    assert not results.calls
    app.dependency_overrides[require_ssf_user] = lambda: {
        "sub": "alice",
        "_ssf_verified_tenant_id": "tenant-a",
        "ssf_permissions": ["ssf.recording.review"],
    }
    answer = call.get(path)
    assert answer.status_code == 200
    assert set(answer.json()) == {
        "verification_id",
        "status",
        "outcome",
        "requested_at",
        "decided_at",
        "requested_by_name",
    }
    assert results.calls[0][:2] == ("tenant-a", "alice")
