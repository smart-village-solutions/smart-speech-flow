import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.tenant_session import TenantSessionKey

client = TestClient(app)


class TestAdminRoutes:
    @pytest.fixture(autouse=True)
    def reset_sessions(self, session_manager, monkeypatch):
        """Reset session manager before each test."""
        monkeypatch.setitem(
            app.dependency_overrides, require_ssf_user, lambda: {"sub": "test-admin"}
        )
        monkeypatch.delenv("SSF_ALLOW_PARALLEL_SESSIONS", raising=False)
        monkeypatch.setattr(session_manager, "allow_parallel_sessions", False)
        session_manager.reset(clear_persistence=True)
        yield
        session_manager.reset(clear_persistence=True)

    def test_create_admin_session_terminates_previous_active_session_by_default(
        self, session_manager
    ):
        first_response = client.post("/api/admin/session/create")
        assert first_response.status_code == 201
        first_session_id = first_response.json()["session_id"]

        activate_payload = {"session_id": first_session_id, "customer_language": "en"}
        activate_response = client.post(
            "/api/customer/session/activate",
            json=activate_payload,
        )
        assert activate_response.status_code == 200

        second_response = client.post("/api/admin/session/create")
        assert second_response.status_code == 201
        second_session_id = second_response.json()["session_id"]

        assert second_session_id != first_session_id

        first_session = session_manager.get_session(
            TenantSessionKey("tenant-test", first_session_id)
        )
        second_session = session_manager.get_session(
            TenantSessionKey("tenant-test", second_session_id)
        )

        assert first_session is not None
        assert second_session is not None
        assert first_session.status.value == "terminated"
        assert first_session.termination_reason == "new_session_created"
        assert second_session.status.value == "pending"

    def test_get_current_session_requires_explicit_id_when_parallel_sessions_enabled(
        self,
        session_manager,
        monkeypatch,
    ):
        monkeypatch.setattr(session_manager, "allow_parallel_sessions", True)

        first_response = client.post("/api/admin/session/create")
        second_response = client.post("/api/admin/session/create")

        assert first_response.status_code == 201
        assert second_response.status_code == 201

        current_response = client.get("/api/admin/session/current")
        assert current_response.status_code == 409
        assert current_response.json()["detail"] == (
            "Multiple active sessions require an explicit session_id"
        )

        second_session_id = second_response.json()["session_id"]
        specific_response = client.get(
            "/api/admin/session/current", params={"session_id": second_session_id}
        )
        assert specific_response.status_code == 200
        assert specific_response.json()["session_id"] == second_session_id
