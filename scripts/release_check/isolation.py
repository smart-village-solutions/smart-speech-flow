"""Cross-tenant denials, run while every session is still live.

A foreign session must look exactly like a missing one: the same neutral 404
on every route. A tenant selector in any request part must be refused.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from .evidence import Evidence
from .gateway import Gateway
from .scenario import ADMIN_LANGUAGE, Conversation, Outcome, acknowledged, socket_refused
from .steps import run_step

NOT_FOUND = "Session not found"

Call = Callable[[], Awaitable[httpx.Response]]


def _not_found(response: httpx.Response) -> Outcome:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return response.status_code == 404 and detail == NOT_FOUND, f"HTTP {response.status_code}"


def _rejected(response: httpx.Response) -> Outcome:
    return response.status_code == 400, f"HTTP {response.status_code}"


def _foreign_calls(gateway: Gateway, actor: Conversation, target: Conversation) -> dict[str, Call]:
    token, session_id = actor.token, target.require_session()
    message_id = target.message_ids[0] if target.message_ids else "missing"
    language = target.tenant.guest_language
    return {
        "status": lambda: gateway.status(token, session_id),
        "messages": lambda: gateway.admin_messages(token, session_id),
        "audio": lambda: gateway.admin_audio(token, session_id, message_id),
        "send message": lambda: gateway.admin_send(
            token, session_id, "Test", ADMIN_LANGUAGE, language
        ),
        "realtime ticket": lambda: gateway.realtime_ticket(token, session_id),
        "polling": lambda: gateway.admin_polling(token, session_id),
        "terminate": lambda: gateway.terminate(token, session_id),
    }


async def _foreign_routes(
    gateway: Gateway, evidence: Evidence, actor: Conversation, target: Conversation
) -> None:
    prefix = f"{actor.label} → {target.label}"
    for name, call in _foreign_calls(gateway, actor, target).items():

        async def step(call: Call = call) -> Outcome:
            return _not_found(await call())

        await run_step(evidence, f"{prefix} {name} is not found", step)


async def _foreign_socket(
    gateway: Gateway, evidence: Evidence, actor: Conversation, target: Conversation
) -> None:
    async def step() -> Outcome:
        response = await gateway.realtime_ticket(actor.token, actor.require_session())
        ticket = response.json().get("ticket") if response.status_code == 200 else None
        if not isinstance(ticket, str) or not ticket:
            return False, f"own ticket HTTP {response.status_code}"
        return await socket_refused(gateway.admin_socket(target.require_session(), ticket))

    label = f"{actor.label} → {target.label} own ticket refused on foreign socket"
    await run_step(evidence, label, step)


async def _target_unaffected(gateway: Gateway, evidence: Evidence, target: Conversation) -> None:
    async def step() -> Outcome:
        response = await gateway.status(target.token, target.require_session())
        state = response.json().get("status") if response.status_code == 200 else None
        return state not in (None, "terminated"), f"HTTP {response.status_code}, status {state}"

    await run_step(evidence, f"{target.label} session unaffected", step)


def _selector_checks(
    gateway: Gateway, actor: Conversation, foreign: Conversation
) -> dict[str, Callable[[], Awaitable[Outcome]]]:
    token, session_id = actor.token, actor.require_session()
    foreign_id = foreign.tenant.directory_id
    selector = {"tenant_id": foreign_id}
    language = actor.tenant.guest_language

    async def query() -> Outcome:
        return _rejected(await gateway.status(token, session_id, params=selector))

    async def header() -> Outcome:
        return _rejected(
            await gateway.status(token, session_id, headers={"X-Tenant-Id": foreign_id})
        )

    async def body() -> Outcome:
        return _rejected(
            await gateway.admin_send(
                token, session_id, "Test", ADMIN_LANGUAGE, language, extra=selector
            )
        )

    async def guest_query() -> Outcome:
        return _rejected(await gateway.customer_session(session_id, params=selector))

    async def guest_socket() -> Outcome:
        context = gateway.customer_socket(session_id, query=f"?tenant_id={foreign_id}")
        return await socket_refused(context)

    async def guest_reconnects() -> Outcome:
        async with gateway.customer_socket(session_id) as socket:
            return await acknowledged(socket)

    return {
        "selector in query is rejected": query,
        "selector in header is rejected": header,
        "selector in body is rejected": body,
        "guest selector in query is rejected": guest_query,
        "guest selector on socket is rejected": guest_socket,
        "guest reconnects without selector": guest_reconnects,
    }


async def check_isolation(
    gateway: Gateway, evidence: Evidence, first: Conversation, second: Conversation
) -> None:
    for actor, target in ((first, second), (second, first)):
        await _foreign_routes(gateway, evidence, actor, target)
        await _foreign_socket(gateway, evidence, actor, target)
        await _target_unaffected(gateway, evidence, target)
    for name, check in _selector_checks(gateway, first, second).items():
        await run_step(evidence, f"{first.label} {name}", check)
