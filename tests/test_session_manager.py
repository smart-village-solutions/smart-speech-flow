# tests/test_session_manager.py
"""
Unit Tests für Single-Session-Policy Implementation
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from services.api_gateway.session_manager import (
    SessionManager,
    Session,
    SessionStatus,
    ClientType
)


@pytest.fixture
def session_manager():
    """Fresh SessionManager instance für jeden Test"""
    return SessionManager()


@pytest.fixture
def mock_websocket():
    """Mock WebSocket für Tests"""
    websocket = MagicMock()
    websocket.client_state.DISCONNECTED = False
    websocket.send_json = AsyncMock()
    websocket.close = AsyncMock()
    return websocket


class TestSingleSessionPolicy:
    """Tests für Single-Session-Policy Logic"""

    @pytest.mark.asyncio
    async def test_create_admin_session_creates_new_session(self, session_manager):
        """Test: Neue Admin-Session wird erfolgreich erstellt"""
        session_id = await session_manager.create_admin_session()

        assert session_id is not None
        assert len(session_id) == 8  # Kurze UUID
        assert session_manager.active_admin_session == session_id

        session = session_manager.get_session(session_id)
        assert session.status == SessionStatus.PENDING
        assert session.customer_language is None
        assert session.admin_language == "de"

    @pytest.mark.asyncio
    async def test_single_session_policy_terminates_existing(self, session_manager):
        """Test: Neue Session beendet automatisch bestehende Sessions"""
        # Erste Session erstellen
        first_session_id = await session_manager.create_admin_session()
        first_session = session_manager.get_session(first_session_id)
        first_session.status = SessionStatus.ACTIVE  # Simuliere aktive Session

        # Zweite Session erstellen (soll erste beenden)
        second_session_id = await session_manager.create_admin_session()

        # Erste Session soll beendet sein
        first_session = session_manager.get_session(first_session_id)
        assert first_session.status == SessionStatus.TERMINATED
        assert first_session.termination_reason == "new_session_created"
        assert first_session.terminated_at is not None

        # Zweite Session soll aktiv sein
        assert session_manager.active_admin_session == second_session_id
        second_session = session_manager.get_session(second_session_id)
        assert second_session.status == SessionStatus.PENDING

    @pytest.mark.asyncio
    async def test_terminate_all_active_sessions(self, session_manager):
        """Test: Alle aktiven Sessions werden korrekt beendet"""
        # Mehrere Sessions erstellen und aktivieren
        session_ids = []
        for i in range(3):
            session_id = await session_manager.create_admin_session()
            session = session_manager.get_session(session_id)
            session.status = SessionStatus.ACTIVE
            session_ids.append(session_id)

        # Alle Sessions beenden
        await session_manager.terminate_all_active_sessions("test_cleanup")

        # Alle Sessions sollen beendet sein
        for session_id in session_ids:
            session = session_manager.get_session(session_id)
            assert session.status == SessionStatus.TERMINATED
            assert session.termination_reason == "test_cleanup"

        assert session_manager.active_admin_session is None

    @pytest.mark.asyncio
    async def test_session_activation_flow(self, session_manager):
        """Test: Session-Aktivierung durch Customer-Join"""
        # Admin-Session erstellen
        session_id = await session_manager.create_admin_session()

        # Customer aktiviert Session
        await session_manager.activate_session(session_id, "en")

        session = session_manager.get_session(session_id)
        assert session.status == SessionStatus.ACTIVE
        assert session.customer_language == "en"
        assert session.customer_connected is True

    @pytest.mark.asyncio
    async def test_websocket_termination_notifications(self, session_manager, mock_websocket):
        """Test: WebSocket-Benachrichtigungen bei Session-Termination"""
        # Session mit WebSocket-Verbindung erstellen
        session_id = await session_manager.create_admin_session()
        await session_manager.add_websocket_connection(
            session_id, ClientType.ADMIN, mock_websocket
        )

        # Session beenden
        await session_manager.terminate_session(session_id, "test_termination")

        # WebSocket-Benachrichtigung prüfen
        mock_websocket.send_json.assert_called_once()
        call_args = mock_websocket.send_json.call_args[0][0]

        assert call_args["type"] == "session_terminated"
        assert call_args["session_id"] == session_id
        assert call_args["reason"] == "test_termination"
        assert "Die Session wurde" in call_args["message"]

        # WebSocket wurde geschlossen
        mock_websocket.close.assert_called_once()


class TestSessionStateManagement:
    """Tests für Session-State-Machine"""

    @pytest.mark.asyncio
    async def test_session_state_transitions(self, session_manager):
        """Test: Korrekte Session-State-Übergänge"""
        # PENDING → ACTIVE
        session_id = await session_manager.create_admin_session()
        session = session_manager.get_session(session_id)
        assert session.status == SessionStatus.PENDING

        await session_manager.activate_session(session_id, "es")
        assert session.status == SessionStatus.ACTIVE

        # ACTIVE → TERMINATED
        await session_manager.terminate_session(session_id)
        assert session.status == SessionStatus.TERMINATED

    def test_get_active_session_single_policy(self, session_manager):
        """Test: get_active_session gibt nur eine Session zurück"""
        # Ohne aktive Session
        assert session_manager.get_active_session() is None

        # Mit aktiver Session
        asyncio.run(self._create_and_activate_session(session_manager))
        active_session = session_manager.get_active_session()

        assert active_session is not None
        assert active_session["status"] == "active"

    async def _create_and_activate_session(self, session_manager):
        """Helper: Session erstellen und aktivieren"""
        session_id = await session_manager.create_admin_session()
        await session_manager.activate_session(session_id, "fr")


class TestWebSocketManagement:
    """Tests für WebSocket-Connection-Management"""

    @pytest.mark.asyncio
    async def test_websocket_connection_lifecycle(self, session_manager, mock_websocket):
        """Test: WebSocket-Verbindungen werden korrekt verwaltet"""
        session_id = await session_manager.create_admin_session()

        # WebSocket hinzufügen
        await session_manager.add_websocket_connection(
            session_id, ClientType.ADMIN, mock_websocket
        )

        # Verbindung prüfen
        websocket = session_manager.get_websocket_connection(session_id, ClientType.ADMIN)
        assert websocket == mock_websocket

        session = session_manager.get_session(session_id)
        assert session.admin_connected is True

        # WebSocket entfernen
        await session_manager.remove_websocket_connection(session_id, ClientType.ADMIN)

        websocket = session_manager.get_websocket_connection(session_id, ClientType.ADMIN)
        assert websocket is None
        assert session.admin_connected is False

    @pytest.mark.asyncio
    async def test_websocket_cleanup_on_termination(self, session_manager, mock_websocket):
        """Test: WebSocket-Cleanup bei Session-Termination"""
        session_id = await session_manager.create_admin_session()
        await session_manager.add_websocket_connection(
            session_id, ClientType.ADMIN, mock_websocket
        )

        # Session beenden
        await session_manager.terminate_session(session_id)

        # WebSocket-Verbindung soll entfernt sein
        assert session_id not in session_manager.websocket_connections


class TestMemoryLeakPrevention:
    """Tests für Memory-Leak-Prevention"""

    @pytest.mark.asyncio
    async def test_no_memory_leaks_on_session_switch(self, session_manager):
        """Test: Keine Memory-Leaks bei häufigen Session-Wechseln"""
        initial_session_count = len(session_manager.sessions)

        # Viele Session-Wechsel simulieren
        for i in range(10):
            session_id = await session_manager.create_admin_session()
            # Simuliere aktive Nutzung
            session = session_manager.get_session(session_id)
            session.messages.append(MagicMock())

        # Nur eine Session sollte aktiv sein, aber alle im Speicher für History
        active_sessions = [
            s for s in session_manager.sessions.values()
            if s.status != SessionStatus.TERMINATED
        ]
        assert len(active_sessions) == 1

        # Beendete Sessions bleiben für History im Speicher
        terminated_sessions = [
            s for s in session_manager.sessions.values()
            if s.status == SessionStatus.TERMINATED
        ]
        assert len(terminated_sessions) == 9

    def test_session_history_limiting(self, session_manager):
        """Test: Session-History wird auf sinnvolle Anzahl begrenzt"""
        # Viele beendete Sessions simulieren
        for i in range(15):
            session = Session(
                id=f"test-{i}",
                status=SessionStatus.TERMINATED,
                terminated_at=datetime.now()
            )
            session_manager.sessions[session.id] = session

        # History soll begrenzt sein
        history = session_manager.get_session_history(limit=10)
        assert len(history) == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])