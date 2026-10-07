"""Resolve the consent status from a live storage policy and a guest answer.

Separate from the route so the mapping can be tested without Studio or FastAPI.
"""

from __future__ import annotations

from typing import Optional

from .consent import ConsentStatus
from .studio_v2 import RuntimePolicy


def resolve_consent(policy: Optional[RuntimePolicy], answer: Optional[bool]) -> ConsentStatus:
    """Map one live read and one guest answer onto a consent status.

    A `None` policy means the read failed. That leaves `pending`
    rather than `declined`, so a Studio outage is never recorded as a guest
    refusal.

    Args:
        policy: The live storage policy, or `None` if the read failed.
        answer: The guest's answer, where `None` means they never gave one.

    Returns:
        The consent status to store on the session.
    """
    if policy is None:
        return ConsentStatus.PENDING
    if policy.mode != "ask":
        return ConsentStatus.POLICY_DISABLED
    if answer is True:
        return ConsentStatus.GRANTED
    return ConsentStatus.DECLINED
