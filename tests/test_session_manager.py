# tests/test_session_manager.py
"""
Unit Tests für Session-Management mit parallelen Sessions
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


class TestSessionCreationAndLifecycle:
    """Tests für Session-Erstellung und parallele Nutzung"""

    @pytest.mark.asyncio
    async def test_create_admin_session_creates_new_session(self, session_manager):
        """Test: Neue Admin-Session wird erfolgreich erstellt"""
        session_id = await session_manager.create_admin_session()

        assert session_id is not None
        assert len(session_id) == 8  # Kurze UUID
        assert session_id in session_manager.active_admin_sessions
        assert len(session_manager.active_admin_sessions) == 1

        session = session_manager.get_session(session_id)
        assert session.status == SessionStatus.PENDING
        assert session.customer_language is None
        assert session.admin_language == "de"

    @pytest.mark.asyncio
    async def test_multiple_sessions_remain_active(self, session_manager):
        """Test: Mehrere Sessions können parallel bestehen"""
        first_session_id = await session_manager.create_admin_session()
        second_session_id = await session_manager.create_admin_session()

        assert session_manager.active_admin_sessions == {first_session_id, second_session_id}

        first_session = session_manager.get_session(first_session_id)
        second_session = session_manager.get_session(second_session_id)

        assert first_session.status == SessionStatus.PENDING
        assert second_session.status == SessionStatus.PENDING
        assert first_session.termination_reason is None

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

        assert session_manager.active_admin_sessions == set()

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

    def test_get_active_session_lookup(self, session_manager):
        """Test: get_active_session liefert jüngste oder spezifische Session"""
        # Ohne aktive Session
        assert session_manager.get_active_session() is None

        session_a = asyncio.run(self._create_and_activate_session(session_manager, "fr"))
        session_b = asyncio.run(self._create_and_activate_session(session_manager, "en"))

        latest = session_manager.get_active_session()
        assert latest is not None
        assert latest["id"] == session_b
        assert latest["status"] == "active"

        direct_lookup = session_manager.get_active_session(session_id=session_a)
        assert direct_lookup is not None
        assert direct_lookup["id"] == session_a
        assert direct_lookup["status"] == "active"

    async def _create_and_activate_session(self, session_manager, language):
        """Helper: Session erstellen und aktivieren"""
        session_id = await session_manager.create_admin_session()
        await session_manager.activate_session(session_id, language)
        return session_id


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

        # Alle Sessions sollen aktiv oder pending bleiben
        active_sessions = [
            s for s in session_manager.sessions.values()
            if s.status != SessionStatus.TERMINATED
        ]
        assert len(active_sessions) == 10

        # Beendete Sessions bleiben für History im Speicher
        terminated_sessions = [
            s for s in session_manager.sessions.values()
            if s.status == SessionStatus.TERMINATED
        ]
        assert len(terminated_sessions) == 0

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
