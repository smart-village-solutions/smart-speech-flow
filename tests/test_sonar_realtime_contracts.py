"""Public transport contracts protected during realtime quality cleanup."""

import asyncio
import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from starlette.websockets import WebSocket

from services.api_gateway import websocket
from services.api_gateway import websocket_polling_routes as polling
from services.api_gateway.app import app
from services.api_gateway.routes import session as session_routes
from services.api_gateway.session_manager import ClientType, Session, SessionManager
from services.api_gateway.websocket_monitor import WebSocketMonitor


@pytest.fixture
def polling_client():
    session_routes.session_manager.reset(clear_persistence=True)
    polling.polling_store.clients.clear()
    yield TestClient(app)
    polling.polling_store.clients.clear()


@pytest.mark.parametrize("role", ["admin", "customer"])
def test_polling_timeout_openapi_and_request_contract(polling_client, role):
    path = f"/api/{role}/session/{{session_id}}/polling/{{polling_id}}"
    query = [
        parameter
        for parameter in app.openapi()["paths"][path]["get"]["parameters"]
        if parameter["in"] == "query"
    ]
    assert [parameter["name"] for parameter in query] == ["timeout"]
    assert query[0]["required"] is False
    schema = query[0]["schema"]
    assert (schema["default"], schema["minimum"], schema["maximum"]) == (0, 0, 60)

    session_id = polling_client.post("/api/admin/session/create").json()["session_id"]
    base = f"/api/{role}/session/{session_id}/polling"
    payload = {}
    if role == "admin":
        payload = polling_client.post(
            f"/api/admin/session/{session_id}/realtime-ticket",
            json={"transport": "polling"},
        ).json()
    activated = polling_client.post(base + "/activate", json=payload)
    assert activated.status_code == 200
    polling_id = activated.json()["polling_id"]
    path = f"{base}/{polling_id}"
    for query in ("", "?timeout=0", "?timeout=60"):
        stored = polling.polling_store.clients[polling_id]
        polling.polling_store.broadcast(stored.key, {"type": "heartbeat"})
        response = polling_client.get(path + query)
        assert response.status_code == 200
        assert response.json() == {
            "messages": [{"type": "heartbeat"}],
            "message_count": 1,
        }
    for invalid in (-1, 61):
        response = polling_client.get(path, params={"timeout": invalid})
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["query", "timeout"]
    response = polling_client.get(path + "/status")
    assert response.status_code == 200
    assert response.json() == {
        "polling_id": polling_id,
        "session_id": session_id,
        "client_type": role,
        "queued_messages": 0,
    }
    response = polling_client.post(path + "/recover")
    assert response.status_code == 200
    assert response.json() == {"status": "recovery_requested"}
    response = polling_client.post(
        path + "/send", json={"type": "heartbeat", "content": {}}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    response = polling_client.delete(path)
    assert response.status_code == 200
    assert response.json() == {"status": "disconnected"}
    assert polling_client.get(path + "/status").status_code == 404
    session = session_routes.session_manager.get_session(stored.key)
    assert (session.admin_connection_count, session.customer_connection_count) == (0, 0)


def test_admin_activation_documents_its_actual_not_found_response(polling_client):
    session_id = polling_client.post("/api/admin/session/create").json()["session_id"]
    response = polling_client.post(
        f"/api/admin/session/{session_id}/polling/activate",
        json={"ticket": "invalid-ticket"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}
    responses = app.openapi()["paths"][
        "/api/admin/session/{session_id}/polling/activate"
    ]["post"]["responses"]
    assert "404" in responses
    assert "503" in responses


async def test_poll_waits_for_an_event_and_drains_messages():
    client = polling.PollingClient(
        "poll-1", polling.TenantSessionKey("tenant-a", "SESSION1"), ClientType.ADMIN
    )
    pending = asyncio.create_task(polling._poll(client, 1))
    await asyncio.sleep(0)
    assert not pending.done()
    client.messages.append({"type": "ready"})
    client.event.set()
    assert await pending == {"messages": [{"type": "ready"}], "message_count": 1}
    assert not client.messages


async def test_poll_factory_preserves_timeout_keyword_and_cancellation():
    client = polling.PollingClient(
        "poll-1", polling.TenantSessionKey("tenant-a", "SESSION1"), ClientType.ADMIN
    )
    operation = polling._poll(client, timeout=0)
    assert inspect.iscoroutine(operation)
    assert await operation == {"messages": [], "message_count": 0}
    assert await polling._poll(client, timeout=1) == {
        "messages": [],
        "message_count": 0,
    }
    pending = asyncio.create_task(polling._poll(client, timeout=60))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending


async def test_legacy_echo_endpoint_keeps_callback_arguments():
    incoming = asyncio.Queue()
    outgoing = asyncio.Queue()
    incoming.put_nowait({"type": "websocket.connect"})
    incoming.put_nowait({"type": "websocket.receive", "text": "heartbeat"})
    incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})
    socket = WebSocket({"type": "websocket"}, receive=incoming.get, send=outgoing.put)
    await session_routes.websocket_endpoint(socket, "SESSION1", "admin")
    assert outgoing.get_nowait()["type"] == "websocket.accept"
    assert outgoing.get_nowait() == {
        "type": "websocket.send",
        "text": "pong: heartbeat",
    }
    assert outgoing.empty()


