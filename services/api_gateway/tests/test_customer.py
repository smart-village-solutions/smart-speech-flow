import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.api_gateway.app import app
from services.api_gateway.auth import require_ssf_user
from services.api_gateway.session_manager import session_manager

client = TestClient(app)


class TestCustomerRoutes:
    def setup_method(self):
        """Reset session manager before each test"""
        app.dependency_overrides[require_ssf_user] = lambda: {"sub": "test-admin"}
        session_manager.reset(clear_persistence=True)

    def teardown_method(self):
        app.dependency_overrides.pop(require_ssf_user, None)

    def test_activate_session_success(self):
        """Test successful session activation"""
        # Create a session first (simulating admin)
        response = client.post("/api/admin/session/create")
        assert response.status_code == 201
        session_data = response.json()
        session_id = session_data["session_id"]

        # Activate session as customer
        activate_payload = {"session_id": session_id, "customer_language": "en"}

        response = client.post("/api/customer/session/activate", json=activate_payload)
        assert response.status_code == 200

        data = response.json()
        assert data["session_id"] == session_id
        assert data["status"] == "active"
        assert data["customer_language"] == "en"
        assert "erfolgreich aktiviert" in data["message"]
        assert "timestamp" in data

    def test_activate_session_not_found(self):
        """Test activation with non-existent session"""
        activate_payload = {"session_id": "NONEXISTENT", "customer_language": "en"}

        response = client.post("/api/customer/session/activate", json=activate_payload)
        assert response.status_code == 404
        assert response.json() == {"detail": "Session not found"}

    def test_activate_session_idempotent(self):
        """Test that activating an already active session is idempotent"""
        # Create and activate session
        response = client.post("/api/admin/session/create")
        session_id = response.json()["session_id"]

        activate_payload = {"session_id": session_id, "customer_language": "de"}

        # First activation
        response1 = client.post("/api/customer/session/activate", json=activate_payload)
        assert response1.status_code == 200
        assert response1.json()["status"] == "active"

        # Second activation (idempotent)
        response2 = client.post("/api/customer/session/activate", json=activate_payload)
        assert response2.status_code == 200
        assert response2.json()["status"] == "active"
        assert "bereits aktiv" in response2.json()["message"]

    def test_activate_terminated_session(self):
        """Test that terminated sessions cannot be activated"""
        # Create session
        response = client.post("/api/admin/session/create")
        session_id = response.json()["session_id"]

        # Terminate session
        response = client.delete(f"/api/admin/session/{session_id}/terminate")
        assert response.status_code == 200

        # Try to activate terminated session
        activate_payload = {"session_id": session_id, "customer_language": "en"}

        response = client.post("/api/customer/session/activate", json=activate_payload)
        assert response.status_code == 404
        assert response.json() == {"detail": "Session not found"}

    def test_get_customer_session_status(self):
        """Test customer session status endpoint"""
        # Create session
        response = client.post("/api/admin/session/create")
        session_id = response.json()["session_id"]

        # Get status (should be pending)
        response = client.get(f"/api/customer/session/{session_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["session_id"] == session_id
        assert data["status"] == "pending"
        assert data["is_active"] is False
        assert data["can_send_messages"] is False

        # Activate session
        activate_payload = {"session_id": session_id, "customer_language": "ar"}
        client.post("/api/customer/session/activate", json=activate_payload)

        # Get status again (should be active)
        response = client.get(f"/api/customer/session/{session_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "active"
        assert data["customer_language"] == "ar"
        assert data["is_active"] is True
        assert data["can_send_messages"] is True

    def test_customer_session_status_hides_admin_termination(self):
        """An inactive join capability has the same response as an unknown one."""
        response = client.post("/api/admin/session/create")
        session_id = response.json()["session_id"]

        activate_payload = {"session_id": session_id, "customer_language": "ru"}
        activate_response = client.post(
            "/api/customer/session/activate", json=activate_payload
        )
        assert activate_response.status_code == 200

        terminate_response = client.delete(f"/api/admin/session/{session_id}/terminate")
        assert terminate_response.status_code == 200

        status_response = client.get(f"/api/customer/session/{session_id}")
        assert status_response.status_code == 404
        assert status_response.json() == {"detail": "Session not found"}

    def test_customer_supported_languages(self):
        """Test customer languages endpoint"""
        response = client.get("/api/customer/languages/supported")
        assert response.status_code == 200

        data = response.json()
        assert "languages" in data
        assert isinstance(data["languages"], dict)
        assert "de" in data["languages"]
        assert "en" in data["languages"]

    def test_activate_session_with_unsupported_language_warning(self):
        """Test activation with unsupported language (should warn but not fail)"""
        # Create session
        response = client.post("/api/admin/session/create")
        session_id = response.json()["session_id"]

        # Activate with unsupported language
        activate_payload = {
            "session_id": session_id,
            "customer_language": "xyz",  # Not in supported list
        }

        response = client.post("/api/customer/session/activate", json=activate_payload)
        # Should still succeed (TTS service will handle validation)
        assert response.status_code == 200
        assert response.json()["customer_language"] == "xyz"

    def test_generic_message_route_is_not_a_tenant_boundary(self):
        """The former role-spoofable route cannot address tenant sessions."""
        # Create session
        response = client.post("/api/admin/session/create")
        session_id = response.json()["session_id"]

        # Try to send message before activation (should fail)
        message_payload = {
            "text": "Hello",
            "source_lang": "en",
            "target_lang": "de",
            "client_type": "customer",
        }

        response = client.post(
            f"/api/session/{session_id}/message",
            json=message_payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 404
