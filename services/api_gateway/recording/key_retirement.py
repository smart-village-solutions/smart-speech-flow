"""Retiring a user's key: the steps re-enrolment (§9.6) and a leaver (§9.8) share.

The caller holds the user's active key row `FOR UPDATE` and the recovery key row
`FOR SHARE`, in that order, and has checked its own refusals. These steps then
run in the lock order every recovery writer keeps: the open requests, their
conversations, then the writes. The caller appends the audit events last.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from .audit import AuditEvent
from .recovery_requests_model import SYSTEM_ACTOR
from .recovery_requests_sql import CURRENT_CUSTODIANS

# A ceremony still dealing or confirming holds sub-shares sealed to this key, or, for a
# resharing's dealer, relies on the key that opens the dealer's share (§9.7).
IN_CEREMONY = (
    "SELECT EXISTS (SELECT 1 FROM recovery_ceremonies c"
    " WHERE c.status IN ('dealing', 'confirming') AND c.expires_at > $2 AND ("
    "  EXISTS (SELECT 1 FROM ceremony_participants p"
    "   WHERE p.tenant_id = c.tenant_id AND p.ceremony_id = c.ceremony_id AND p.holder_ref = $1)"
    "  OR EXISTS (SELECT 1 FROM ceremony_dealers d"
    "   WHERE d.tenant_id = c.tenant_id AND d.ceremony_id = c.ceremony_id"
    "   AND d.holder_ref = $1)))"
)
# The active recovery key, if the key with this fingerprint is a current custodian's of it.
CUSTODIAN_OF = f"SELECT r.key_id{CURRENT_CUSTODIANS} AND p.holder_ref = $1 AND p.fingerprint = $2"


@dataclass(frozen=True)
class Retired:
    events: list[AuditEvent]
    # The recovery key whose share the retired key opens, if any: its blob was kept.
    custodian_of: Any
    wraps_deleted: int


async def retire_key(
    connection: asyncpg.Connection,
    tenant_id: str,
    sub: str,
    old: Any,
    actor: str,
    now: datetime,
    *,
    left: bool,
) -> Retired:
    """`old` is the locked active row (`key_version`, `fingerprint`)."""
    events = await _close_open_requests(connection, tenant_id, sub, actor, now)
    await _lock_conversations(connection, sub)
    # Sealed to the retired key: nobody can use them any more.
    await connection.execute(
        "DELETE FROM recovery_partials p USING recovery_requests r"
        " WHERE r.tenant_id = p.tenant_id AND r.request_id = p.request_id"
        " AND r.requester_sub = $1",
        sub,
    )
    custodian_of = await connection.fetchval(CUSTODIAN_OF, sub, bytes(old["fingerprint"]))
    await _retire(connection, sub, old["key_version"], custodian_of, now, left)
    deleted = await _delete_user_wraps(connection, tenant_id, sub, actor, now)
    return Retired(events + deleted, custodian_of, len(deleted))


async def _close_open_requests(
    connection: asyncpg.Connection, tenant_id: str, sub: str, actor: str, now: datetime
) -> list[AuditEvent]:
    """Before the wraps go, so a wraps store that committed while we waited is deleted too.

    A request still running is cancelled by `actor`; one that lapsed unseen closes as
    expired, as its next touch would have closed it (§9.5).
    """
    rows = await connection.fetch(
        "SELECT request_id, expires_at <= $2 AS lapsed FROM recovery_requests"
        " WHERE requester_sub = $1 AND status = 'open' ORDER BY request_id FOR UPDATE",
        sub,
        now,
    )
    if not rows:
        return []
    ids = [row["request_id"] for row in rows]
    await connection.execute(
        "UPDATE recovery_requests SET closed_at = $2,"
        " status = CASE WHEN expires_at <= $2 THEN 'expired' ELSE 'cancelled' END"
        " WHERE request_id = ANY($1::uuid[]) AND status = 'open'",
        ids,
        now,
    )
    return [
        AuditEvent(
            tenant_id,
            SYSTEM_ACTOR if row["lapsed"] else actor,
            "recovery.request.expired" if row["lapsed"] else "recovery.request.cancelled",
            str(row["request_id"]),
            now,
        )
        for row in rows
    ]


async def _lock_conversations(connection: asyncpg.Connection, sub: str) -> None:
    """Shared and in order before any delete, as every recovery writer does (§9.6).

    A shred takes the conversation first; without this, the partial and wrap
    deletes could each wait on a row the shred holds, and the shred on one of ours.
    """
    await connection.execute(
        "SELECT 1 FROM conversations c WHERE c.conversation_id IN ("
        " SELECT k.conversation_id FROM key_wraps w JOIN conversation_keys k"
        "  ON k.tenant_id = w.tenant_id AND k.key_id = w.key_id"
        "  WHERE w.recipient_kind = 'user' AND w.recipient_ref = $1"
        " UNION SELECT p.conversation_id FROM recovery_partials p JOIN recovery_requests r"
        "  ON r.tenant_id = p.tenant_id AND r.request_id = p.request_id"
        "  WHERE r.requester_sub = $1)"
        " ORDER BY c.conversation_id FOR SHARE",
        sub,
    )


async def _retire(
    connection: asyncpg.Connection,
    sub: str,
    version: int,
    custodian_of: Any,
    now: datetime,
    left: bool,
) -> None:
    """The blob goes, unless it still opens a custodian share a resharing may need (§9.6)."""
    await connection.execute(
        "UPDATE user_keys SET retired_at = $3,"
        " left_at = CASE WHEN $5 THEN $3::timestamptz END,"
        " encrypted_private = CASE WHEN $4 THEN encrypted_private END"
        " WHERE user_sub = $1 AND key_version = $2",
        sub,
        version,
        now,
        custodian_of is not None,
        left,
    )


async def _delete_user_wraps(
    connection: asyncpg.Connection, tenant_id: str, sub: str, actor: str, now: datetime
) -> list[AuditEvent]:
    """Sealed to the retired key: they can never be opened again."""
    rows = await connection.fetch(
        "DELETE FROM key_wraps WHERE recipient_kind = 'user' AND recipient_ref = $1"
        " RETURNING key_id",
        sub,
    )
    deleted = sorted(str(row["key_id"]) for row in rows)
    return [AuditEvent(tenant_id, actor, "key_wrap.deleted", key_id, now) for key_id in deleted]
