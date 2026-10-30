"""A leaver's key retirement in Postgres (spec §9.8; migration 009).

The re-enrolment swap without the new key, in its lock order: the user's active
key row, the recovery key row, then `retire_key`'s requests, conversations and
writes, and one audit batch last.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

import asyncpg

from .audit import AuditEvent
from .key_retirement import IN_CEREMONY, retire_key
from .leavers import KeyHolder, MarkedLeaver
from .recovery_requests_model import Refused
from .recovery_requests_sql import CURRENT_CUSTODIANS
from .repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    append_audits,
    bind_tenant,
    storage_unavailable,
)

T = TypeVar("T")

_ACTIVITY = "c.employee_sub = u.user_sub AND c.shredded_at IS NULL"
_LISTED = f"SELECT p.holder_ref, p.display_name{CURRENT_CUSTODIANS}"
_HOLDERS = (
    "SELECT u.user_sub, u.key_version, u.fingerprint, u.created_at, a.conversations,"
    " a.last_conversation_at, h.holder_ref IS NOT NULL AS custodian, h.display_name"
    f" FROM user_keys u LEFT JOIN ({_LISTED}) h ON h.holder_ref = u.user_sub"
    " CROSS JOIN LATERAL (SELECT count(*) AS conversations,"
    f" max(c.started_at) AS last_conversation_at FROM conversations c WHERE {_ACTIVITY}) a"
    " WHERE u.retired_at IS NULL ORDER BY u.user_sub"
)
# Its browser is the paper device: the ceremony cannot finish without the starter.
_STARTED = (
    "SELECT EXISTS (SELECT 1 FROM recovery_ceremonies WHERE started_by = $1"
    " AND status IN ('dealing', 'confirming') AND expires_at > $2)"
)


class PostgresLeavers:
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

    async def holders(self, tenant_id: str) -> list[KeyHolder]:
        async def work(connection: asyncpg.Connection) -> list[Any]:
            return list(await connection.fetch(_HOLDERS))

        return [
            KeyHolder(
                sub=row["user_sub"],
                key_version=row["key_version"],
                fingerprint=bytes(row["fingerprint"]),
                enrolled_at=row["created_at"],
                conversations=int(row["conversations"]),
                last_conversation_at=row["last_conversation_at"],
                custodian=row["custodian"],
                display_name=row["display_name"],
            )
            for row in await self._run(tenant_id, work)
        ]

    async def holder_subs(self, tenant_id: str) -> frozenset[str]:
        async def work(connection: asyncpg.Connection) -> list[Any]:
            return list(
                await connection.fetch("SELECT user_sub FROM user_keys WHERE retired_at IS NULL")
            )

        return frozenset(row["user_sub"] for row in await self._run(tenant_id, work))

    async def mark(
        self, tenant_id: str, sub: str, key_version: int, actor: str, now: datetime
    ) -> Refused | MarkedLeaver:
        """Retires `key_version` of `sub` without a successor, or refuses and changes nothing."""

        async def work(connection: asyncpg.Connection) -> Refused | MarkedLeaver:
            old = await connection.fetchrow(
                "SELECT key_version, fingerprint FROM user_keys"
                " WHERE user_sub = $1 AND retired_at IS NULL FOR UPDATE",
                sub,
            )
            # Before the requests: a resharing's activation takes this row, then them (§9.7).
            await connection.execute(
                "SELECT 1 FROM recovery_keys WHERE status = 'active' FOR SHARE"
            )
            refused = await _refusal(connection, old, sub, key_version, now)
            if refused is not None:
                return refused
            retired = await retire_key(connection, tenant_id, sub, old, actor, now, left=True)
            custodian = await connection.fetchval(
                f"SELECT EXISTS ({_LISTED} AND p.holder_ref = $1)", sub
            )
            events = retired.events
            if retired.custodian_of is not None:
                ref = str(retired.custodian_of)
                events.append(AuditEvent(tenant_id, actor, "recovery.share.stale", ref, now))
            events.append(
                AuditEvent(tenant_id, actor, "user_left", f"user-key:{sub}:{key_version}", now)
            )
            await append_audits(connection, events)
            return MarkedLeaver(sub, key_version, custodian, retired.wraps_deleted)

        return await self._run(tenant_id, work)


async def _refusal(
    connection: asyncpg.Connection, old: Any, sub: str, key_version: int, now: datetime
) -> Refused | None:
    if old is None:
        # A swap may have retired the row this one waited on; its newer key is not the one shown.
        newest = await connection.fetchrow(
            "SELECT key_version, left_at FROM user_keys WHERE user_sub = $1"
            " ORDER BY key_version DESC LIMIT 1",
            sub,
        )
        if newest is None:
            return Refused("key_not_enrolled")
        if newest["left_at"] is not None:
            return Refused("already_left")
        return Refused(
            "key_changed" if newest["key_version"] >= key_version else "key_not_enrolled"
        )
    if old["key_version"] != key_version:
        return Refused("key_changed")
    if await connection.fetchval(IN_CEREMONY, sub, now) or await connection.fetchval(
        _STARTED, sub, now
    ):
        return Refused("ceremony_in_progress")
    return None
