"""The Contract V1 conversation-content consent states.

This module imports nothing from the gateway so that both the session model
and the persistence policy gate can depend on it without a cycle.
"""

from __future__ import annotations

from enum import Enum


class ConsentStatus(str, Enum):
    """The only consent values Contract V1 permits for a session."""

    PENDING = "pending"
    GRANTED = "granted"
    DECLINED = "declined"
    POLICY_DISABLED = "policy_disabled"

    @classmethod
    def from_stored(cls, value: object) -> ConsentStatus:
        """Restore a persisted value, failing closed on anything unrecognised."""
        try:
            return cls(value)
        except ValueError:
            return cls.PENDING
