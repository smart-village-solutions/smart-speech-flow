"""Termination, the consent-gated retention check, and unconditional cleanup.

Refused content is removed at termination while the terminal record survives,
so a kept session still lists its messages and a refused one lists none
(services/api_gateway/session_manager.py, _settle_refused_content). Audio is
never served after termination, whether it was kept or not.
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


async def _verify_no_audio(
    gateway: Gateway, evidence: Evidence, conversation: Conversation
) -> None:
    """An ended conversation serves no audio, kept or not.

    The gateway refuses every audio variant of a terminated session
    (test_terminal_session_denies_all_admin_audio_variants), so whether audio was
    retained is only visible on the server's disk; the runbook covers that.
    """

    async def step() -> Outcome:
        statuses = [
            (
                await gateway.admin_audio(conversation.token, conversation.require_session(), mid)
            ).status_code
            for mid in conversation.message_ids
        ]
        refused = sum(status == 404 for status in statuses)
        return refused == len(statuses) > 0, f"{refused}/{len(statuses)} refused"

    await run_step(evidence, f"{conversation.label} serves no audio after termination", step)


async def terminate_and_verify(
    gateway: Gateway, evidence: Evidence, conversations: list[Conversation]
) -> None:
    for conversation in conversations:
        if not conversation.completed:
            continue
        if await _terminate(gateway, evidence, conversation):
            await _verify_messages(gateway, evidence, conversation)
            await _verify_no_audio(gateway, evidence, conversation)


async def clean_up(gateway: Gateway, evidence: Evidence, conversations: list[Conversation]) -> None:
    for conversation in conversations:
        if conversation.session_id is None or conversation.terminated:
            continue

        async def step(conversation: Conversation = conversation) -> Outcome:
            response = await gateway.terminate(conversation.token, conversation.require_session())
            conversation.terminated = response.status_code == 200
            return conversation.terminated, f"HTTP {response.status_code}"

        await run_step(evidence, f"{conversation.label} cleanup", step)
