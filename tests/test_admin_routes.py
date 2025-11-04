# tests/test_admin_routes.py
"""
Unit Tests für Admin-Routes mit parallelen Sessions
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

# Import the app and modules first
from services.api_gateway.app import app
from services.api_gateway.session_manager import SessionStatus

client = TestClient(app)


@pytest.fixture
def admin_session_manager():
    """Mock SessionManager für Tests"""
    manager = MagicMock()
    manager.create_admin_session = AsyncMock()
    manager.get_session = MagicMock()
    manager.get_active_session = MagicMock()
    manager.get_active_sessions = MagicMock(return_value=[])
    manager.get_session_history = MagicMock()
    manager.terminate_session = AsyncMock()
    return manager


@pytest.fixture
def mock_session():
    """Mock Session-Objekt"""
    session = MagicMock()
    session.id = "TEST123"
    session.status = SessionStatus.PENDING
    session.customer_language = None
    session.admin_connected = True
    session.customer_connected = False
    session.messages = []
    session.created_at.isoformat.return_value = "2025-09-28T10:30:00"
    session.terminated_at = None
    session.termination_reason = None
    return session


class TestAdminSessionCreation:
    """Tests für Admin-Session-Erstellung"""

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_create_admin_session_success(self, admin_session_manager, mock_session):
        """Test: Erfolgreiche Admin-Session-Erstellung"""
        # Mock setup
        admin_session_manager.create_admin_session = AsyncMock(return_value="TEST123")
        admin_session_manager.get_session.return_value = mock_session

        # API Call
        response = client.post("/api/admin/session/create")

        # Assertions
        assert response.status_code == 201
        data = response.json()

        assert data["session_id"] == "TEST123"
        assert data["status"] == "pending"
        assert "client_url" in data
        # Test accepts both development and production URLs
        assert ("localhost:5174/join/TEST123" in data["client_url"] or
                "translate.smart-village.solutions/join/TEST123" in data["client_url"])
        assert "erfolgreich erstellt" in data["message"]
        assert "Session-ID" in data["message"]

        # Verify manager was called
        admin_session_manager.create_admin_session.assert_called_once()
        admin_session_manager.get_session.assert_called_once_with("TEST123")

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_create_admin_session_failure(self, admin_session_manager):
        """Test: Session-Erstellung schlägt fehl"""
        # Mock setup - Session creation fails
        admin_session_manager.create_admin_session = AsyncMock(side_effect=Exception("Database error"))

        # API Call
        response = client.post("/api/admin/session/create")

        # Assertions
        assert response.status_code == 500
        data = response.json()
        assert "Session-Erstellung fehlgeschlagen" in data["detail"]

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_create_admin_session_no_session_returned(self, admin_session_manager):
        """Test: Session wird erstellt aber nicht gefunden"""
        # Mock setup
        admin_session_manager.create_admin_session = AsyncMock(return_value="TEST123")
        admin_session_manager.get_session.return_value = None  # Session not found

        # API Call
        response = client.post("/api/admin/session/create")

        # Assertions
        assert response.status_code == 500
        data = response.json()
        assert "Fehler bei Session-Erstellung" in data["detail"]


class TestCurrentSessionRetrieval:
    """Tests für aktuelle Session-Abfrage"""

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_get_current_session_success(self, admin_session_manager, mock_session):
        """Test: Erfolgreiche Abfrage der aktuellen Session"""
        # Mock setup
        admin_session_manager.get_active_session.return_value = {"id": "TEST123"}
        admin_session_manager.get_active_sessions.return_value = []
        admin_session_manager.get_session.return_value = mock_session

        # API Call
        response = client.get("/api/admin/session/current")

        # Assertions
        assert response.status_code == 200
        data = response.json()

        assert data["session_id"] == "TEST123"
        assert data["status"] == "pending"
        assert data["admin_connected"] is True
        assert data["customer_connected"] is False
        assert data["message_count"] == 0

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_get_current_session_with_specific_id(self, admin_session_manager, mock_session):
        """Test: Abfrage einer spezifischen Session via Query-Parameter"""
        admin_session_manager.get_active_session.return_value = {"id": "TEST123"}
        admin_session_manager.get_session.return_value = mock_session

        response = client.get("/api/admin/session/current", params={"session_id": "TEST123"})

        assert response.status_code == 200
        admin_session_manager.get_active_session.assert_called_once_with(session_id="TEST123")

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_get_current_session_not_found(self, admin_session_manager):
        """Test: Keine aktive Session gefunden"""
        # Mock setup
        admin_session_manager.get_active_session.return_value = None

        # API Call
        response = client.get("/api/admin/session/current")

        # Assertions
        assert response.status_code == 404
        data = response.json()
        assert "Keine aktive Admin-Session gefunden" in data["detail"]


class TestSessionTermination:
    """Tests für Session-Beendigung"""

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_terminate_session_success(self, admin_session_manager, mock_session):
        """Test: Erfolgreiche Session-Beendigung"""
        # Mock setup
        admin_session_manager.get_session.return_value = mock_session
        admin_session_manager.terminate_session = AsyncMock()

        # API Call
        response = client.delete("/api/admin/session/TEST123/terminate")

        # Assertions
        assert response.status_code == 200
        data = response.json()

        assert data["session_id"] == "TEST123"
        assert data["status"] == "terminated"
        assert "erfolgreich beendet" in data["message"]

        # Verify termination was called
        admin_session_manager.terminate_session.assert_called_once_with(
            "TEST123", "manual_admin_termination"
        )

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_terminate_session_not_found(self, admin_session_manager):
        """Test: Session nicht gefunden bei Termination"""
        # Mock setup
        admin_session_manager.get_session.return_value = None

        # API Call
        response = client.delete("/api/admin/session/INVALID/terminate")

        # Assertions
        assert response.status_code == 404
        data = response.json()
        assert "Session INVALID nicht gefunden" in data["detail"]

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_terminate_already_terminated_session(self, admin_session_manager, mock_session):
        """Test: Session ist bereits beendet"""
        # Mock setup
        mock_session.status = SessionStatus.TERMINATED
        admin_session_manager.get_session.return_value = mock_session

        # API Call
        response = client.delete("/api/admin/session/TEST123/terminate")

        # Assertions
        assert response.status_code == 200
        data = response.json()

        assert data["session_id"] == "TEST123"
        assert data["status"] == "already_terminated"
        assert "bereits beendet" in data["message"]


class TestSessionHistory:
    """Tests für Session-Historie"""

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_get_session_history_success(self, admin_session_manager):
        """Test: Erfolgreiche Session-Historie-Abfrage"""
        # Mock setup
        mock_history = [
            {"id": "SESSION1", "status": "terminated", "created_at": "2025-09-28T10:00:00"},
            {"id": "SESSION2", "status": "terminated", "created_at": "2025-09-28T09:00:00"}
        ]
        mock_active = [{"id": "SESSION3", "status": "active"}]
        admin_session_manager.get_session_history.return_value = mock_history
        admin_session_manager.get_active_sessions.return_value = mock_active

        # API Call
        response = client.get("/api/admin/session/history")

        # Assertions
        assert response.status_code == 200
        data = response.json()

        assert len(data["sessions"]) == 2
        assert data["total_count"] == 2
        assert len(data["active_sessions"]) == 1
        assert data["active_sessions"][0]["id"] == "SESSION3"

        # Verify correct limit was used
        admin_session_manager.get_session_history.assert_called_once_with(limit=10)

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_get_session_history_with_custom_limit(self, admin_session_manager):
        """Test: Session-Historie mit benutzerdefiniertem Limit"""
        # Mock setup
        admin_session_manager.get_session_history.return_value = []
        admin_session_manager.get_active_sessions.return_value = []

        # API Call mit Custom Limit
        response = client.get("/api/admin/session/history?limit=5")

        # Assertions
        assert response.status_code == 200
        admin_session_manager.get_session_history.assert_called_once_with(limit=5)


class TestSessionStatus:
    """Tests für Session-Status-Abfrage"""

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_get_session_status_success(self, admin_session_manager, mock_session):
        """Test: Erfolgreiche Session-Status-Abfrage"""
        # Mock setup
        admin_session_manager.get_session.return_value = mock_session

        # API Call
        response = client.get("/api/admin/session/TEST123/status")

        # Assertions
        assert response.status_code == 200
        data = response.json()

        assert data["session_id"] == "TEST123"
        assert data["status"] == "pending"
        assert data["admin_connected"] is True
        assert data["customer_connected"] is False

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_get_session_status_not_found(self, admin_session_manager):
        """Test: Session nicht gefunden bei Status-Abfrage"""
        # Mock setup
        admin_session_manager.get_session.return_value = None

        # API Call
        response = client.get("/api/admin/session/INVALID/status")

        # Assertions
        assert response.status_code == 404
        data = response.json()
        assert "Session INVALID nicht gefunden" in data["detail"]


class TestErrorHandling:
    """Tests für Error-Handling"""

    @patch('services.api_gateway.routes.admin.session_manager')
    def test_unexpected_error_handling(self, admin_session_manager):
        """Test: Behandlung unerwarteter Fehler"""
        # Mock setup - Unexpected error
        admin_session_manager.get_active_session.side_effect = RuntimeError("Unexpected error")

        # API Call
        response = client.get("/api/admin/session/current")

        # Assertions
        assert response.status_code == 500
        data = response.json()
        assert "Fehler beim Abrufen der Session" in data["detail"]


class TestClientURLGeneration:
    """Tests für Client-URL-Generierung"""

    @patch('services.api_gateway.routes.admin.session_manager')
    @patch('services.api_gateway.routes.admin.get_client_base_url')
    def test_client_url_generation(self, mock_get_base_url, admin_session_manager, mock_session):
        """Test: Korrekte Client-URL-Generierung"""
        # Mock setup
        mock_get_base_url.return_value = "https://client.example.com"
        admin_session_manager.create_admin_session = AsyncMock(return_value="ABC123")
        admin_session_manager.get_session.return_value = mock_session

        # API Call
        response = client.post("/api/admin/session/create")

        # Assertions
        assert response.status_code == 201
        data = response.json()
        assert data["client_url"] == "https://client.example.com/join/ABC123"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
