"""Retention decisions: extensions and legal holds by supervisors (spec §16, §16.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

DecisionKind = Literal["extend", "hold_on", "hold_off"]
# Studio's retention maximum: a typo cannot lock ciphertext beyond reach in one step.
MAX_EXTENSION: Final[timedelta] = timedelta(hours=8760)
# Longer than any session lasts: a conversation never ended (a tenant that left,
# a lost end) still expires this long after it started.
UNENDED_GRACE: Final[timedelta] = timedelta(hours=24)


class RetentionRefusedError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RetentionDecision:
    tenant_id: str
    decision_id: str
    conversation_id: str
    at: datetime
    actor_sub: str
    kind: DecisionKind
    retain_until: datetime | None
    reason: str


@dataclass(frozen=True)
class ConversationSummary:
    conversation_id: str
    employee_sub: str
    started_at: datetime
    ended_at: datetime | None
    retention_until: datetime
    legal_hold: bool
    shredded_at: datetime | None

    def public(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "employee_sub": self.employee_sub,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "retention_until": self.retention_until.isoformat(),
            "legal_hold": self.legal_hold,
            "shredded": self.shredded_at is not None,
        }


def check_extension(until: datetime, current: datetime, now: datetime) -> None:
    if until <= current:
        raise RetentionRefusedError("retention_not_extended")
    if until > now + MAX_EXTENSION:
        raise RetentionRefusedError("retention_too_far")
