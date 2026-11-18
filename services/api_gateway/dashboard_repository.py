"""Metadata-only dashboard queries using the recording tenant transaction boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import asyncpg

from .dashboard import DashboardUnavailableError
from .recording.repository import COMMAND_TIMEOUT_SECONDS, DRIVER_FAILURE, bind_tenant
from .recording.verification_sql import openable


class DashboardRecords:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def overview(
        self,
        tenant_id: str,
        sub: str,
        refs: Mapping[str, datetime],
        before: tuple[str, str] | None,
        limit: int,
        supervisor: bool | None,
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        # Only fixed SQL fragments and placeholders are composed; values are bound.
        fields = (
            "c.conversation_id, c.session_ref, c.employee_sub, c.started_at, c.ended_at,"  # nosec B608
            " c.incomplete, ($5::boolean IS NOT NULL AND "
            + openable("$1", "$2", "COALESCE($5,false)")
            + ") AS can_open,"  # nosec B608
            " (SELECT array_agg(v.status) FROM verifications v"
            " WHERE v.conversation_id = c.conversation_id) AS verification_statuses"
        )
        # Known-session start time keeps linked and archive-only pages in the same order.
        source = (
            " FROM conversations c LEFT JOIN unnest($3::text[], $4::timestamptz[])"
            " AS s(session_ref, started_at) ON s.session_ref = c.session_ref"
        )
        permitted = (
            " WHERE c.shredded_at IS NULL AND (c.retention_until > $2 OR c.legal_hold)"
            " AND ($5::boolean IS NOT NULL AND " + openable("$1", "$2", "COALESCE($5,false)") + ")"
        )
        boundary_at = datetime.fromisoformat(before[0]) if before else None
        boundary_id = before[1] if before else None
        query = (
            "SELECT " + fields + source + permitted + " AND ($6::timestamptz IS NULL OR"
            " (COALESCE(s.started_at,c.started_at), 'r-' || c.conversation_id::text)"
            " < ($6, $7)) ORDER BY COALESCE(s.started_at,c.started_at) DESC,"
            " c.conversation_id DESC LIMIT $8"
        )
        # This private marker outlives grant removal, shredding and expiration.
        # It never returns recording IDs/times/results without archive access.
        linked_query = (
            "SELECT c.session_ref, ($4::boolean IS NOT NULL AND "  # nosec B608
            + openable("$1", "$3", "COALESCE($4,false)")
            + ") AS archive_accessible"
            " FROM conversations c WHERE c.employee_sub=$1 AND c.session_ref=ANY($2::text[])"
        )
        try:
            async with self.pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    args = (sub, now, list(refs), list(refs.values()), supervisor)
                    linked = await connection.fetch(linked_query, sub, list(refs), now, supervisor)
                    page = await connection.fetch(query, *args, boundary_at, boundary_id, limit)
        except DRIVER_FAILURE:
            raise DashboardUnavailableError from None
        return [
            {
                "session_ref": row["session_ref"],
                "private_recorded": True,
                "archive_accessible": bool(row["archive_accessible"]),
            }
            for row in linked
        ] + [dict(row) for row in page]

    async def completed_result(
        self, tenant_id: str, sub: str, verification_id: str
    ) -> dict[str, Any] | None:
        # Deliberately select only public decision metadata, never notes, wraps or URLs.
        try:
            async with self.pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    row = await connection.fetchrow(
                        "SELECT verification_id, status, outcome, requested_at, decided_at"
                        " FROM verifications WHERE verification_id = $1::uuid"
                        " AND reviewer_sub = $2 AND status IN ('approved', 'not_approved')",
                        verification_id,
                        sub,
                    )
        except DRIVER_FAILURE:
            raise DashboardUnavailableError from None
        if row is None:
            return None
        return {
            "verification_id": str(row["verification_id"]),
            "status": row["status"],
            "outcome": row["outcome"],
            "requested_at": row["requested_at"].isoformat(),
            "decided_at": row["decided_at"].isoformat(),
            "requested_by_name": None,
        }
