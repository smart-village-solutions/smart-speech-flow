"""One conversation, operator and guest, from creation to four delivered messages.

Steps run in order and stop at the first failure. Sockets are held in an exit
stack, so they close whether or not the conversation completes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Tenant
from .evidence import Evidence, session_ref
from .gateway import Gateway, Socket, SocketRejected
from .steps import run_step

ADMIN_LANGUAGE = "de"
ADMIN_TEXTS = ("Guten Tag, wie kann ich Ihnen helfen?", "Bitte nehmen Sie kurz Platz.")
GUEST_TEXTS = {
    "en": ("Hello, I need help with a form.", "Thank you very much."),
    "tr": ("Merhaba, bir form için yardıma ihtiyacım var.", "Çok teşekkür ederim."),
}
MESSAGES_PER_CONVERSATION = 4
ACK_TIMEOUT = 10.0
DELIVERY_TIMEOUT = 30.0

Frame = dict[str, Any]
Outcome = tuple[bool, str]


@dataclass
class Conversation:
    tenant: Tenant
    index: int
    token: str = field(repr=False)
    consent: bool
    session_id: str | None = field(default=None, repr=False)
    message_ids: list[str] = field(default_factory=list)
    completed: bool = False
    terminated: bool = False

    @property
    def label(self) -> str:
        return f"{self.tenant.label}{self.index}"

    def require_session(self) -> str:
        if self.session_id is None:
            raise ValueError("no session")
        return self.session_id


@dataclass
class _Live:
    ticket: str = ""
    admin: Socket | None = None
    guest: Socket | None = None


async def next_frame(
    socket: Socket, wanted: Callable[[Frame], bool], timeout: float
) -> Frame | None:
    """Read frames until one matches, answering heartbeats; None on timeout."""

    async def read() -> Frame:
        while True:
            try:
                frame = json.loads(await socket.recv())
            except ValueError:
                continue
            if frame.get("type") == "heartbeat_ping":
                pong = {"type": "heartbeat_pong", "ping_id": frame.get("ping_id")}
                await socket.send(json.dumps(pong))
            elif wanted(frame):
                return frame

    try:
        return await asyncio.wait_for(read(), timeout)
    except TimeoutError:
        return None


def _is_ack(frame: Frame) -> bool:
    return frame.get("type") == "connection_ack"


async def acknowledged(socket: Socket) -> Outcome:
    frame = await next_frame(socket, _is_ack, ACK_TIMEOUT)
    return frame is not None, "connection_ack" if frame else "no connection_ack"


async def socket_refused(context: AbstractAsyncContextManager[Socket]) -> Outcome:
    """True when the server refuses or closes the socket instead of acknowledging it."""
    try:
        async with context as socket:
            frame = await next_frame(socket, _is_ack, ACK_TIMEOUT)
    except SocketRejected as rejected:
        return True, f"rejected ({rejected})"
    return frame is None, "accepted" if frame else "no acknowledgement"


def _body(response: httpx.Response, status: int) -> dict[str, Any]:
    if response.status_code != status:
        return {}
    body = response.json()
    return body if isinstance(body, dict) else {}


ConversationStep = Callable[[Gateway, Conversation, _Live, AsyncExitStack], Awaitable[Outcome]]


async def _create(
    gateway: Gateway, conversation: Conversation, live: _Live, stack: AsyncExitStack
) -> Outcome:
    response = await gateway.create_session(conversation.token)
    session_id = _body(response, 201).get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return False, f"HTTP {response.status_code}"
    conversation.session_id = session_id
    return True, f"HTTP 201, session {session_ref(session_id)}"


async def _guest_reads(
    gateway: Gateway, conversation: Conversation, live: _Live, stack: AsyncExitStack
) -> Outcome:
    response = await gateway.customer_session(conversation.require_session())
    state = _body(response, 200).get("status")
    return state == "pending", f"HTTP {response.status_code}, status {state}"


async def _ticket(
    gateway: Gateway, conversation: Conversation, live: _Live, stack: AsyncExitStack
) -> Outcome:
    response = await gateway.realtime_ticket(conversation.token, conversation.require_session())
    ticket = _body(response, 200).get("ticket")
    if not isinstance(ticket, str) or not ticket:
        return False, f"HTTP {response.status_code}"
    live.ticket = ticket
    return True, "HTTP 200"


async def _admin_socket(
    gateway: Gateway, conversation: Conversation, live: _Live, stack: AsyncExitStack
) -> Outcome:
    context = gateway.admin_socket(conversation.require_session(), live.ticket)
    live.admin = await stack.enter_async_context(context)
    return await acknowledged(live.admin)


async def _activate(
    gateway: Gateway, conversation: Conversation, live: _Live, stack: AsyncExitStack
) -> Outcome:
    response = await gateway.activate(
        conversation.require_session(), conversation.tenant.guest_language, conversation.consent
    )
    state = _body(response, 200).get("status")
    return state == "active", f"HTTP {response.status_code}, consent {conversation.consent}"


async def _guest_socket(
    gateway: Gateway, conversation: Conversation, live: _Live, stack: AsyncExitStack
) -> Outcome:
    context = gateway.customer_socket(conversation.require_session())
    live.guest = await stack.enter_async_context(context)
    return await acknowledged(live.guest)


def _message(sender: str, index: int) -> ConversationStep:
    async def step(
        gateway: Gateway, conversation: Conversation, live: _Live, stack: AsyncExitStack
    ) -> Outcome:
        session_id = conversation.require_session()
        language = conversation.tenant.guest_language
        if sender == "admin":
            response = await gateway.admin_send(
                conversation.token, session_id, ADMIN_TEXTS[index], ADMIN_LANGUAGE, language
            )
            receiver = live.guest
        else:
            text = GUEST_TEXTS[language][index]
            response = await gateway.customer_send(session_id, text, language, ADMIN_LANGUAGE)
            receiver = live.admin
        message_id = _body(response, 200).get("message_id")
        if not isinstance(message_id, str) or receiver is None:
            return False, f"HTTP {response.status_code}"
        conversation.message_ids.append(message_id)
        frame = await next_frame(
            receiver,
            lambda candidate: candidate.get("type") == "message"
            and candidate.get("message_id") == message_id,
            DELIVERY_TIMEOUT,
        )
        return frame is not None, "delivered" if frame else f"not delivered in {DELIVERY_TIMEOUT} s"

    return step


STEPS: tuple[tuple[str, ConversationStep], ...] = (
    ("create session", _create),
    ("guest reads pending session", _guest_reads),
    ("realtime ticket", _ticket),
    ("admin socket acknowledged", _admin_socket),
    ("guest activates", _activate),
    ("guest socket acknowledged", _guest_socket),
    ("admin message 1 delivered", _message("admin", 0)),
    ("guest message 1 delivered", _message("guest", 0)),
    ("admin message 2 delivered", _message("admin", 1)),
    ("guest message 2 delivered", _message("guest", 1)),
)


async def run_conversation(gateway: Gateway, evidence: Evidence, conversation: Conversation) -> None:
    live = _Live()
    async with AsyncExitStack() as stack:
        for name, step in STEPS:

            async def bound(step: ConversationStep = step) -> Outcome:
                return await step(gateway, conversation, live, stack)

            if not await run_step(evidence, f"{conversation.label} {name}", bound):
                return
        conversation.completed = True
