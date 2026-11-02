"""Postgres side of the nightly revocation check (spec §10.7; migration 011)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, TypeVar

import asyncpg

from .audit import AuditEvent
from .repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    append_audits,
    bind_tenant,
    storage_unavailable,
)
from .verification_repository import RELEASE
from .verification_sql import LIVE_REASON, OPEN_STATUSES
from .verification_writes import close_records

T = TypeVar("T")

_CLAIM = (
    "INSERT INTO revocation_runs (tenant_id, run_date, started_at) VALUES ($1, $2, $3)"
    " ON CONFLICT (tenant_id, run_date) DO UPDATE SET started_at = EXCLUDED.started_at"
    " WHERE revocation_runs.finished_at IS NULL AND revocation_runs.started_at < $4"
    " RETURNING run_date"
)
_FINISH = (
    "UPDATE revocation_runs SET finished_at = $3, outcome = $4"
    " WHERE tenant_id = $1 AND run_date = $2"
)
# The last success; a tenant that never succeeded is owed one since its first claimed run.
_OWED_SINCE = (
    "SELECT COALESCE(max(finished_at) FILTER (WHERE outcome = 'done'), min(started_at))"
    " FROM revocation_runs"
)
_HOLDERS = "SELECT DISTINCT user_sub FROM user_keys WHERE retired_at IS NULL"
# Assignments on a conversation that is shredded or past its date are left to lapse:
# their rows go at expiry, and they count towards no bound (review of #675).
_ASSIGNMENTS = (
    "SELECT v.verification_id, v.conversation_id, v.reviewer_sub, v.directory_read_at"
    " FROM verifications v JOIN conversations c"
    "  ON c.tenant_id = v.tenant_id AND c.conversation_id = v.conversation_id"
    f" WHERE v.status IN {OPEN_STATUSES} AND c.shredded_at IS NULL"
    " AND (c.retention_until > $1 OR c.legal_hold) ORDER BY v.verification_id"
)
_USER_WRAPS = (
    " FROM key_wraps w JOIN conversation_keys k ON k.tenant_id = w.tenant_id AND k.key_id = w.key_id"
    " JOIN conversations c ON c.tenant_id = k.tenant_id AND c.conversation_id = k.conversation_id"
    " WHERE w.recipient_kind = 'user' AND w.recipient_ref <> c.employee_sub"
)
_RECOVERED = (
    "SELECT DISTINCT c.conversation_id, w.recipient_ref"
    + _USER_WRAPS
    + " AND w.creator_ref = w.recipient_ref ORDER BY c.conversation_id, w.recipient_ref"
)
_ORPHANED = (
    "SELECT DISTINCT c.conversation_id" + _USER_WRAPS + f" AND NOT {LIVE_REASON}"
    " ORDER BY c.conversation_id"
)
_LOCK_CONVERSATION = "SELECT 1 FROM conversations WHERE conversation_id = $1 FOR SHARE"
_LOCK_RECORDS = (
    "SELECT verification_id, reviewer_sub FROM verifications WHERE verification_id = ANY($1::uuid[])"
    f" AND status IN {OPEN_STATUSES} ORDER BY verification_id FOR UPDATE"
)
_UNSUPERVISED = (
    "DELETE FROM key_wraps w USING conversation_keys k, conversations c"
    " WHERE k.tenant_id = w.tenant_id AND k.key_id = w.key_id"
    " AND c.tenant_id = k.tenant_id AND c.conversation_id = k.conversation_id"
    " AND c.conversation_id = $1 AND w.recipient_kind = 'user' AND w.recipient_ref = ANY($2::text[])"
    " AND w.creator_ref = w.recipient_ref AND w.recipient_ref <> c.employee_sub"
    " RETURNING w.key_id, w.recipient_ref"
)
_NON_EMPLOYEE_RECIPIENTS = (
    "SELECT DISTINCT w.recipient_ref" + _USER_WRAPS + " AND c.conversation_id = $1"
)


@dataclass(frozen=True)
class Assignment:
    verification_id: str
    conversation_id: str
    reviewer_sub: str
    directory_read_at: datetime


@dataclass(frozen=True)
class Grants:
    """Everyone a conversation's user wraps reach beyond its employee."""

    assignments: tuple[Assignment, ...]
    recovered: tuple[tuple[str, str], ...]  # (conversation, supervisor)
    orphaned: tuple[str, ...]  # conversations holding a wrap no reason keeps


