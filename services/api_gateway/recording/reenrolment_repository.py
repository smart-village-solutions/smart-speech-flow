"""Re-enrolment's swap (spec §9.6; migration 007).

One transaction, in the lock order every recovery writer keeps: the caller's
active key row, then their open requests, then the writes, then the audit.
A wraps store or a filing holds the key row shared, so it either finishes
before the swap (and its wraps are deleted by it) or sees the key retired.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

import asyncpg

from .audit import AuditEvent
from .recovery_requests_model import SYSTEM_ACTOR, Refused
from .recovery_requests_sql import USABLE_SHARES
from .repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    UserKeyRecord,
    append_audits,
    bind_tenant,
    insert_user_key,
    storage_unavailable,
)

T = TypeVar("T")

# A ceremony still dealing or confirming holds sub-shares sealed to this key.
_IN_CEREMONY = (
    "SELECT EXISTS (SELECT 1 FROM recovery_ceremonies c JOIN ceremony_participants p"
    " ON p.tenant_id = c.tenant_id AND p.ceremony_id = c.ceremony_id"
    " WHERE c.status IN ('dealing', 'confirming') AND c.expires_at > $2 AND p.holder_ref = $1)"
)
# The active recovery key, if the caller is its custodian by this very key.
_CUSTODIAN_OF = (
    "SELECT r.key_id FROM recovery_keys r JOIN ceremony_participants p"
    " ON p.tenant_id = r.tenant_id AND p.ceremony_id = r.key_id"
    " WHERE r.status = 'active' AND p.kind = 'custodian' AND p.holder_ref = $1"
    " AND p.fingerprint = $2"
)


@dataclass(frozen=True)
class ReenrolmentImpact:
    """What the warning before a re-enrolment says (§9.6)."""

    custodian: bool
    k: int | None
    usable_after: int | None


class PostgresKeyReenrolment:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _run(self, tenant_id: str, work: Callable[[asyncpg.Connection], Awaitable[T]]) -> T:
        try:
            async with (
                self._pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection,
                connection.transaction(),
            ):
                await bind_tenant(connection, tenant_id)
                return await work(connection)
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def swap(
        self, record: UserKeyRecord, replaces_version: int, now: datetime
    ) -> Refused | None:
        """Retires `replaces_version` for `record`, or refuses and changes nothing."""

        async def work(connection: asyncpg.Connection) -> Refused | None:
            old = await connection.fetchrow(
                "SELECT key_version, fingerprint FROM user_keys"
                " WHERE user_sub = $1 AND retired_at IS NULL FOR UPDATE",
                record.user_sub,
            )
            refused = await _refusal(connection, old, record.user_sub, replaces_version, now)
            if refused is not None:
                return refused
            events = await _close_open_requests(connection, record, now)
            await _lock_conversations(connection, record.user_sub)
            # Sealed to the retired key: nobody can use them any more.
            await connection.execute(
                "DELETE FROM recovery_partials p USING recovery_requests r"
                " WHERE r.tenant_id = p.tenant_id AND r.request_id = p.request_id"
                " AND r.requester_sub = $1",
                record.user_sub,
            )
            custodian_of = await connection.fetchval(
                _CUSTODIAN_OF, record.user_sub, bytes(old["fingerprint"])
            )
            await _retire(connection, record.user_sub, replaces_version, custodian_of, now)
            events += await _delete_user_wraps(connection, record, now)
            await insert_user_key(connection, record)
            if custodian_of is not None:
                events.append(_event(record, "recovery.share.stale", str(custodian_of), now))
            events.append(_event(record, "key_reenrolled", f"user-key:{record.key_version}", now))
            await append_audits(connection, events)
            return None

        return await self._run(record.tenant_id, work)

    async def check(
        self, tenant_id: str, sub: str, replaces_version: int, now: datetime
    ) -> Refused | None:
        """The swap's refusals, read before a confirmation is asked for; the swap checks again."""

        async def work(connection: asyncpg.Connection) -> Refused | None:
            old = await connection.fetchrow(
                "SELECT key_version, fingerprint FROM user_keys"
                " WHERE user_sub = $1 AND retired_at IS NULL",
                sub,
            )
            return await _refusal(connection, old, sub, replaces_version, now)

        return await self._run(tenant_id, work)

    async def impact(self, tenant_id: str, sub: str) -> ReenrolmentImpact:
        async def work(connection: asyncpg.Connection) -> ReenrolmentImpact:
            current = await connection.fetchval(
                "SELECT fingerprint FROM user_keys WHERE user_sub = $1 AND retired_at IS NULL",
                sub,
            )
            custodian = current is not None and (
                await connection.fetchval(_CUSTODIAN_OF, sub, bytes(current)) is not None
            )
            # Only for the custodian re-enrolling here; admins read it in the ceremony status.
            shares = await connection.fetchrow(USABLE_SHARES) if custodian else None
            if shares is None:
                return ReenrolmentImpact(custodian, None, None)
            usable = int(shares["usable"]) - 1  # the caller's own share goes stale
            return ReenrolmentImpact(custodian, int(shares["k"]), usable)

        return await self._run(tenant_id, work)