async def test_cancelled_poll_releases_every_pruned_clients_presence(monkeypatch):
    now = [0.0]
    store = polling.TenantPollingStore(clock=lambda: now[0])
    sessions = SessionManager()
    expired_key = polling.TenantSessionKey("tenant-a", "EXPIRED1")
    live_key = polling.TenantSessionKey("tenant-a", "CURRENT1")
    for key in (expired_key, live_key):
        sessions.sessions[key] = Session(id=key.session_id, tenant_id=key.tenant_id)
    store.activate(expired_key, ClientType.ADMIN)
    store.activate(expired_key, ClientType.CUSTOMER)
    sessions.admin_connected(expired_key)
    sessions.customer_connected(expired_key)
    now[0] = 121.0
    live_client = store.activate(live_key, ClientType.ADMIN)
    monkeypatch.setattr(polling, "polling_store", store)
    manager = websocket.WebSocketManager(sessions)
    loop = asyncio.get_running_loop()
    release_admin = sessions.admin_disconnected

    def release_and_cancel(key):
        release_admin(key)
        loop.call_soon_threadsafe(request_task.cancel)

    monkeypatch.setattr(sessions, "admin_disconnected", release_and_cancel)
    endpoint = next(
        route.endpoint for route in polling.router.routes if route.name == "admin_poll"
    )
    request_task = asyncio.create_task(
        endpoint(
            session_id=live_key.session_id,
            polling_id=live_client.polling_id,
            key=live_key,
            wait_seconds=60,
            manager=manager,
        )
    )
    with pytest.raises(asyncio.CancelledError):
        await request_task

    expired_session = sessions.get_session(expired_key)
    assert list(store.clients) == [live_client.polling_id]
    assert [
        expired_session.admin_connection_count,
        expired_session.customer_connection_count,
    ] == [0, 0]
    assert not expired_session.admin_connected
    assert not expired_session.customer_connected


async def test_terminated_polling_client_cannot_send_recover_or_read_status():
    client = polling.PollingClient(
        "poll-1",
        polling.TenantSessionKey("tenant-a", "SESSION1"),
        ClientType.ADMIN,
        terminated=True,
    )
    manager = websocket.WebSocketManager(SessionManager())
    message = polling.PollingMessage(type="message", content={"text": "private"})
    with pytest.raises(HTTPException) as sent:
        await polling._send(client, message, manager)
    assert (sent.value.status_code, sent.value.detail) == (
        404,
        "Polling client not found",
    )
    for action in (polling._status, polling._recover):
        with pytest.raises(HTTPException) as unavailable:
            action(client)
        assert (unavailable.value.status_code, unavailable.value.detail) == (
            404,
            "Polling client not found",
        )
    assert not client.messages


def test_customer_polling_principal_cannot_cross_tenants(monkeypatch):
    store = polling.TenantPollingStore()
    client = store.activate(
        polling.TenantSessionKey("tenant-a", "SESSION1"), ClientType.CUSTOMER
    )
    monkeypatch.setattr(polling, "polling_store", store)
    with pytest.raises(HTTPException) as unauthorized:
        polling.require_customer_polling_key(
            "SESSION1", client.polling_id, {"studio_tenant_id": "tenant-b"}
        )
    assert unauthorized.value.status_code == 404
    assert unauthorized.value.detail == "Polling client not found"


