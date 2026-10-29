"""The gateway's side of retention: decisions go in, summaries come out (spec §16.1).

A decision is a row the database applies itself, so even a compromised
gateway can only append decisions, each with its reason and audit event.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

from ..audit import AuditEvent
from ..repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    append_audit,
    bind_tenant,
    storage_unavailable,
)
from .decisions import ConversationSummary, RetentionDecision, RetentionRefusedError
from .metrics import WorkerStatus

_SUMMARY = (
    "SELECT conversation_id, employee_sub, started_at, ended_at, retention_until,"
    " legal_hold, shredded_at FROM conversations"
)


def _summary(row: Any) -> ConversationSummary:
    return ConversationSummary(
        conversation_id=str(row["conversation_id"]),
        employee_sub=row["employee_sub"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        retention_until=row["retention_until"],
        legal_hold=row["legal_hold"],
        shredded_at=row["shredded_at"],
    )


class PostgresRetentionDecisions:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _run(self, tenant_id: str, work: Any) -> Any:
        try:
            async with self._pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    return await work(connection)
        # The trigger's refusals, before the driver failures they subclass.
        except asyncpg.NoDataFoundError:
            raise RetentionRefusedError("no_conversation") from None
        except asyncpg.RaiseError as error:
            raise RetentionRefusedError(error.message) from None
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def decide(self, decision: RetentionDecision, event_type: str) -> ConversationSummary:
        async def work(connection: asyncpg.Connection) -> Any:
            await connection.execute(
                "INSERT INTO retention_decisions (tenant_id, decision_id, conversation_id, at,"
                " actor_sub, kind, retain_until, reason) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                decision.tenant_id,
                decision.decision_id,
                decision.conversation_id,
                decision.at,
                decision.actor_sub,
                decision.kind,
                decision.retain_until,
                decision.reason,
            )
            await append_audit(
                connection,
                AuditEvent(
                    decision.tenant_id,
                    decision.actor_sub,
                    event_type,
                    decision.decision_id,
                    decision.at,
                ),
            )
            return await connection.fetchrow(
                _SUMMARY + " WHERE conversation_id = $1", decision.conversation_id
            )

        return _summary(await self._run(decision.tenant_id, work))

    async def summary(self, tenant_id: str, conversation_id: str) -> ConversationSummary | None:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchrow(
                _SUMMARY + " WHERE conversation_id = $1", conversation_id
            )

        row = await self._run(tenant_id, work)
        return None if row is None else _summary(row)

    async def summaries(
        self, tenant_id: str, *, limit: int, started_before: datetime | None
    ) -> list[ConversationSummary]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(
                _SUMMARY + " WHERE ($1::timestamptz IS NULL OR started_at < $1)"
                " ORDER BY started_at DESC LIMIT $2",
                started_before,
                limit,
            )

        return [_summary(row) for row in await self._run(tenant_id, work)]

    async def record_not_found(
        self, tenant_id: str, actor_sub: str, conversation_ref: str, at: datetime
    ) -> None:
        """Spec §17: unauthorised access is a 404 plus an audit event."""

        async def work(connection: asyncpg.Connection) -> None:
            await append_audit(
                connection,
                AuditEvent(
                    tenant_id, actor_sub, "recording.retention.not_found", conversation_ref, at
                ),
            )

        await self._run(tenant_id, work)

    async def worker_statuses(self) -> list[WorkerStatus]:
        """Each site's last heartbeat; not tenant data, so no tenant is bound."""
        try:
            async with self._pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection:
                rows = await connection.fetch(
                    "SELECT site, beat_at, failing_seconds, halted, hold_mismatches"
                    " FROM retention_worker_status ORDER BY site"
                )
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None
        return [WorkerStatus(**dict(row)) for row in rows]
