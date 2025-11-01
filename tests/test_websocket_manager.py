# tests/test_websocket_manager.py
"""
Unit-Tests für WebSocket-Manager
Testet Session-basierte Connection-Pools, Heartbeat-System, Graceful-Disconnect und Polling-Fallback
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

# FastAPI WebSocket-Test-Utilities
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket

# WebSocket-Manager und Dependencies
from services.api_gateway.websocket import (
    WebSocketManager, WebSocketConnection, ConnectionState, MessageType
)
from services.api_gateway.session_manager import SessionManager, ClientType, SessionStatus


class MockWebSocket:
    """Mock WebSocket für Tests"""

    def __init__(self):
        self.messages_sent = []
        self.is_closed = False
        self.close_code = None
        self.close_reason = None
        self.client_state = Mock()
        self.client_state.DISCONNECTED = "DISCONNECTED"

    async def accept(self):
        pass

    async def send_json(self, data):
        self.messages_sent.append(data)

    async def receive_json(self):
        # Simuliert eingehende Nachrichten
        return {"type": "heartbeat_pong"}

    async def close(self, code=1000, reason=""):
        self.is_closed = True
        self.close_code = code
        self.close_reason = reason


@pytest.fixture
def session_manager():
    """Session-Manager für Tests"""
    return SessionManager()


@pytest.fixture
def websocket_manager(session_manager):
    """WebSocket-Manager für Tests"""
    return WebSocketManager(session_manager)


@pytest.fixture
def mock_websocket():
    """Mock WebSocket-Verbindung"""
    return MockWebSocket()


@pytest.mark.asyncio
class TestWebSocketManager:
    """Tests für WebSocket-Manager-Grundfunktionen"""

    async def test_websocket_connection_creation(self, websocket_manager, mock_websocket):
        """Test: WebSocket-Verbindung erstellen"""
        session_id = "TEST123"
        client_type = ClientType.ADMIN

        connection_id = await websocket_manager.connect_websocket(
            mock_websocket, session_id, client_type
        )

        # Assertions
        assert connection_id is not None
        assert session_id in websocket_manager.session_connections
        assert connection_id in websocket_manager.all_connections

        connection = websocket_manager.all_connections[connection_id]
        assert connection.session_id == session_id
        assert connection.client_type == client_type
        assert connection.state == ConnectionState.CONNECTED

        # Connection-ACK wurde gesendet
        assert len(mock_websocket.messages_sent) == 1
        ack_message = mock_websocket.messages_sent[0]
        assert ack_message["type"] == MessageType.CONNECTION_ACK.value
        assert ack_message["session_id"] == session_id

    async def test_session_based_connection_pools(self, websocket_manager):
        """Test: Session-basierte Connection-Pools"""
        session1_id = "SESSION1"
        session2_id = "SESSION2"

        mock_ws1 = MockWebSocket()
        mock_ws2 = MockWebSocket()
        mock_ws3 = MockWebSocket()

        # Verbindungen zu verschiedenen Sessions erstellen
        conn1 = await websocket_manager.connect_websocket(mock_ws1, session1_id, ClientType.ADMIN)
        conn2 = await websocket_manager.connect_websocket(mock_ws2, session1_id, ClientType.CUSTOMER)
        conn3 = await websocket_manager.connect_websocket(mock_ws3, session2_id, ClientType.ADMIN)

        # Assertions: Session-Pools sind korrekt organisiert
        assert len(websocket_manager.session_connections[session1_id]) == 2
        assert len(websocket_manager.session_connections[session2_id]) == 1
        assert len(websocket_manager.all_connections) == 3

        # Session-Connections abrufen
        session1_connections = websocket_manager.get_session_connections(session1_id)
        assert len(session1_connections) == 2

        client_types = [conn["client_type"] for conn in session1_connections]
        assert ClientType.ADMIN.value in client_types
        assert ClientType.CUSTOMER.value in client_types

    async def test_graceful_disconnect(self, websocket_manager, mock_websocket):
        """Test: Graceful WebSocket-Disconnect"""
        session_id = "TEST123"
        connection_id = await websocket_manager.connect_websocket(
            mock_websocket, session_id, ClientType.ADMIN
        )

        # Disconnect ausführen
        await websocket_manager.disconnect_websocket(connection_id, "test_disconnect")

        # Assertions
        assert mock_websocket.is_closed
        assert mock_websocket.close_code == 1000
        assert mock_websocket.close_reason == "test_disconnect"

        # Connection wurde aus Pools entfernt
        assert connection_id not in websocket_manager.all_connections
        assert session_id not in websocket_manager.session_connections or \
               connection_id not in websocket_manager.session_connections[session_id]

        # Disconnect-Message wurde gesendet
        disconnect_messages = [msg for msg in mock_websocket.messages_sent
                             if msg.get("type") == MessageType.CONNECTION_STATUS.value]
        assert len(disconnect_messages) == 1
        assert disconnect_messages[0]["status"] == "disconnecting"

    async def test_session_termination_graceful_disconnect(self, websocket_manager):
        """Test: Graceful-Disconnect bei Session-Termination"""
        session_id = "TEST123"

        # Mehrere Verbindungen zur Session
        mock_ws1 = MockWebSocket()
        mock_ws2 = MockWebSocket()

        conn1 = await websocket_manager.connect_websocket(mock_ws1, session_id, ClientType.ADMIN)
        conn2 = await websocket_manager.connect_websocket(mock_ws2, session_id, ClientType.CUSTOMER)

        # Session beenden
        await websocket_manager.handle_session_termination(session_id, "test_termination")

        # Assertions: Beide Verbindungen wurden geschlossen
        assert mock_ws1.is_closed
        assert mock_ws2.is_closed

        # Termination-Messages wurden gesendet
        termination_msgs1 = [msg for msg in mock_ws1.messages_sent
                           if msg.get("type") == MessageType.SESSION_TERMINATED.value]
        termination_msgs2 = [msg for msg in mock_ws2.messages_sent
                           if msg.get("type") == MessageType.SESSION_TERMINATED.value]

        assert len(termination_msgs1) == 1
        assert len(termination_msgs2) == 1
        assert termination_msgs1[0]["reason"] == "test_termination"

        # Session-Connection-Pool wurde geleert
        assert session_id not in websocket_manager.session_connections

    async def test_heartbeat_system_start_stop(self, websocket_manager):
        """Test: Heartbeat-System starten und stoppen"""
        # Heartbeat-System starten
        await websocket_manager.start_heartbeat_system()
        assert websocket_manager.heartbeat_task is not None
        assert not websocket_manager.heartbeat_task.done()

        # Heartbeat-System stoppen
        await websocket_manager.stop_heartbeat_system()
        assert websocket_manager.heartbeat_task is None

    async def test_heartbeat_ping_pong(self, websocket_manager, mock_websocket):
        """Test: Heartbeat-Ping/Pong-Mechanismus"""
        session_id = "TEST123"
        connection_id = await websocket_manager.connect_websocket(
            mock_websocket, session_id, ClientType.ADMIN
        )

        # Heartbeat-Pings manuell senden
        await websocket_manager._send_heartbeat_pings()

        # Assertions: Ping wurde gesendet
        ping_messages = [msg for msg in mock_websocket.messages_sent
                        if msg.get("type") == MessageType.HEARTBEAT_PING.value]
        assert len(ping_messages) == 1

        # Pong simulieren
        connection = websocket_manager.all_connections[connection_id]
        old_heartbeat = connection.last_heartbeat

        await asyncio.sleep(0.01)  # Kleine Verzögerung für Timestamp-Unterschied
        await websocket_manager._handle_heartbeat_pong(connection)

        # Assertions: Heartbeat wurde aktualisiert
        assert connection.last_heartbeat > old_heartbeat
        assert connection.state == ConnectionState.CONNECTED

    async def test_heartbeat_timeout_detection(self, websocket_manager, mock_websocket):
        """Test: Heartbeat-Timeout-Erkennung"""
        session_id = "TEST123"
        connection_id = await websocket_manager.connect_websocket(
            mock_websocket, session_id, ClientType.ADMIN
        )

        # Heartbeat-Timestamp in die Vergangenheit setzen
        connection = websocket_manager.all_connections[connection_id]
        connection.last_heartbeat = datetime.now() - timedelta(seconds=70)  # Über Timeout-Limit

        # Timeout-Check ausführen
        await websocket_manager._check_heartbeat_timeouts()

        # Assertions: Connection wurde wegen Timeout geschlossen
        assert mock_websocket.is_closed
        assert mock_websocket.close_code == 1001  # Heartbeat-Timeout-Code
        assert connection_id not in websocket_manager.all_connections
        assert websocket_manager.connection_stats["heartbeat_timeouts"] == 1

    async def test_polling_fallback_activation(self, websocket_manager):
        """Test: Polling-Fallback aktivieren"""
        session_id = "TEST123"
        client_type = ClientType.ADMIN

        polling_id = await websocket_manager.enable_polling_fallback(session_id, client_type)

        # Assertions
        assert polling_id is not None
        assert polling_id in websocket_manager.polling_clients
        assert websocket_manager.connection_stats["polling_fallbacks"] == 1

        # Polling-Messages abrufen (momentan leer)
        messages = await websocket_manager.get_polling_messages(polling_id)
        assert messages == []

    async def test_broadcast_to_session(self, websocket_manager):
        """Test: Broadcasting an Session-Teilnehmer"""
        session_id = "TEST123"

        mock_ws1 = MockWebSocket()
        mock_ws2 = MockWebSocket()

        conn1 = await websocket_manager.connect_websocket(mock_ws1, session_id, ClientType.ADMIN)
        conn2 = await websocket_manager.connect_websocket(mock_ws2, session_id, ClientType.CUSTOMER)

        # Test-Message broadcasten
        test_message = {
            "type": "test_broadcast",
            "content": "Hello Session!"
        }

        await websocket_manager.broadcast_to_session(session_id, test_message)

        # Assertions: Beide Clients haben Message erhalten
        broadcast_msgs1 = [msg for msg in mock_ws1.messages_sent
                          if msg.get("type") == "test_broadcast"]
        broadcast_msgs2 = [msg for msg in mock_ws2.messages_sent
                          if msg.get("type") == "test_broadcast"]

        assert len(broadcast_msgs1) == 1
        assert len(broadcast_msgs2) == 1
        assert broadcast_msgs1[0]["content"] == "Hello Session!"

    async def test_differentiated_broadcasting(self, websocket_manager):
        """Test: Differentiated Broadcasting (Sender vs. Empfänger)"""
        session_id = "TEST123"

        mock_admin_ws = MockWebSocket()
        mock_customer_ws = MockWebSocket()

        await websocket_manager.connect_websocket(mock_admin_ws, session_id, ClientType.ADMIN)
        await websocket_manager.connect_websocket(mock_customer_ws, session_id, ClientType.CUSTOMER)

        # Differentiated Broadcast
        original_message = {"type": "message", "text": "Original German Text"}
        translated_message = {"type": "message", "text": "Translated English Text"}

        await websocket_manager.broadcast_with_differentiated_content(
            session_id,
            ClientType.ADMIN,  # Admin ist Sender
            original_message,
            translated_message
        )

        # Assertions
        # Admin (Sender) erhält original_message
        admin_messages = [msg for msg in mock_admin_ws.messages_sent
                         if msg.get("type") == "message"]
        assert len(admin_messages) == 1
        assert admin_messages[0]["text"] == "Original German Text"

        # Customer (Empfänger) erhält translated_message
        customer_messages = [msg for msg in mock_customer_ws.messages_sent
                           if msg.get("type") == "message"]
        assert len(customer_messages) == 1
        assert customer_messages[0]["text"] == "Translated English Text"

    async def test_connection_stats_monitoring(self, websocket_manager):
        """Test: Connection-Statistiken für Monitoring"""
        session_id = "TEST123"

        mock_ws1 = MockWebSocket()
        mock_ws2 = MockWebSocket()

        # Verbindungen erstellen
        conn1 = await websocket_manager.connect_websocket(mock_ws1, session_id, ClientType.ADMIN)
        conn2 = await websocket_manager.connect_websocket(mock_ws2, session_id, ClientType.CUSTOMER)

        # Polling-Fallback aktivieren
        await websocket_manager.enable_polling_fallback(session_id, ClientType.ADMIN)

        # Stats abrufen
        stats = websocket_manager.get_connection_stats()

        # Assertions
        assert stats["global_stats"]["total_connections"] == 2
        assert stats["global_stats"]["active_connections"] == 2
        assert stats["global_stats"]["polling_fallbacks"] == 1

        assert session_id in stats["session_stats"]
        session_stats = stats["session_stats"][session_id]
        assert session_stats["total_connections"] == 2
        assert session_stats["active_connections"] == 2
        assert ClientType.ADMIN.value in session_stats["client_types"]
        assert ClientType.CUSTOMER.value in session_stats["client_types"]

    async def test_connection_lifecycle_is_alive(self, websocket_manager, mock_websocket):
        """Test: Connection-Lifecycle und is_alive-Checks"""
        session_id = "TEST123"
        connection_id = await websocket_manager.connect_websocket(
            mock_websocket, session_id, ClientType.ADMIN
        )

        connection = websocket_manager.all_connections[connection_id]

        # Connection ist initial alive
        assert connection.is_alive()
        assert connection.state == ConnectionState.CONNECTED

        # Connection-Status ändern
        connection.state = ConnectionState.DISCONNECTED
        assert not connection.is_alive()

        # Heartbeat-Timeout simulieren
        connection.state = ConnectionState.CONNECTED
        connection.last_heartbeat = datetime.now() - timedelta(seconds=70)
        assert not connection.is_alive()  # Heartbeat-Timeout

    async def test_exponential_backoff_calculation(self, websocket_manager):
        """Test: Exponential Backoff für Reconnects"""
        # Test verschiedene Reconnect-Attempts
        delay1 = websocket_manager._calculate_reconnect_delay(0)  # Erster Versuch
        delay2 = websocket_manager._calculate_reconnect_delay(1)  # Zweiter Versuch
        delay3 = websocket_manager._calculate_reconnect_delay(3)  # Vierter Versuch
        delay_max = websocket_manager._calculate_reconnect_delay(10)  # Maximal-Test

        # Assertions: Exponential backoff
        assert delay1 == 1  # base_delay * 2^0
        assert delay2 == 2  # base_delay * 2^1
        assert delay3 == 8  # base_delay * 2^3
        assert delay_max == 60  # Maximum cap

        # Delays sollten wachsen (bis zum Maximum)
        assert delay1 < delay2 < delay3

    async def test_error_handling_dead_connections(self, websocket_manager):
        """Test: Error-Handling für tote Verbindungen"""
        session_id = "TEST123"

        # WebSocket mit Send-Fehler simulieren
        mock_ws_broken = Mock()
        mock_ws_broken.accept = AsyncMock()
        mock_ws_broken.send_json = AsyncMock(side_effect=Exception("Connection broken"))
        mock_ws_broken.close = AsyncMock()
        mock_ws_broken.client_state = Mock()
        mock_ws_broken.client_state.DISCONNECTED = "DISCONNECTED"

        connection_id = await websocket_manager.connect_websocket(
            mock_ws_broken, session_id, ClientType.ADMIN
        )

        # Broadcast-Test mit kaputtem WebSocket
        test_message = {"type": "test", "content": "test"}

        # Sollte nicht crashen trotz Send-Fehler
        await websocket_manager.broadcast_to_session(session_id, test_message)

        # Connection sollte als ERROR markiert werden
        connection = websocket_manager.all_connections.get(connection_id)
        if connection:  # Might be cleaned up
            assert connection.state == ConnectionState.ERROR

    async def test_client_join_leave_notifications(self, websocket_manager):
        """Test: Client-Join/Leave-Notifications"""
        session_id = "TEST123"

        # Erste Verbindung (Admin)
        mock_admin_ws = MockWebSocket()
        admin_conn_id = await websocket_manager.connect_websocket(
            mock_admin_ws, session_id, ClientType.ADMIN
        )

        # Zweite Verbindung (Customer) - sollte Join-Notification an Admin senden
        mock_customer_ws = MockWebSocket()
        customer_conn_id = await websocket_manager.connect_websocket(
            mock_customer_ws, session_id, ClientType.CUSTOMER
        )

        # Admin sollte Customer-Join-Notification erhalten haben
        join_messages = [msg for msg in mock_admin_ws.messages_sent
                        if msg.get("type") == MessageType.CLIENT_JOINED.value]
        assert len(join_messages) == 1
        assert join_messages[0]["client_type"] == ClientType.CUSTOMER.value

        # Customer disconnecten - sollte Leave-Notification an Admin senden
        await websocket_manager.disconnect_websocket(customer_conn_id, "test_leave")

        # Admin sollte Customer-Leave-Notification erhalten haben
        leave_messages = [msg for msg in mock_admin_ws.messages_sent
                         if msg.get("type") == MessageType.CLIENT_LEFT.value]
        assert len(leave_messages) == 1
        assert leave_messages[0]["client_type"] == ClientType.CUSTOMER.value
        assert leave_messages[0]["reason"] == "test_leave"


@pytest.mark.asyncio
class TestWebSocketIntegration:
    """Integration-Tests für WebSocket-Manager mit SessionManager"""

    async def test_integration_with_session_manager(self, websocket_manager, mock_websocket):
        """Test: Integration mit SessionManager"""
        # Session im SessionManager erstellen
        session_id = await websocket_manager.session_manager.create_admin_session()

        # WebSocket-Verbindung zur Session
        connection_id = await websocket_manager.connect_websocket(
            mock_websocket, session_id, ClientType.ADMIN
        )

        # Session sollte WebSocket-Connection haben
        session = websocket_manager.session_manager.get_session(session_id)
        assert session.admin_connected == True

        # WebSocket-Verbindung über SessionManager abrufen
        session_ws = websocket_manager.session_manager.get_websocket_connection(
            session_id, ClientType.ADMIN
        )
        assert session_ws == mock_websocket

    async def test_session_termination_via_session_manager(self, websocket_manager, session_manager):
        """Test: Session-Termination über SessionManager löst WebSocket-Cleanup aus"""
        # Session und WebSocket-Verbindung erstellen
        session_id = await session_manager.create_admin_session()

        mock_ws = MockWebSocket()
        connection_id = await websocket_manager.connect_websocket(
            mock_ws, session_id, ClientType.ADMIN
        )

        # Session über SessionManager beenden
        await session_manager.terminate_session(session_id, "integration_test")

        # WebSocket sollte geschlossen worden sein
        assert mock_ws.is_closed

        # WebSocket-Connection sollte aus Pools entfernt worden sein
        assert connection_id not in websocket_manager.all_connections

    async def test_single_session_policy_websocket_cleanup(self, websocket_manager, session_manager):
        """Test: Single-Session-Policy beendet alle WebSocket-Verbindungen"""
        # Erste Session mit WebSocket
        session1_id = await session_manager.create_admin_session()
        mock_ws1 = MockWebSocket()
        conn1_id = await websocket_manager.connect_websocket(mock_ws1, session1_id, ClientType.ADMIN)

        # Zweite Session erstellen (sollte erste beenden)
        session2_id = await session_manager.create_admin_session()

        # Erste WebSocket-Verbindung sollte geschlossen worden sein
        assert mock_ws1.is_closed
        assert conn1_id not in websocket_manager.all_connections

        # Termination-Message sollte gesendet worden sein
        termination_msgs = [msg for msg in mock_ws1.messages_sent
                          if msg.get("type") == MessageType.SESSION_TERMINATED.value]
        assert len(termination_msgs) == 1
        assert termination_msgs[0]["reason"] == "new_session_created"


if __name__ == "__main__":
    # Tests direkt ausführen für Debugging
    pytest.main([__file__, "-v"])