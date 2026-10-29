"""The hash-chained audit log of recording mode (spec §11.4).

Each tenant's events form one chain: an event's hash covers its fields and
the previous event's hash, so a removed, reordered or altered row breaks
every hash after it. The application role can only SELECT and INSERT.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from .crypto import tags
from .crypto.encoding import enc

GENESIS: Final[bytes] = bytes(32)
# The actor of what the guest did: guests have no identity of their own.
GUEST_ACTOR: Final[str] = "guest"
# The actor of expiry: the primary site's retention worker (#618).
RETENTION_ACTOR: Final[str] = "retention-worker"


@dataclass(frozen=True)
class AuditEvent:
    """What happened, never what was said: no content and no guest name."""

    tenant_id: str
    actor_sub: str
    event_type: str
    object_ref: str
    at: datetime


@dataclass(frozen=True)
class AuditRow:
    event: AuditEvent
    seq: int
    prev_hash: bytes
    hash: bytes


def canonical_time(at: datetime) -> str:
    if at.tzinfo is None:
        raise ValueError("audit times must be timezone-aware")
    return at.astimezone(timezone.utc).isoformat(timespec="microseconds")


def audit_hash(event: AuditEvent, seq: int, prev_hash: bytes) -> bytes:
    return hashlib.sha256(
        enc(
            tags.AUDIT,
            event.tenant_id,
            seq,
            canonical_time(event.at),
            event.actor_sub,
            event.event_type,
            event.object_ref,
            prev_hash,
        )
    ).digest()


def chain_is_intact(rows: Sequence[AuditRow]) -> bool:
    """Rows of one tenant in `seq` order, starting at 1."""
    previous = GENESIS
    for expected_seq, row in enumerate(rows, start=1):
        if row.seq != expected_seq or row.prev_hash != previous:
            return False
        if audit_hash(row.event, row.seq, row.prev_hash) != row.hash:
            return False
        previous = row.hash
    return True
