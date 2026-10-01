"""Tester release check: python -m scripts.release_check (see the runbook)."""

from __future__ import annotations

import asyncio
import functools
import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx

from .config import ConfigError, Operator, Settings, Tenant, load_settings
from .evidence import Evidence
from .gateway import Gateway, websocket_connect
from .isolation import check_colleague_denial, check_isolation
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


def _write_manifest(path: Path, conversations: list[Conversation]) -> None:
    """Session ids for the on-host audio retention check; owner-readable only."""
    entries = [
        {
            "label": conversation.label,
            "consent": conversation.consent,
            "storage": conversation.tenant.storage_mode,
            "session_id": conversation.session_id,
            "message_ids": conversation.message_ids,
        }
        for conversation in conversations
    ]
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as manifest:
        json.dump({"conversations": entries}, manifest, indent=2)


async def _check_denials(
    gateway: Gateway, evidence: Evidence, conversations: list[Conversation]
) -> None:
    """A1 against B1 across tenants, then each tenant's two operators (#476)."""
    pairs = (
        (check_isolation, "isolation", conversations[0], conversations[2]),
        (check_colleague_denial, "A colleague denial", conversations[0], conversations[1]),
        (check_colleague_denial, "B colleague denial", conversations[2], conversations[3]),
    )
    for check, name, first, second in pairs:
        if first.completed and second.completed:
            await check(gateway, evidence, first, second)
        else:
            evidence.record(f"{name} skipped", False, "a conversation did not complete")


async def run(
    settings: Settings,
    gateway: Gateway,
    evidence: Evidence,
    login: Login,
    *,
    manifest: Path | None = None,
) -> bool:
    conversations = await _log_in(settings, evidence, login)
    if conversations is None or not await tenants_idle(gateway, evidence, conversations):
        return False
    try:
        await asyncio.gather(*(run_conversation(gateway, evidence, c) for c in conversations))
        await _check_denials(gateway, evidence, conversations)
        await terminate_and_verify(gateway, evidence, conversations)
    finally:
        await clean_up(gateway, evidence, conversations)
        for conversation in conversations:
            if conversation.session_id:
                evidence.add_secret(conversation.session_id)
        if manifest is not None:
            _write_manifest(manifest, conversations)
    return evidence.passed


async def _run_live(settings: Settings, evidence: Evidence, manifest: Path | None) -> bool:
    async with httpx.AsyncClient(base_url=settings.api_base, timeout=60) as http:
        gateway = Gateway(
            http, websocket_connect, settings.websocket_base, settings.frontend_origin
        )
        login = functools.partial(access_token, settings)
        return await run(settings, gateway, evidence, login, manifest=manifest)


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
    manifest_path = os.environ.get("SSF_RC_MANIFEST", "").strip()
    manifest = Path(manifest_path) if manifest_path else None
    passed = asyncio.run(_run_live(settings, evidence, manifest))
    print(evidence.to_markdown())
    report_path = os.environ.get("SSF_RC_REPORT", "").strip()
    if report_path:
        Path(report_path).write_text(evidence.to_json(), encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
