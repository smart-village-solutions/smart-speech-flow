"""Re-enrolment's swap (spec §9.6; migration 007), run only by the mailed link's confirm (§9.9).

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
from .key_retirement import CUSTODIAN_OF, IN_CEREMONY, retire_key
from .recovery_requests_model import Refused
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

    async def impact(self, tenant_id: str, sub: str) -> ReenrolmentImpact:
        async def work(connection: asyncpg.Connection) -> ReenrolmentImpact:
            current = await connection.fetchval(
                "SELECT fingerprint FROM user_keys WHERE user_sub = $1 AND retired_at IS NULL",
                sub,
            )
            custodian = current is not None and (
                await connection.fetchval(CUSTODIAN_OF, sub, bytes(current)) is not None
            )
            # Only for the custodian re-enrolling here; admins read it in the ceremony status.
            shares = await connection.fetchrow(USABLE_SHARES) if custodian else None
            if shares is None:
                return ReenrolmentImpact(custodian, None, None)
            usable = int(shares["usable"]) - 1  # the caller's own share goes stale
            return ReenrolmentImpact(custodian, int(shares["k"]), usable)

        return await self._run(tenant_id, work)


async def lock_active_key(connection: asyncpg.Connection, sub: str) -> Any:
    """The swap's first locks: the caller's active key row, then the active recovery key."""
    old = await connection.fetchrow(
        "SELECT key_version, fingerprint, email FROM user_keys"
        " WHERE user_sub = $1 AND retired_at IS NULL FOR UPDATE",
        sub,
    )
    # Before the requests: a resharing's activation takes this row, then them (§9.7).
    await connection.execute("SELECT 1 FROM recovery_keys WHERE status = 'active' FOR SHARE")
    return old


async def complete_swap(
    connection: asyncpg.Connection,
    record: UserKeyRecord,
    old: Any,
    now: datetime,
    events: list[AuditEvent],
) -> None:
    """Retires `old` for `record` once the refusals passed; `events` go first in the audit."""
    retired = await retire_key(
        connection, record.tenant_id, record.user_sub, old, record.user_sub, now, left=False
    )
    events = events + retired.events
    await insert_user_key(connection, record)
    if retired.custodian_of is not None:
        events.append(_event(record, "recovery.share.stale", str(retired.custodian_of), now))
    events.append(_event(record, "key_reenrolled", f"user-key:{record.key_version}", now))
    await append_audits(connection, events)


def _event(record: UserKeyRecord, event_type: str, ref: str, now: datetime) -> AuditEvent:
    return AuditEvent(record.tenant_id, record.user_sub, event_type, ref, now)


async def reenrolment_refusal(
    connection: asyncpg.Connection, old: Any, sub: str, replaces_version: int, now: datetime
) -> Refused | None:
    if old is None:
        # A concurrent swap retired the row this one waited on: its key is newer now. A
        # leaver's newest key is the retired one, so their browser goes on to enrol (§9.8).
        newest = await connection.fetchrow(
            "SELECT key_version, left_at FROM user_keys WHERE user_sub = $1"
            " ORDER BY key_version DESC LIMIT 1",
            sub,
        )
        changed = (
            newest is not None
            and newest["left_at"] is None
            and newest["key_version"] >= replaces_version
        )
        return Refused("key_changed" if changed else "key_not_enrolled")
    if old["key_version"] != replaces_version:
        return Refused("key_changed")
    if await connection.fetchval(IN_CEREMONY, sub, now):
        return Refused("ceremony_in_progress")
    return None
