"""Tester release check: python -m scripts.release_check (see the runbook)."""

from __future__ import annotations

import asyncio
import functools
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx

from .config import ConfigError, Operator, Settings, Tenant, load_settings
from .evidence import Evidence
from .gateway import Gateway, websocket_connect
from .isolation import check_isolation
from .login import LoginError, access_token
from .preflight import tenants_idle
from .retention import clean_up, terminate_and_verify
from .scenario import ADMIN_TEXTS, GUEST_TEXTS, Conversation, run_conversation

Login = Callable[[Tenant, Operator], Awaitable[str]]


async def _log_in(
    settings: Settings, evidence: Evidence, login: Login
) -> list[Conversation] | None:
    conversations = []
    for tenant in settings.tenants:
        for index, operator in enumerate(tenant.operators, start=1):
            label = f"{tenant.label}{index}"
            try:
                token = await login(tenant, operator)
            except (LoginError, httpx.HTTPError, ValueError, KeyError) as error:
                evidence.record(f"{label} login", False, str(error) or type(error).__name__)
                return None
            evidence.add_secret(token)
            evidence.record(f"{label} login", True)
            conversations.append(
                Conversation(tenant=tenant, index=index, token=token, consent=index == 1)
            )
    return conversations


async def run(settings: Settings, gateway: Gateway, evidence: Evidence, login: Login) -> bool:
    conversations = await _log_in(settings, evidence, login)
    if conversations is None or not await tenants_idle(gateway, evidence, conversations):
        return False
    try:
        await asyncio.gather(*(run_conversation(gateway, evidence, c) for c in conversations))
        first, second = conversations[0], conversations[2]
        if first.completed and second.completed:
            await check_isolation(gateway, evidence, first, second)
        else:
            evidence.record("isolation skipped", False, "a conversation did not complete")
        await terminate_and_verify(gateway, evidence, conversations)
    finally:
        await clean_up(gateway, evidence, conversations)
        for conversation in conversations:
            if conversation.session_id:
                evidence.add_secret(conversation.session_id)
    return evidence.passed


async def _run_live(settings: Settings, evidence: Evidence) -> bool:
    async with httpx.AsyncClient(base_url=settings.api_base, timeout=60) as http:
        gateway = Gateway(
            http, websocket_connect, settings.websocket_base, settings.frontend_origin
        )
        return await run(settings, gateway, evidence, functools.partial(access_token, settings))


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as error:
        print(f"release check: {error}", file=sys.stderr)
        return 2
    evidence = Evidence()
    guest_texts = (text for texts in GUEST_TEXTS.values() for text in texts)
    for secret in (*settings.secrets(), *ADMIN_TEXTS, *guest_texts):
        evidence.add_secret(secret)
    passed = asyncio.run(_run_live(settings, evidence))
    print(evidence.to_markdown())
    report_path = os.environ.get("SSF_RC_REPORT", "").strip()
    if report_path:
        Path(report_path).write_text(evidence.to_json(), encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