def _event(record: UserKeyRecord, event_type: str, ref: str, now: datetime) -> AuditEvent:
    return AuditEvent(record.tenant_id, record.user_sub, event_type, ref, now)


async def _refusal(
    connection: asyncpg.Connection, old: Any, sub: str, replaces_version: int, now: datetime
) -> Refused | None:
    if old is None:
        # A concurrent swap retired the row this one waited on: its key is newer now.
        newer = await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM user_keys WHERE user_sub = $1 AND key_version >= $2)",
            sub,
            replaces_version,
        )
        return Refused("key_changed" if newer else "key_not_enrolled")
    if old["key_version"] != replaces_version:
        return Refused("key_changed")
    if await connection.fetchval(_IN_CEREMONY, sub, now):
        return Refused("ceremony_in_progress")
    return None


async def _close_open_requests(
    connection: asyncpg.Connection, record: UserKeyRecord, now: datetime
) -> list[AuditEvent]:
    """Before the wraps go, so a wraps store that committed while we waited is deleted too.

    A request still running is cancelled by the caller; one that lapsed unseen closes as
    expired, as its next touch would have closed it (§9.5).
    """
    rows = await connection.fetch(
        "SELECT request_id, expires_at <= $2 AS lapsed FROM recovery_requests"
        " WHERE requester_sub = $1 AND status = 'open' ORDER BY request_id FOR UPDATE",
        record.user_sub,
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
            record.tenant_id,
            SYSTEM_ACTOR if row["lapsed"] else record.user_sub,
            "recovery.request.expired" if row["lapsed"] else "recovery.request.cancelled",
            str(row["request_id"]),
            now,
        )
        for row in rows
    ]


async def _lock_conversations(connection: asyncpg.Connection, sub: str) -> None:
    """Shared and in order before any delete, as every recovery writer does (§9.6).

    A shred takes the conversation first; without this, the swap's partial and wrap
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
) -> None:
    """The blob goes, unless it still opens a custodian share a resharing may need (§9.6)."""
    await connection.execute(
        "UPDATE user_keys SET retired_at = $3,"
        " encrypted_private = CASE WHEN $4 THEN encrypted_private END"
        " WHERE user_sub = $1 AND key_version = $2",
        sub,
        version,
        now,
        custodian_of is not None,
    )


async def _delete_user_wraps(
    connection: asyncpg.Connection, record: UserKeyRecord, now: datetime
) -> list[AuditEvent]:
    """Sealed to the retired key: they can never be opened again."""
    rows = await connection.fetch(
        "DELETE FROM key_wraps WHERE recipient_kind = 'user' AND recipient_ref = $1"
        " RETURNING key_id",
        record.user_sub,
    )
    deleted = sorted(str(row["key_id"]) for row in rows)
    return [_event(record, "key_wrap.deleted", key_id, now) for key_id in deleted]
