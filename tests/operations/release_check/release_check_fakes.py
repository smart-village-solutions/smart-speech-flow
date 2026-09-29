"""An in-memory SSF gateway for the release-check tests, with failure knobs.

A token names its tenant (`token-A1` belongs to tenant A), and a session
belongs to the tenant whose token created it. Frames go to the other party's
socket, as the real gateway broadcasts them.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx

from scripts.release_check.gateway import SocketRejected

SELECTORS = ("tenant_id", "x-tenant-id")
SELECTOR_REFUSAL = {"detail": "Tenant selectors are not accepted in requests"}


def _json(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body)


def _not_found() -> httpx.Response:
    return _json(404, {"detail": "Session not found"})


class FakeSocket:
    def __init__(self) -> None:
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict] = []

    def push(self, frame: dict) -> None:
        self.inbox.put_nowait(json.dumps(frame))

    async def recv(self) -> str:
        return await self.inbox.get()

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


@dataclass
class FakeSession:
    tenant: str
    status: str = "pending"
    consent: bool = False
    messages: list[str] = field(default_factory=list)
    tickets: set[str] = field(default_factory=set)
    admin: FakeSocket | None = None
    guest: FakeSocket | None = None


class FakeGateway:
    def __init__(self, storage: dict[str, str] | None = None) -> None:
        self.storage = storage or {"A": "ask", "B": "ask"}
        self.sessions: dict[str, FakeSession] = {}
        self.terminated: list[str] = []
        self.leak_cross_tenant = False
        self.accept_selectors = False
        self.accept_foreign_ticket = False
        self.drop_delivery = False
        self.keep_refused_content = False
        self.fail_create_for: set[str] = set()
        self.ping_before_ack = False

    @staticmethod
    def _tenant(token: str) -> str:
        return token.removeprefix("token-")[0]

    def _own(self, token: str, session_id: str) -> FakeSession | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None
        if session.tenant != self._tenant(token) and not self.leak_cross_tenant:
            return None
        return session

    def _selected(self, *maps: dict[str, str] | None) -> bool:
        if self.accept_selectors:
            return False
        return any(key.lower() in SELECTORS for mapping in maps if mapping for key in mapping)

    async def create_session(self, token: str) -> httpx.Response:
        if token in self.fail_create_for:
            return _json(500, {"detail": "boom"})
        session_id = f"S{len(self.sessions) + 1}{self._tenant(token)}"
        self.sessions[session_id] = FakeSession(tenant=self._tenant(token))
        return _json(201, {"session_id": session_id})

    async def status(self, token, session_id, *, params=None, headers=None) -> httpx.Response:
        if self._selected(params, headers):
            return _json(400, SELECTOR_REFUSAL)
        session = self._own(token, session_id)
        return _not_found() if session is None else _json(200, {"status": session.status})

    async def admin_messages(self, token, session_id) -> httpx.Response:
        session = self._own(token, session_id)
        if session is None:
            return _not_found()
        return _json(200, {"messages": [{"id": m} for m in session.messages]})

    async def admin_audio(self, token, session_id, message_id) -> httpx.Response:
        session = self._own(token, session_id)
        if session is None:
            return _not_found()
        if message_id not in session.messages:
            return _json(404, {"detail": "Audio file not found"})
        return httpx.Response(200, content=b"RIFF")

    async def realtime_ticket(self, token, session_id) -> httpx.Response:
        session = self._own(token, session_id)
        if session is None:
            return _not_found()
        ticket = f"ticket-{session_id}-{len(session.tickets)}"
        session.tickets.add(ticket)
        return _json(200, {"ticket": ticket, "expires_at": "later"})

    async def admin_polling(self, token, session_id) -> httpx.Response:
        return _not_found() if self._own(token, session_id) is None else _json(200, {})

    async def admin_send(self, token, session_id, text, source, target, *, extra=None):
        if self._selected(extra):
            return _json(400, SELECTOR_REFUSAL)
        session = self._own(token, session_id)
        if session is None:
            return _not_found()
        return self._deliver(session, session_id, session.guest)

    async def terminate(self, token, session_id) -> httpx.Response:
        session = self._own(token, session_id)
        if session is None:
            return _not_found()
        self.terminated.append(session_id)
        keeps = session.consent and self.storage[session.tenant] == "ask"
        if not keeps and not self.keep_refused_content:
            session.messages.clear()
        session.status = "terminated"
        return _json(200, {"status": "terminated"})

    async def customer_session(self, session_id, *, params=None) -> httpx.Response:
        if self._selected(params):
            return _json(400, SELECTOR_REFUSAL)
        session = self.sessions.get(session_id)
        return _not_found() if session is None else _json(200, {"status": session.status})

    async def activate(self, session_id, language, consent) -> httpx.Response:
        session = self.sessions.get(session_id)
        if session is None:
            return _not_found()
        session.status = "active"
        session.consent = consent
        return _json(200, {"status": "active"})

    async def customer_send(self, session_id, text, source, target) -> httpx.Response:
        session = self.sessions[session_id]
        return self._deliver(session, session_id, session.admin)

    def _deliver(self, session: FakeSession, session_id: str, receiver: FakeSocket | None):
        message_id = f"{session_id}-M{len(session.messages) + 1}"
        session.messages.append(message_id)
        if receiver is not None and not self.drop_delivery:
            receiver.push({"type": "message", "message_id": message_id})
        return _json(200, {"status": "success", "message_id": message_id, "audio_url": "/a"})

    def _connected(self) -> FakeSocket:
        socket = FakeSocket()
        if self.ping_before_ack:
            socket.push({"type": "heartbeat_ping", "ping_id": "p1"})
        socket.push({"type": "connection_ack"})
        return socket

    @asynccontextmanager
    async def admin_socket(self, session_id, ticket):
        session = self.sessions.get(session_id)
        owns_ticket = session is not None and ticket in session.tickets
        if session is None or (not owns_ticket and not self.accept_foreign_ticket):
            raise SocketRejected("closed 4404")
        session.admin = self._connected()
        yield session.admin

    @asynccontextmanager
    async def customer_socket(self, session_id, *, query=""):
        if "tenant_id" in query and not self.accept_selectors:
            raise SocketRejected("closed 1008")
        session = self.sessions.get(session_id)
        if session is None:
            raise SocketRejected("closed 4404")
        session.guest = self._connected()
        yield session.guest
