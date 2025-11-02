# tests/test_mobile_optimization.py
"""
Tests für Mobile-Optimization Features
- Adaptive Polling-Intervalle
- Background-Tab-Detection
- Battery-Optimization
- Network-Quality-Adaptation
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock
from services.api_gateway.websocket import (
    WebSocketManager, WebSocketConnection, AdaptivePollingManager,
    ConnectionState, ClientType, MessageType
)
from services.api_gateway.session_manager import SessionManager, Session, SessionStatus
from services.api_gateway.routes.session import ClientActivityUpdate


class TestAdaptivePollingManager:
    """Tests für AdaptivePollingManager"""

    def setup_method(self):
        """Test-Setup"""
        self.polling_manager = AdaptivePollingManager()

    def test_desktop_active_polling(self):
        """Test: Desktop-Client mit aktivem Tab hat schnellstes Polling"""
        connection = self._create_mock_connection(is_mobile=False, tab_active=True)
        interval = self.polling_manager.get_optimal_interval(connection)
        assert interval == 3  # active_desktop

    def test_mobile_active_polling(self):
        """Test: Mobile-Client mit aktivem Tab hat moderates Polling"""
        connection = self._create_mock_connection(is_mobile=True, tab_active=True)
        interval = self.polling_manager.get_optimal_interval(connection)
        assert interval == 5  # active_mobile

    def test_mobile_background_polling(self):
        """Test: Mobile-Client im Hintergrund hat langsames Polling"""
        connection = self._create_mock_connection(is_mobile=True, tab_active=False)
        interval = self.polling_manager.get_optimal_interval(connection)
        assert interval == 30  # background_mobile

    def test_battery_saver_mode(self):
        """Test: Niedriger Akku aktiviert Battery-Saver-Mode"""
        connection = self._create_mock_connection(
            is_mobile=True,
            tab_active=True,
            battery_level=0.15  # <20%
        )
        interval = self.polling_manager.get_optimal_interval(connection)
        assert interval == 60  # battery_saver

    def test_slow_network_adaptation(self):
        """Test: Langsame Netzwerkverbindung erhöht Polling-Intervall"""
        connection = self._create_mock_connection(
            is_mobile=True,
            tab_active=True,
            network_quality="slow"
        )
        interval = self.polling_manager.get_optimal_interval(connection)
        assert interval == 15  # slow_network

    def test_offline_mode(self):
        """Test: Offline-Modus hat sehr langsames Polling"""
        connection = self._create_mock_connection(
            network_quality="offline"
        )
        interval = self.polling_manager.get_optimal_interval(connection)
        assert interval == 120  # offline_mode

    def test_update_client_status(self):
        """Test: Client-Status-Updates ändern Polling-Intervall"""
        connection = self._create_mock_connection(is_mobile=True, tab_active=True)

        # Initial: active_mobile (5s)
        initial_interval = self.polling_manager.get_optimal_interval(connection)
        assert initial_interval == 5

        # Tab wird inaktiv -> background_mobile (30s)
        new_interval = self.polling_manager.update_client_status(
            connection, tab_active=False
        )
        assert new_interval == 30
        assert connection.current_polling_interval == 30

    def test_battery_optimization_tips(self):
        """Test: Battery-Optimization-Tips werden korrekt generiert"""
        connection = self._create_mock_connection(
            is_mobile=True,
            tab_active=False,
            battery_level=0.25,
            network_quality="slow"
        )

        tips = self.polling_manager.get_battery_optimization_tips(connection)

        assert len(tips) == 3
        assert any("Niedriger Akkustand" in tip for tip in tips)
        assert any("Tab im Hintergrund" in tip for tip in tips)
        assert any("Langsame Verbindung" in tip for tip in tips)

    def _create_mock_connection(self, **kwargs):
        """Mock WebSocketConnection erstellen"""
        mock_websocket = Mock()
        connection = WebSocketConnection(
            websocket=mock_websocket,
            client_type=ClientType.CUSTOMER,
            session_id="TEST123",
            connected_at=datetime.now(),
            last_heartbeat=datetime.now(),
            state=ConnectionState.CONNECTED,
            is_mobile=kwargs.get("is_mobile", False),
            tab_active=kwargs.get("tab_active", True),
            battery_level=kwargs.get("battery_level", 1.0),
            network_quality=kwargs.get("network_quality", "good"),
            current_polling_interval=5
        )
        return connection


class TestWebSocketMobileOptimization:
    """Tests für WebSocket Mobile-Optimization Integration"""

    def setup_method(self):
        """Test-Setup"""
        self.session_manager = SessionManager()
        self.session_manager.reset(clear_persistence=True)
        self.websocket_manager = WebSocketManager(self.session_manager)

    @pytest.mark.asyncio
    async def test_connection_with_mobile_info(self):
        """Test: WebSocket-Verbindung mit Mobile-Device-Info"""
        mock_websocket = AsyncMock()
        mock_websocket.accept = AsyncMock()

        client_info = {
            "is_mobile": True,
            "battery_level": 0.8,
            "network_quality": "good"
        }

        connection_id = await self.websocket_manager.connect_websocket(
            websocket=mock_websocket,
            session_id="TEST123",
            client_type=ClientType.CUSTOMER,
            client_info=client_info
        )

        connection = self.websocket_manager.all_connections[connection_id]
        assert connection.is_mobile == True
        assert connection.battery_level == 0.8
        assert connection.network_quality == "good"
        assert connection.current_polling_interval == 5  # active_mobile

    @pytest.mark.asyncio
    async def test_tab_visibility_change_handler(self):
        """Test: Tab-Visibility-Change Handler"""
        # Setup
        mock_websocket = AsyncMock()
        connection_id = await self._create_test_connection(mock_websocket, is_mobile=True)
        connection = self.websocket_manager.all_connections[connection_id]

        # Tab wird inaktiv
        message = {
            "type": MessageType.TAB_VISIBILITY_CHANGE.value,
            "is_visible": False
        }

        await self.websocket_manager._handle_tab_visibility_change(connection, message)

        # Polling-Intervall sollte sich geändert haben
        assert connection.tab_active == False
        assert connection.current_polling_interval == 30  # background_mobile

    @pytest.mark.asyncio
    async def test_battery_status_update_handler(self):
        """Test: Battery-Status-Update Handler"""
        # Setup
        mock_websocket = AsyncMock()
        connection_id = await self._create_test_connection(mock_websocket, is_mobile=True)
        connection = self.websocket_manager.all_connections[connection_id]

        # Battery wird niedrig
        message = {
            "type": MessageType.BATTERY_STATUS_UPDATE.value,
            "battery_level": 0.15,  # <20%
            "is_charging": False
        }

        await self.websocket_manager._handle_battery_status_update(connection, message)

        # Battery-Saver-Mode sollte aktiviert sein
        assert connection.battery_level == 0.15
        assert connection.current_polling_interval == 60  # battery_saver

    @pytest.mark.asyncio
    async def test_network_status_change_handler(self):
        """Test: Network-Status-Change Handler"""
        # Setup
        mock_websocket = AsyncMock()
        connection_id = await self._create_test_connection(mock_websocket)
        connection = self.websocket_manager.all_connections[connection_id]

        # Netzwerk wird langsam
        message = {
            "type": MessageType.NETWORK_STATUS_CHANGE.value,
            "network_quality": "slow",
            "connection_type": "cellular"
        }

        await self.websocket_manager._handle_network_status_change(connection, message)

        # Polling sollte angepasst sein
        assert connection.network_quality == "slow"
        assert connection.current_polling_interval == 15  # slow_network

    @pytest.mark.asyncio
    async def test_polling_interval_update_notification(self):
        """Test: Polling-Intervall-Update-Notification wird gesendet"""
        mock_websocket = AsyncMock()
        connection_id = await self._create_test_connection(mock_websocket, is_mobile=True)
        connection = self.websocket_manager.all_connections[connection_id]

        # Mock zurücksetzen um nur neue Calls zu testen
        mock_websocket.send_json.reset_mock()

        # Polling-Intervall-Update senden
        await self.websocket_manager._send_polling_interval_update(
            connection, new_interval=30, reason="test_optimization"
        )

        # WebSocket send_json sollte aufgerufen worden sein
        mock_websocket.send_json.assert_called_once()
        call_args = mock_websocket.send_json.call_args[0][0]

        assert call_args["type"] == MessageType.POLLING_INTERVAL_UPDATE.value
        assert call_args["new_interval"] == 30
        assert call_args["reason"] == "test_optimization"

    @pytest.mark.asyncio
    async def test_battery_saver_notification(self):
        """Test: Battery-Saver-Benachrichtigung wird gesendet"""
        mock_websocket = AsyncMock()
        connection_id = await self._create_test_connection(mock_websocket, is_mobile=True)
        connection = self.websocket_manager.all_connections[connection_id]

        # Mock zurücksetzen um nur neue Calls zu testen
        mock_websocket.send_json.reset_mock()

        # Battery-Saver-Modus senden
        await self.websocket_manager._send_battery_saver_notification(connection)

        # WebSocket send_json sollte aufgerufen worden sein
        mock_websocket.send_json.assert_called_once()
        call_args = mock_websocket.send_json.call_args[0][0]

        assert call_args["type"] == "battery_saver_mode"
        assert call_args["new_polling_interval"] == 60

    async def _create_test_connection(self, mock_websocket, **kwargs):
        """Test-WebSocket-Connection erstellen"""
        mock_websocket.accept = AsyncMock()

        client_info = {
            "is_mobile": kwargs.get("is_mobile", False),
            "battery_level": kwargs.get("battery_level", 1.0),
            "network_quality": kwargs.get("network_quality", "good")
        }

        return await self.websocket_manager.connect_websocket(
            websocket=mock_websocket,
            session_id="TEST123",
            client_type=ClientType.CUSTOMER,
            client_info=client_info
        )


class TestClientActivityAPI:
    """Tests für Client-Activity-Update API"""

    def test_client_activity_update_model(self):
        """Test: ClientActivityUpdate Pydantic-Model Validation"""
        # Valid update
        update = ClientActivityUpdate(
            is_mobile=True,
            tab_active=False,
            battery_level=0.75,
            is_charging=True,
            network_quality="good",
            connection_type="wifi"
        )

        assert update.is_mobile == True
        assert update.tab_active == False
        assert update.battery_level == 0.75
        assert update.network_quality == "good"

    def test_battery_level_validation(self):
        """Test: Battery-Level-Validation (0.0-1.0)"""
        # Valid range
        update = ClientActivityUpdate(battery_level=0.5)
        assert update.battery_level == 0.5

        # Invalid range (should be clamped or raise error)
        with pytest.raises(ValueError):
            ClientActivityUpdate(battery_level=1.5)

        with pytest.raises(ValueError):
            ClientActivityUpdate(battery_level=-0.1)

    def test_optional_fields(self):
        """Test: Alle Felder sind optional"""
        update = ClientActivityUpdate()
        assert update.is_mobile is None
        assert update.tab_active is None
        assert update.battery_level is None


# Integration Tests würden hier folgen...
# (Vollständige API-Endpunkt-Tests mit FastAPI TestClient)