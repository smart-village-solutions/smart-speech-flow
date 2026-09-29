"""Thin calls to the SSF gateway, one per route the release check uses.

No assertions live here. Whatever the WebSocket library raises when a server
refuses or closes a socket surfaces as SocketRejected, so the checks and their
test fakes share one failure type.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol
from urllib.parse import quote

import httpx
from websockets.asyncio.client import connect as _open_websocket
from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.typing import Origin

OPEN_TIMEOUT_SECONDS = 10


class SocketRejected(Exception):
    """The server refused the WebSocket or closed it."""


class Socket(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str: ...


Connect = Callable[[str, str], AbstractAsyncContextManager[Socket]]


def _closed(closed: ConnectionClosed) -> SocketRejected:
    return SocketRejected(f"closed {closed.rcvd.code if closed.rcvd else ''}".strip())


class _Adapter:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def send(self, message: str) -> None:
        try:
            await self._connection.send(message)
        except ConnectionClosed as closed:
            raise _closed(closed) from None

    async def recv(self) -> str:
        try:
            frame = await self._connection.recv()
        except ConnectionClosed as closed:
            raise _closed(closed) from None
        return frame if isinstance(frame, str) else frame.decode("utf-8")


@asynccontextmanager
async def websocket_connect(url: str, origin: str) -> AsyncIterator[Socket]:
    try:
        connection = await _open_websocket(
            url, origin=Origin(origin), open_timeout=OPEN_TIMEOUT_SECONDS
        )
    except (InvalidHandshake, OSError, TimeoutError) as error:
        raise SocketRejected(type(error).__name__) from None
    try:
        yield _Adapter(connection)
    finally:
        await connection.close()


class Gateway:
    def __init__(
        self, http: httpx.AsyncClient, connect: Connect, websocket_base: str, origin: str
    ) -> None:
        self._http = http
        self._connect = connect
        self._websocket_base = websocket_base
        self._origin = origin

    @staticmethod
    def _auth(token: str, headers: dict[str, str] | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", **(headers or {})}

    async def create_session(self, token: str) -> httpx.Response:
        return await self._http.post("/api/admin/session/create", headers=self._auth(token))

    async def status(
        self,
        token: str,
        session_id: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self._http.get(
            f"/api/admin/session/{session_id}/status",
            headers=self._auth(token, headers),
            params=params,
        )

    async def admin_messages(self, token: str, session_id: str) -> httpx.Response:
        return await self._http.get(
            f"/api/admin/session/{session_id}/messages", headers=self._auth(token)
        )

    async def admin_audio(self, token: str, session_id: str, message_id: str) -> httpx.Response:
        return await self._http.get(
            f"/api/admin/session/{session_id}/audio/{message_id}/translated.wav",
            headers=self._auth(token),
        )

    async def realtime_ticket(
        self, token: str, session_id: str, transport: str = "websocket"
    ) -> httpx.Response:
        return await self._http.post(
            f"/api/admin/session/{session_id}/realtime-ticket",
            headers=self._auth(token),
            json={"transport": transport},
        )

    async def admin_polling(
        self, token: str, session_id: str, ticket: str = "none"
    ) -> httpx.Response:
        return await self._http.post(
            f"/api/admin/session/{session_id}/polling/activate",
            headers=self._auth(token),
            json={"ticket": ticket},
        )

    async def admin_send(
        self,
        token: str,
        session_id: str,
        text: str,
        source: str,
        target: str,
        *,
        extra: dict[str, str] | None = None,
    ) -> httpx.Response:
        body = {"text": text, "source_lang": source, "target_lang": target, **(extra or {})}
        return await self._http.post(
            f"/api/admin/session/{session_id}/message", headers=self._auth(token), json=body
        )

    async def terminate(self, token: str, session_id: str) -> httpx.Response:
        return await self._http.delete(
            f"/api/admin/session/{session_id}/terminate", headers=self._auth(token)
        )

    async def session_history(self, token: str) -> httpx.Response:
        return await self._http.get("/api/admin/session/history", headers=self._auth(token))

    async def customer_session(
        self, session_id: str, *, params: dict[str, str] | None = None
    ) -> httpx.Response:
        return await self._http.get(f"/api/customer/session/{session_id}", params=params)

    async def activate(self, session_id: str, language: str, consent: bool) -> httpx.Response:
        body = {
            "session_id": session_id,
            "customer_language": language,
            "data_retention_consent": consent,
        }
        return await self._http.post("/api/customer/session/activate", json=body)

    async def customer_send(
        self, session_id: str, text: str, source: str, target: str
    ) -> httpx.Response:
        body = {"text": text, "source_lang": source, "target_lang": target}
        return await self._http.post(f"/api/customer/session/{session_id}/message", json=body)

    def admin_socket(self, session_id: str, ticket: str) -> AbstractAsyncContextManager[Socket]:
        url = f"{self._websocket_base}/ws/admin/{session_id}?ticket={quote(ticket, safe='')}"
        return self._connect(url, self._origin)

    def customer_socket(
        self, session_id: str, *, query: str = ""
    ) -> AbstractAsyncContextManager[Socket]:
        url = f"{self._websocket_base}/ws/customer/{session_id}{query}"
        return self._connect(url, self._origin)
