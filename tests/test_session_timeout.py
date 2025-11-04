# tests/test_session_timeout.py
"""
Tests für Session-Timeout-Management
"""

import pytest
from datetime import datetime, timedelta
from services.api_gateway.session_manager import SessionManager, Session, SessionStatus, ClientType


class TestSessionTimeoutManagement:
    """Tests für Session-Timeout-Features"""

    def setup_method(self):
        """Test-Setup - frische SessionManager-Instanz"""
        self.session_manager = SessionManager()
        self.session_manager.reset(clear_persistence=True)

    def test_session_activity_update(self):
        """Test: Session-Aktivität wird korrekt aktualisiert"""
        # Session erstellen
        session = Session(id="TEST123")
        original_time = session.last_activity

        # Kurz warten und Aktivität aktualisieren
        session.update_activity()

        # Aktivität sollte aktualisiert sein
        assert session.last_activity > original_time
        assert not session.timeout_warning_sent

    def test_timeout_warning_detection(self):
        """Test: Timeout-Warning wird korrekt erkannt"""
        # Session mit vergangenem Zeitstempel erstellen
        session = Session(id="TEST123", status=SessionStatus.ACTIVE)
        session.last_activity = datetime.now() - timedelta(minutes=26)  # 26 Minuten alt
        session.warning_timeout_minutes = 25

        # Timeout-Warning sollte fällig sein
        assert session.is_timeout_warning_due()

        # Nach dem Senden sollte es nicht mehr fällig sein
        session.timeout_warning_sent = True
        assert not session.is_timeout_warning_due()

    def test_session_timeout_detection(self):
        """Test: Session-Timeout wird korrekt erkannt"""
        # Session mit vergangenem Zeitstempel erstellen
        session = Session(id="TEST123", status=SessionStatus.ACTIVE)
        session.last_activity = datetime.now() - timedelta(minutes=31)  # 31 Minuten alt
        session.session_timeout_minutes = 30

        # Session sollte Timeout haben
        assert session.is_timeout_due()

    def test_no_timeout_for_terminated_session(self):
        """Test: Beendete Sessions haben nie Timeout"""
        session = Session(id="TEST123", status=SessionStatus.TERMINATED)
        session.last_activity = datetime.now() - timedelta(hours=2)  # 2 Stunden alt

        # Keine Timeouts für beendete Sessions
        assert not session.is_timeout_warning_due()
        assert not session.is_timeout_due()

    @pytest.mark.asyncio
    async def test_session_manager_timeout_check(self):
        """Test: SessionManager prüft Timeouts korrekt"""
        # Test-Session mit Timeout erstellen
        session_id = await self.session_manager.create_admin_session()
        session = self.session_manager.get_session(session_id)

        # Session auf vergangenen Zeitstempel setzen
        session.last_activity = datetime.now() - timedelta(minutes=31)
        session.status = SessionStatus.ACTIVE

        # Mock WebSocket-Manager um Broadcast-Fehler zu vermeiden
        class MockWebSocketManager:
            async def broadcast_to_session(self, session_id, message):
                pass

            async def handle_session_termination(self, session_id, reason):
                pass

        self.session_manager.websocket_manager = MockWebSocketManager()

        # Timeout-Check ausführen
        await self.session_manager.check_session_timeouts()

        # Session sollte beendet sein
        updated_session = self.session_manager.get_session(session_id)
        assert updated_session.status == SessionStatus.TERMINATED
        assert updated_session.termination_reason == "session_timeout"

    def test_session_activity_on_message(self):
        """Test: Session-Aktivität wird bei neuen Nachrichten aktualisiert"""
        from services.api_gateway.session_manager import SessionMessage

        # Session erstellen
        session_id = "TEST123"
        session = Session(id=session_id, status=SessionStatus.ACTIVE)
        self.session_manager.sessions[session_id] = session

        original_time = session.last_activity

        # Nachricht hinzufügen
        message = SessionMessage(
            id="MSG1",
            sender=ClientType.ADMIN,
            original_text="Test",
            translated_text="Test",
            audio_base64=None,
            source_lang="de",
            target_lang="en",
            timestamp=datetime.now()
        )

        self.session_manager.add_message(session_id, message)

        # Aktivität sollte aktualisiert sein
        assert session.last_activity > original_time

    def test_session_to_dict_includes_timeout_info(self):
        """Test: Session.to_dict() enthält Timeout-Informationen"""
        session = Session(id="TEST123")
        session_dict = session.to_dict()

        # Timeout-Felder sollten vorhanden sein
        assert "last_activity" in session_dict
        assert "timeout_warning_sent" in session_dict
        assert "session_timeout_minutes" in session_dict
        assert "minutes_since_activity" in session_dict
        assert isinstance(session_dict["minutes_since_activity"], int)

    @pytest.mark.asyncio
    async def test_heartbeat_updates_activity(self):
        """Test: Heartbeat aktualisiert Session-Aktivität"""
        # Session erstellen
        session_id = await self.session_manager.create_admin_session()
        session = self.session_manager.get_session(session_id)
        original_time = session.last_activity

        # Heartbeat simulieren
        await self.session_manager.heartbeat_received(session_id, ClientType.ADMIN)

        # Aktivität sollte aktualisiert sein
        updated_session = self.session_manager.get_session(session_id)
        assert updated_session.last_activity > original_time
