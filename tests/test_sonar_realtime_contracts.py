"""Public transport contracts protected during realtime quality cleanup."""

import asyncio
import inspect
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocket

from services.api_gateway import websocket
from services.api_gateway import websocket_polling_routes as polling
from services.api_gateway.app import app
from services.api_gateway.audio_storage import AudioStore
from services.api_gateway.routes import session as session_routes
from services.api_gateway.legacy_session_manager import LegacySessionManager
from services.api_gateway.session_manager import ClientType, Session, TenantSessionManager
from services.api_gateway.session_store import MemoryTenantSessionStore
from tests.realtime_sessions import websocket_monitor


@pytest.fixture
def polling_client(session_manager):
    session_manager.reset(clear_persistence=True)
    yield TestClient(app)


@pytest.mark.parametrize("role", ["admin", "customer"])
def test_polling_timeout_openapi_and_request_contract(polling_client, gateway_dependencies, role):
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
        stored = gateway_dependencies.polling_store.clients[polling_id]
        gateway_dependencies.polling_store.broadcast(stored.key, {"type": "heartbeat"})
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
    response = polling_client.post(path + "/send", json={"type": "heartbeat", "content": {}})
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    response = polling_client.delete(path)
    assert response.status_code == 200
    assert response.json() == {"status": "disconnected"}
    assert polling_client.get(path + "/status").status_code == 404
    session = gateway_dependencies.session_manager.get_session(stored.key)
    assert (session.admin_connection_count, session.customer_connection_count) == (0, 0)


