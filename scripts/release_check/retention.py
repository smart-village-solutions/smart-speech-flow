"""Termination, the consent-gated retention check, and unconditional cleanup.

Refused content is removed at termination while the terminal record survives:
a kept session answers its messages and audio, a refused one answers an empty
list and 404s (services/api_gateway/session_manager.py, _settle_refused_content).
"""

from __future__ import annotations

from .evidence import Evidence
from .gateway import Gateway
from .scenario import MESSAGES_PER_CONVERSATION, Conversation, Outcome
from .steps import run_step


def _keeps_content(conversation: Conversation) -> bool:
    return conversation.consent and conversation.tenant.storage_mode == "ask"


async def _terminate(gateway: Gateway, evidence: Evidence, conversation: Conversation) -> bool:
    async def step() -> Outcome:
        response = await gateway.terminate(conversation.token, conversation.require_session())
        conversation.terminated = response.status_code == 200
        return conversation.terminated, f"HTTP {response.status_code}"

    return await run_step(evidence, f"{conversation.label} terminate", step)


async def _verify_messages(
    gateway: Gateway, evidence: Evidence, conversation: Conversation
) -> None:
    expected = MESSAGES_PER_CONVERSATION if _keeps_content(conversation) else 0

    async def step() -> Outcome:
        response = await gateway.admin_messages(conversation.token, conversation.require_session())
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}"
        kept = len(response.json().get("messages", []))
        detail = (
            f"{kept} kept, consent {conversation.consent}, "
            f"storage {conversation.tenant.storage_mode}"
        )
        if expected and not kept:
            detail += "; is the tenant's storage mode really ask?"
        return kept == expected, detail

    await run_step(evidence, f"{conversation.label} keeps {expected} messages", step)


async def _verify_audio(gateway: Gateway, evidence: Evidence, conversation: Conversation) -> None:
    expected = 200 if _keeps_content(conversation) else 404
    for number, message_id in enumerate(conversation.message_ids, start=1):

        async def step(message_id: str = message_id) -> Outcome:
            response = await gateway.admin_audio(
                conversation.token, conversation.require_session(), message_id
            )
            return response.status_code == expected, f"HTTP {response.status_code}"

        await run_step(evidence, f"{conversation.label} audio {number} answers {expected}", step)


async def terminate_and_verify(
    gateway: Gateway, evidence: Evidence, conversations: list[Conversation]
) -> None:
    for conversation in conversations:
        if not conversation.completed:
            continue
        if await _terminate(gateway, evidence, conversation):
            await _verify_messages(gateway, evidence, conversation)
            await _verify_audio(gateway, evidence, conversation)


async def clean_up(gateway: Gateway, evidence: Evidence, conversations: list[Conversation]) -> None:
    for conversation in conversations:
        if conversation.session_id is None or conversation.terminated:
            continue

        async def step(conversation: Conversation = conversation) -> Outcome:
            response = await gateway.terminate(conversation.token, conversation.require_session())
            conversation.terminated = response.status_code == 200
            return conversation.terminated, f"HTTP {response.status_code}"

        await run_step(evidence, f"{conversation.label} cleanup", step)
