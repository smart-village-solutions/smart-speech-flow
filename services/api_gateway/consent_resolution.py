"""Resolve the Contract V1 consent status from a live mode and a guest answer.

Separate from the route so the mapping can be tested without Studio or FastAPI.
"""

from __future__ import annotations

from typing import Optional

from .consent import ConsentStatus
from .studio_runtime_client import RuntimeConfiguration


def resolve_consent(
    configuration: Optional[RuntimeConfiguration], answer: Optional[bool]
) -> ConsentStatus:
    """Map one live read and one guest answer onto a consent status.

    A `None` configuration means the read failed. That leaves `pending`
    rather than `declined`, so a Studio outage is never recorded as a guest
    refusal.

    Args:
        configuration: The live runtime configuration, or `None` if the read
            failed.
        answer: The guest's answer, where `None` means they never gave one.

    Returns:
        The consent status to store on the session.
    """
    if configuration is None:
        return ConsentStatus.PENDING
    if configuration.conversation_content_storage.mode != "ask":
        return ConsentStatus.POLICY_DISABLED
    if answer is True:
        return ConsentStatus.GRANTED
    return ConsentStatus.DECLINED