class PostgresRevocations:
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

    async def claim(
        self, tenant_id: str, day: date, now: datetime, reclaim_after: timedelta
    ) -> bool:
        """One run per tenant and day; a run that never finished may be claimed again."""

        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchval(_CLAIM, tenant_id, day, now, now - reclaim_after)

        return await self._run(tenant_id, work) is not None

    async def finish(self, tenant_id: str, day: date, outcome: str, now: datetime) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(_FINISH, tenant_id, day, now, outcome)

        await self._run(tenant_id, work)

    async def owed_since(self, tenant_id: str) -> datetime | None:
        """The last success, else the first claimed run; None for a tenant never checked."""

        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchval(_OWED_SINCE)

        result: datetime | None = await self._run(tenant_id, work)
        return result

    async def key_holders(self, tenant_id: str) -> frozenset[str]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(_HOLDERS)

        return frozenset(row["user_sub"] for row in await self._run(tenant_id, work))

    async def grants(self, tenant_id: str, now: datetime) -> Grants:
        async def work(connection: asyncpg.Connection) -> Grants:
            assignments = await connection.fetch(_ASSIGNMENTS, now)
            recovered = await connection.fetch(_RECOVERED)
            orphaned = await connection.fetch(_ORPHANED)
            return Grants(
                tuple(
                    Assignment(
                        str(row["verification_id"]),
                        str(row["conversation_id"]),
                        row["reviewer_sub"],
                        row["directory_read_at"],
                    )
                    for row in assignments
                ),
                tuple((str(row["conversation_id"]), row["recipient_ref"]) for row in recovered),
                tuple(str(row["conversation_id"]) for row in orphaned),
            )

        return await self._run(tenant_id, work)

    async def revoke(
        self,
        tenant_id: str,
        conversation_id: str,
        withdraw: Sequence[str],
        unsupervised: Sequence[str],
        actor: str,
        now: datetime,
    ) -> int:
        """One conversation, in the recording lock order; returns the wraps deleted."""

        async def work(connection: asyncpg.Connection) -> int:
            conversation = uuid.UUID(conversation_id)
            await connection.execute(_LOCK_CONVERSATION, conversation)
            records = await connection.fetch(_LOCK_RECORDS, [uuid.UUID(vid) for vid in withdraw])
            ids = [row["verification_id"] for row in records]
            events = [
                AuditEvent(
                    tenant_id,
                    actor,
                    "recording.verification.withdrawn.permission_revoked",
                    f"{row['verification_id']}:{row['reviewer_sub']}",
                    now,
                )
                for row in records
            ]
            await close_records(connection, ids, "withdrawn", "permission_revoked", now)
            deleted = [
                (str(row["key_id"]), row["recipient_ref"])
                for row in await connection.fetch(_UNSUPERVISED, conversation, list(unsupervised))
            ]
            for row in await connection.fetch(_NON_EMPLOYEE_RECIPIENTS, conversation):
                released = await connection.fetch(RELEASE, conversation, row["recipient_ref"])
                deleted += [(str(item["key_id"]), row["recipient_ref"]) for item in released]
            events += [
                AuditEvent(tenant_id, actor, "key_wrap.revoked", f"{key_id}:{sub}", now)
                for key_id, sub in sorted(deleted)
            ]
            await append_audits(connection, events)
            return len(deleted)

        return await self._run(tenant_id, work)

    async def skipped(
        self, tenant_id: str, guard: str, day: date, now: datetime, actor: str
    ) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await append_audits(
                connection,
                [
                    AuditEvent(
                        tenant_id, actor, f"recording.revocation.skipped.{guard}", str(day), now
                    )
                ],
            )

        await self._run(tenant_id, work)
