"""A client must not receive an echo of its own message.

`broadcast_to_session` excludes by connection id, and two handlers used to
rebuild that id from `int(connection.connected_at.timestamp())`. That string
matched the real id only because the id ended in `int(time.time())` too, and
both were computed in the same second -- an accident, not a lookup. Making
connection ids unique broke the accident, so the sender was included in its
own broadcast and every message arrived twice.

No test covered the exclusion path, so nothing failed when it broke. These do.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from services.api_gateway import websocket as ws
from services.api_gateway.session_manager import SessionManager


@pytest.fixture(autouse=True)
def _silent_monitor(monkeypatch):
    """broadcast_to_session reports every send to the monitor."""
    monkeypatch.setattr(ws, "get_websocket_monitor", lambda: Mock())


def _register(manager: ws.WebSocketManager, session_id: str, client_type: ws.ClientType):
    """Register a live connection the way connect_websocket does."""
    connection_id = manager._build_connection_id(session_id, client_type)
    socket = Mock()
    socket.send_json = AsyncMock()
    connection = ws.WebSocketConnection(
        websocket=socket,
        client_type=client_type,
        session_id=session_id,
        connected_at=datetime.now(timezone.utc),
        last_heartbeat=datetime.now(timezone.utc),
        state=ws.ConnectionState.CONNECTED,
    )
    manager.session_connections.setdefault(session_id, {})[connection_id] = connection
    manager.all_connections[connection_id] = connection
    return connection_id, connection, socket


@pytest.fixture
def session():
    manager = ws.WebSocketManager(SessionManager())
    _, admin, admin_socket = _register(manager, "session-1", ws.ClientType.ADMIN)
    _, customer, customer_socket = _register(
        manager, "session-1", ws.ClientType.CUSTOMER
    )
    return {
        "manager": manager,
        "admin": admin,
        "admin_socket": admin_socket,
        "customer": customer,
        "customer_socket": customer_socket,
    }


class TestTheSenderIsExcludedFromItsOwnBroadcast:
    async def test_a_chat_message_does_not_come_back_to_its_sender(self, session):
        await session["manager"]._handle_client_message(
            session["customer"], {"content": "hallo"}
        )

        assert session["customer_socket"].send_json.await_count == 0
        assert session["admin_socket"].send_json.await_count == 1

    async def test_a_typing_indicator_does_not_come_back_to_its_sender(self, session):
        await session["manager"]._handle_typing_indicator(
            session["admin"], {"is_typing": True}
        )

        assert session["admin_socket"].send_json.await_count == 0
        assert session["customer_socket"].send_json.await_count == 1


class TestTheExclusionUsesTheRegisteredId:
    def test_the_id_is_looked_up_not_rebuilt(self, session):
        """A rebuilt id is a guess about the id format; this is the map itself."""
        manager = session["manager"]
        registered = next(
            connection_id
            for connection_id, connection in manager.all_connections.items()
            if connection is session["customer"]
        )

        assert manager._registered_connection_id(session["customer"]) == registered

    def test_an_unregistered_connection_has_no_id(self, session):
        stranger = ws.WebSocketConnection(
            websocket=Mock(),
            client_type=ws.ClientType.CUSTOMER,
            session_id="session-1",
            connected_at=datetime.now(timezone.utc),
            last_heartbeat=datetime.now(timezone.utc),
            state=ws.ConnectionState.CONNECTED,
        )

        assert session["manager"]._registered_connection_id(stranger) is None