async def test_websocket_missing_session_keeps_close_code_and_reason():
    manager = websocket.WebSocketManager(SessionManager())
    incoming = asyncio.Queue()
    outgoing = asyncio.Queue()
    socket = WebSocket({"type": "websocket"}, receive=incoming.get, send=outgoing.put)
    await websocket.websocket_endpoint(
        socket,
        polling.TenantSessionKey("tenant-a", "MISSING1"),
        ClientType.ADMIN,
        manager,
        "https://translate.smart-village.solutions",
    )
    assert outgoing.get_nowait() == {
        "type": "websocket.close",
        "code": 1003,
        "reason": "Session not found",
    }
    assert outgoing.empty()


async def test_websocket_registration_race_keeps_close_code_and_reason(monkeypatch):
    sessions = SessionManager()
    key = polling.TenantSessionKey("tenant-a", "SESSION1")
    sessions.sessions[key] = Session(id="SESSION1", tenant_id="tenant-a")
    manager = websocket.WebSocketManager(sessions)
    register = sessions.add_websocket_connection

    async def expire_before_registration(*args):
        sessions.sessions.pop(key)
        await register(*args)

    monkeypatch.setattr(
        sessions, "add_websocket_connection", expire_before_registration
    )
    incoming = asyncio.Queue()
    outgoing = asyncio.Queue()
    incoming.put_nowait({"type": "websocket.connect"})
    socket = WebSocket({"type": "websocket"}, receive=incoming.get, send=outgoing.put)
    with pytest.raises(RuntimeError, match="Session unavailable"):
        await manager.connect_websocket(socket, key, ClientType.ADMIN)
    assert outgoing.get_nowait()["type"] == "websocket.accept"
    assert outgoing.get_nowait() == {
        "type": "websocket.close",
        "code": 4404,
        "reason": "Session not found",
    }
    assert outgoing.empty()
    assert not manager.all_connections


def test_monitor_callback_arguments_preserve_metrics_and_redact_payloads(caplog):
    monitor = WebSocketMonitor(registry=CollectorRegistry())
    metrics = monitor.connection_established("connection", "SESSION1", "admin")
    monitor.message_sent("connection", "hé", "private-type")
    monitor.message_received("connection", "hello", "private-type")
    monitor.record_error("connection", "private-error", "private-details")
    assert (metrics.messages_sent, metrics.bytes_sent) == (1, 3)
    assert (metrics.messages_received, metrics.bytes_received) == (1, 5)
    assert metrics.errors == 1
    assert "private-" not in caplog.text


async def test_unregistered_session_helpers_remain_awaitable(monkeypatch, tmp_path):
    manager = SessionManager()
    manager.sessions["SESSION1"] = Session(id="SESSION1")
    monkeypatch.setattr(session_routes, "session_manager", manager)
    assert await session_routes.get_session_messages("SESSION1") == {
        "session_id": "SESSION1",
        "messages": [],
    }
    with pytest.raises(HTTPException) as missing:
        await session_routes.get_session_messages("MISSING")
    assert missing.value.status_code == 404
    manager.sessions["SESSION1"].messages.append(
        SimpleNamespace(id="message-1", audio_base64="aGVsbG8=")
    )
    audio = await session_routes.get_message_audio("message-1")
    assert audio.body == b"hello"
    assert audio.media_type == "audio/wav"
    with pytest.raises(HTTPException) as missing:
        await session_routes.get_message_audio("missing")
    assert missing.value.status_code == 404

    monkeypatch.setattr(
        "services.api_gateway.audio_storage.get_audio_file_path", lambda _name: None
    )
    with pytest.raises(HTTPException) as missing:
        await session_routes.get_original_audio("missing")
    assert missing.value.detail["error_code"] == "AUDIO_NOT_FOUND"
    audio_path = tmp_path / "input_message-1.wav"
    audio_path.touch()
    monkeypatch.setattr(
        "services.api_gateway.audio_storage.get_audio_file_path",
        lambda _name: audio_path,
    )
    original = await session_routes.get_original_audio("message-1")
    assert original.path == str(audio_path)
    assert original.media_type == "audio/wav"


async def test_websocket_query_helpers_remain_awaitable():
    manager = websocket.WebSocketManager(SessionManager())
    assert (
        await websocket.get_websocket_stats(manager) == manager.get_connection_stats()
    )
    assert await websocket.get_session_connections("SESSION1", manager) == {
        "session_id": "SESSION1",
        "connections": [],
        "count": 0,
    }