def test_admin_activation_documents_its_actual_not_found_response(polling_client):
    session_id = polling_client.post("/api/admin/session/create").json()["session_id"]
    response = polling_client.post(
        f"/api/admin/session/{session_id}/polling/activate",
        json={"ticket": "invalid-ticket"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}
    responses = app.openapi()["paths"]["/api/admin/session/{session_id}/polling/activate"]["post"][
        "responses"
    ]
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
    sessions = TenantSessionManager(
        store=MemoryTenantSessionStore(),
        audio_store=AudioStore.from_environment(),
    )
    expired_key = polling.TenantSessionKey("tenant-a", "EXPIRED1")
    live_key = polling.TenantSessionKey("tenant-a", "CURRENT1")
    for key in (expired_key, live_key):
        sessions.store.create(Session(id=key.session_id, tenant_id=key.tenant_id))
    store.activate(expired_key, ClientType.ADMIN)
    store.activate(expired_key, ClientType.CUSTOMER)
    sessions.admin_connected(expired_key)
    sessions.customer_connected(expired_key)
    now[0] = 121.0
    live_client = store.activate(live_key, ClientType.ADMIN)
    manager = websocket.WebSocketManager(sessions, monitor=websocket_monitor())
    loop = asyncio.get_running_loop()
    release_admin = sessions.admin_disconnected

    def release_and_cancel(key):
        release_admin(key)
        loop.call_soon_threadsafe(request_task.cancel)

    monkeypatch.setattr(sessions, "admin_disconnected", release_and_cancel)
    endpoint = next(route.endpoint for route in polling.router.routes if route.name == "admin_poll")
    request_task = asyncio.create_task(
        endpoint(
            session_id=live_key.session_id,
            polling_id=live_client.polling_id,
            key=live_key,
            wait_seconds=60,
            manager=manager,
            polling_store=store,
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


@pytest.fixture
def polling_http_state():
    store = polling.TenantPollingStore()
    sessions = TenantSessionManager(
        store=MemoryTenantSessionStore(),
        audio_store=AudioStore.from_environment(),
    )
    key = polling.TenantSessionKey("tenant-a", "SESSION1")
    sessions.store.create(Session(id=key.session_id, tenant_id=key.tenant_id))
    manager = websocket.WebSocketManager(sessions, monitor=websocket_monitor())
    endpoint_app = FastAPI()
    endpoint_app.include_router(polling.router)
    endpoint_app.dependency_overrides[polling.require_admin_session_key] = lambda: key
    endpoint_app.dependency_overrides[polling.require_customer_session_key] = lambda: key
    endpoint_app.dependency_overrides[polling.get_websocket_manager] = lambda: manager
    endpoint_app.dependency_overrides[polling.get_polling_store] = lambda: store
    return SimpleNamespace(store=store, sessions=sessions, key=key, app=endpoint_app)


async def test_concurrent_http_deletes_release_a_pollers_presence_once(
    monkeypatch, polling_http_state
):
    store, sessions, key = (
        polling_http_state.store,
        polling_http_state.sessions,
        polling_http_state.key,
    )
    removed = store.activate(key, ClientType.ADMIN)
    surviving = store.activate(key, ClientType.ADMIN)
    sessions.admin_connected(key)
    sessions.admin_connected(key)

    # If a handler moves to worker threads, expose both ownership claims before
    # either thread can delete. Event-loop handlers need no scheduling aid.
    event_loop_thread = threading.get_ident()
    claimed = threading.Barrier(2)
    require = store.require

    def require_with_concurrent_claim(*args):
        client = require(*args)
        if threading.get_ident() != event_loop_thread:
            claimed.wait(timeout=5)
        return client

    monkeypatch.setattr(store, "require", require_with_concurrent_claim)
    path = f"/api/admin/session/{key.session_id}/polling/{removed.polling_id}"
    async with AsyncClient(
        transport=ASGITransport(app=polling_http_state.app),
        base_url="http://gateway.test",
    ) as client:
        responses = await asyncio.gather(client.delete(path), client.delete(path))

    assert sorted(response.status_code for response in responses) == [200, 404]
    assert list(store.clients) == [surviving.polling_id]
    assert sessions.get_session(key).admin_connection_count == 1
    assert sessions.get_session(key).admin_connected


async def test_concurrent_http_activation_keeps_role_limit_and_presence(
    monkeypatch, polling_http_state
):
    monkeypatch.setattr(polling, "MAX_POLLING_CLIENTS_PER_ROLE", 1)
    path = f"/api/customer/session/{polling_http_state.key.session_id}/polling/activate"
    async with AsyncClient(
        transport=ASGITransport(app=polling_http_state.app),
        base_url="http://gateway.test",
    ) as client:
        responses = await asyncio.gather(client.post(path), client.post(path))
    assert sorted(response.status_code for response in responses) == [200, 429]
    assert len(polling_http_state.store.clients) == 1
    session = polling_http_state.sessions.get_session(polling_http_state.key)
    assert session.customer_connection_count == 1
    assert session.customer_connected


async def test_terminated_long_poll_does_not_release_a_deleted_client_twice(
    polling_http_state,
):
    store, sessions, key = (
        polling_http_state.store,
        polling_http_state.sessions,
        polling_http_state.key,
    )
    removed = store.activate(key, ClientType.ADMIN)
    surviving = store.activate(key, ClientType.ADMIN)
    sessions.admin_connected(key)
    sessions.admin_connected(key)
    waiting = asyncio.Event()
    resume_poll = asyncio.Event()

    class PausedEvent(asyncio.Event):
        async def wait(self):
            waiting.set()
            result = await super().wait()
            await resume_poll.wait()
            return result

    removed.event = PausedEvent()
    path = f"/api/admin/session/{key.session_id}/polling/{removed.polling_id}"
    async with AsyncClient(
        transport=ASGITransport(app=polling_http_state.app),
        base_url="http://gateway.test",
    ) as client:
        pending = asyncio.create_task(client.get(path, params={"timeout": 60}))
        await asyncio.wait_for(waiting.wait(), 2)
        store.terminate(key, "manual_termination")
        try:
            deleted = await asyncio.wait_for(client.delete(path), 2)
        finally:
            resume_poll.set()
        response = await asyncio.wait_for(pending, 2)
    assert deleted.status_code == 200
    assert response.status_code == 200
    assert response.json() == {
        "messages": [
            {
                "type": "session_terminated",
                "session_id": "SESSION1",
                "reason": "manual_termination",
                "reconnect_allowed": False,
            }
        ],
        "message_count": 1,
    }
    assert list(store.clients) == [surviving.polling_id]
    assert sessions.get_session(key).admin_connection_count == 1


async def test_terminated_polling_client_cannot_send_recover_or_read_status():
    client = polling.PollingClient(
        "poll-1",
        polling.TenantSessionKey("tenant-a", "SESSION1"),
        ClientType.ADMIN,
        terminated=True,
    )
    manager = websocket.WebSocketManager(
        TenantSessionManager(
            store=MemoryTenantSessionStore(),
            audio_store=AudioStore.from_environment(),
        ),
        monitor=websocket_monitor(),
    )
    message = polling.PollingMessage(type="message", content={"text": "private"})
    with pytest.raises(HTTPException) as sent:
        await polling._send(polling.TenantPollingStore(), client, message, manager)
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


def test_customer_polling_principal_cannot_cross_tenants():
    store = polling.TenantPollingStore()
    client = store.activate(polling.TenantSessionKey("tenant-a", "SESSION1"), ClientType.CUSTOMER)
    with pytest.raises(HTTPException) as unauthorized:
        polling.require_customer_polling_key(
            "SESSION1", client.polling_id, {"studio_tenant_id": "tenant-b"}, store
        )
    assert unauthorized.value.status_code == 404
    assert unauthorized.value.detail == "Polling client not found"


async def test_websocket_missing_session_keeps_close_code_and_reason():
    manager = websocket.WebSocketManager(
        TenantSessionManager(
            store=MemoryTenantSessionStore(),
            audio_store=AudioStore.from_environment(),
        ),
        monitor=websocket_monitor(),
    )
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
    sessions = TenantSessionManager(
        store=MemoryTenantSessionStore(),
        audio_store=AudioStore.from_environment(),
    )
    key = polling.TenantSessionKey("tenant-a", "SESSION1")
    # Cached only, so dropping it from the cache makes it unavailable.
    sessions.sessions[key] = Session(id="SESSION1", tenant_id="tenant-a")
    manager = websocket.WebSocketManager(sessions, monitor=websocket_monitor())
    register = sessions.add_websocket_connection

    async def expire_before_registration(*args):
        sessions.sessions.pop(key)
        await register(*args)

    monkeypatch.setattr(sessions, "add_websocket_connection", expire_before_registration)
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
    monitor = websocket_monitor()
    metrics = monitor.connection_established("connection", "SESSION1", "admin")
    monitor.message_sent("connection", "hé", "private-type")
    monitor.message_received("connection", "hello", "private-type")
    monitor.record_error("connection", "private-error", "private-details")
    assert (metrics.messages_sent, metrics.bytes_sent) == (1, 3)
    assert (metrics.messages_received, metrics.bytes_received) == (1, 5)
    assert metrics.errors == 1
    assert "private-" not in caplog.text


async def test_unregistered_session_helpers_remain_awaitable(monkeypatch, tmp_path):
    manager = LegacySessionManager()
    manager.sessions["SESSION1"] = Session(id="SESSION1")
    assert await session_routes.get_session_messages("SESSION1", manager) == {
        "session_id": "SESSION1",
        "messages": [],
    }
    with pytest.raises(HTTPException) as missing:
        await session_routes.get_session_messages("MISSING", manager)
    assert missing.value.status_code == 404
    manager.sessions["SESSION1"].messages.append(
        SimpleNamespace(id="message-1", audio_base64="aGVsbG8=")
    )
    audio = await session_routes.get_message_audio("message-1", manager)
    assert audio.body == b"hello"
    assert audio.media_type == "audio/wav"
    with pytest.raises(HTTPException) as missing:
        await session_routes.get_message_audio("missing", manager)
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
    manager = websocket.WebSocketManager(
        TenantSessionManager(
            store=MemoryTenantSessionStore(),
            audio_store=AudioStore.from_environment(),
        ),
        monitor=websocket_monitor(),
    )
    assert await websocket.get_websocket_stats(manager) == manager.get_connection_stats()
    assert await websocket.get_session_connections("SESSION1", manager) == {
        "session_id": "SESSION1",
        "connections": [],
        "count": 0,
    }
