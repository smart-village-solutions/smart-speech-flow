"""Termination, the check that nothing of an ended conversation is kept, and cleanup.

Outside a recording a conversation leaves nothing behind (spec §5.4): the
terminal record lists no messages and no audio is served after termination.
"""

from __future__ import annotations

from .evidence import Evidence
from .gateway import Gateway
from .scenario import Conversation, Outcome
from .steps import run_step

async def _terminate(gateway: Gateway, evidence: Evidence, conversation: Conversation) -> bool:
    async def step() -> Outcome:
        response = await gateway.terminate(conversation.token, conversation.require_session())
        conversation.terminated = response.status_code == 200
        return conversation.terminated, f"HTTP {response.status_code}"

    return await run_step(evidence, f"{conversation.label} terminate", step)


async def _verify_messages(
    gateway: Gateway, evidence: Evidence, conversation: Conversation
) -> None:
    async def step() -> Outcome:
        response = await gateway.admin_messages(conversation.token, conversation.require_session())
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}"
        kept = len(response.json().get("messages", []))
        return kept == 0, f"{kept} kept"

    await run_step(evidence, f"{conversation.label} keeps no messages", step)


async def _verify_no_audio(
    gateway: Gateway, evidence: Evidence, conversation: Conversation
) -> None:
    """An ended conversation serves no audio.

    The gateway refuses every audio variant of a terminated session
    (test_terminal_session_denies_all_admin_audio_variants), so whether a file
    survived is only visible on the server's tmpfs; the runbook covers that.
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
