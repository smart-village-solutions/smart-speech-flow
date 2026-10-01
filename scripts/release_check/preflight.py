"""Refuse to start while any tester account has a live conversation.

Production allows one live conversation per admin: creating a session ends the
same admin's earlier one and nobody else's (#473), and the session history lists
only the requesting admin's sessions (#476). So the check can neither end nor see
a real user's conversation; what it guards is a tester session left live by an
earlier run, which a new run would end mid-way. Each tester sees only their own
sessions, so every tester's history is read, failing closed when one cannot be.
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

        async def step(conversation: Conversation = conversation) -> Outcome:
            response = await gateway.session_history(conversation.token)
            if response.status_code != 200:
                return False, f"HTTP {response.status_code}"
            live = len(response.json().get("active_sessions", []))
            return live == 0, f"{live} live"

        name = f"{conversation.label} has no live conversation"
        idle = await run_step(evidence, name, step) and idle
    return idle
