"""Refuse to start while either tenant has a live conversation.

Production allows one live conversation per tenant: creating a session ends the
tenant's others (services/api_gateway/session_manager.py, unless
SSF_ALLOW_PARALLEL_SESSIONS is set). A run against a busy tenant would end a
real user's conversation, so the check reads each tenant's live sessions first
and fails closed when it cannot.
"""

from __future__ import annotations

from .evidence import Evidence
from .gateway import Gateway
from .scenario import Conversation, Outcome
from .steps import run_step


async def tenants_idle(
    gateway: Gateway, evidence: Evidence, conversations: list[Conversation]
) -> bool:
    idle = True
    for conversation in conversations:
        if conversation.index != 1:
            continue

        async def step(conversation: Conversation = conversation) -> Outcome:
            response = await gateway.session_history(conversation.token)
            if response.status_code != 200:
                return False, f"HTTP {response.status_code}"
            live = len(response.json().get("active_sessions", []))
            return live == 0, f"{live} live"

        name = f"{conversation.tenant.label} has no live conversations"
        idle = await run_step(evidence, name, step) and idle
    return idle
