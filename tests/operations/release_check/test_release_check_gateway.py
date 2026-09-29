import json
from contextlib import asynccontextmanager

import httpx
import pytest
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from scripts.release_check import gateway as gateway_module
from scripts.release_check.gateway import Gateway, SocketRejected, websocket_connect


def _gateway(handler):
    connected: list[tuple[str, str]] = []

    @asynccontextmanager
    async def connect(url: str, origin: str):
        connected.append((url, origin))
        yield None

    http = httpx.AsyncClient(base_url="https://api.example", transport=httpx.MockTransport(handler))
    return Gateway(http, connect, "wss://api.example", "https://app.example"), connected


async def test_admin_calls_carry_the_bearer_token_and_the_right_route():
    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        return httpx.Response(200, json={})

    gateway, _ = _gateway(handler)
    await gateway.create_session("tok")
    await gateway.status("tok", "S1")
    await gateway.admin_messages("tok", "S1")
    await gateway.admin_audio("tok", "S1", "M1")
    await gateway.realtime_ticket("tok", "S1")
    await gateway.admin_polling("tok", "S1")
    await gateway.terminate("tok", "S1")

    assert seen == [
        ("POST", "/api/admin/session/create", "Bearer tok"),
        ("GET", "/api/admin/session/S1/status", "Bearer tok"),
        ("GET", "/api/admin/session/S1/messages", "Bearer tok"),
        ("GET", "/api/admin/session/S1/audio/M1/translated.wav", "Bearer tok"),
        ("POST", "/api/admin/session/S1/realtime-ticket", "Bearer tok"),
        ("POST", "/api/admin/session/S1/polling/activate", "Bearer tok"),
        ("DELETE", "/api/admin/session/S1/terminate", "Bearer tok"),
    ]


async def test_messages_are_json_and_guest_calls_carry_no_token():
    bodies: list[tuple[str, dict, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        bodies.append((request.url.path, body, request.headers.get("authorization")))
        return httpx.Response(200, json={})

    gateway, _ = _gateway(handler)
    await gateway.admin_send("tok", "S1", "Hallo", "de", "en", extra={"tenant_id": "x"})
    await gateway.activate("S1", "en", True)
    await gateway.customer_send("S1", "Hello", "en", "de")

    assert bodies[0] == (
        "/api/admin/session/S1/message",
        {"text": "Hallo", "source_lang": "de", "target_lang": "en", "tenant_id": "x"},
        "Bearer tok",
    )
    assert bodies[1] == (
        "/api/customer/session/activate",
        {"session_id": "S1", "customer_language": "en", "data_retention_consent": True},
        None,
    )
    assert bodies[2][0] == "/api/customer/session/S1/message"
    assert bodies[2][2] is None


async def test_selectors_reach_the_request_as_given():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(400, json={})

    gateway, _ = _gateway(handler)
    await gateway.status("tok", "S1", params={"tenant_id": "x"}, headers={"X-Tenant-Id": "x"})
    await gateway.customer_session("S1", params={"tenant_id": "x"})

    assert seen[0].url.params["tenant_id"] == "x"
    assert seen[0].headers["x-tenant-id"] == "x"
    assert seen[1].url.params["tenant_id"] == "x"


async def test_sockets_use_the_websocket_base_and_the_frontend_origin():
    gateway, connected = _gateway(lambda request: httpx.Response(200))

    async with gateway.admin_socket("S1", "t/k"):
        pass
    async with gateway.customer_socket("S1", query="?tenant_id=x"):
        pass

    assert connected == [
        ("wss://api.example/ws/admin/S1?ticket=t%2Fk", "https://app.example"),
        ("wss://api.example/ws/customer/S1?tenant_id=x", "https://app.example"),
    ]


async def test_a_refused_handshake_becomes_socket_rejected(monkeypatch):
    async def refuse(*args, **kwargs):
        raise InvalidHandshake("403")

    monkeypatch.setattr(gateway_module, "_open_websocket", refuse)

    with pytest.raises(SocketRejected):
        async with websocket_connect("wss://api.example/ws/customer/S1", "https://app.example"):
            pass


async def test_a_closed_connection_becomes_socket_rejected(monkeypatch):
    class Closed:
        async def recv(self):
            raise ConnectionClosed(None, None)

        async def send(self, message):
            raise ConnectionClosed(None, None)

        async def close(self):
            return None

    async def open_closed(*args, **kwargs):
        return Closed()

    monkeypatch.setattr(gateway_module, "_open_websocket", open_closed)

    async with websocket_connect("wss://api.example/ws/customer/S1", "https://app.example") as socket:
        with pytest.raises(SocketRejected):
            await socket.recv()
        with pytest.raises(SocketRejected):
            await socket.send("{}")
