"""Authoritative feedback storage.

The reconciliation query deliberately does not select
`improvements_ciphertext`: the recovery path in #305 must be structurally
unable to carry free text, not merely careful with it.

Errors are reduced to a type name before they reach a log. A PostgreSQL error
carries the entire failing row in its DETAIL field -- verified against
postgres:17.7-alpine -- so logging an asyncpg exception string would publish
the ciphertext, and a future schema change could make that plaintext.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence
from uuid import UUID

import asyncpg

from .models import AnalyticsState, FeedbackRecord

logger = logging.getLogger(__name__)


class RetentionLockUnavailable(RuntimeError):
    """Another replica is already running the retention pass.

    Not a failure: with N replicas, N-1 skip every pass by design. Counting
    this as an error would alert on normal operation.
    """


class FeedbackStorageUnavailable(RuntimeError):
    """The authoritative write could not be committed.

    Carries no detail from the underlying driver: see the module docstring.
    """


@dataclass(frozen=True, slots=True)
class PendingAnalytics:
    """Everything the reconciler needs, and nothing it must not have."""

    feedback_id: UUID
    tenant_id: str
    session_ref: str
    analytics_event_id: UUID
    translation_quality: int
    performance: int
    usability: int
    net_promoter_score: int
    form_version: str
    created_at: datetime


class FeedbackRepository(Protocol):
    async def store(self, record: FeedbackRecord) -> None: ...

    async def mark_analytics_delivered(self, feedback_id: UUID, tenant_id: str) -> None: ...

    async def mark_analytics_state(
        self, feedback_id: UUID, state: AnalyticsState, tenant_id: str
    ) -> None: ...

    async def claim_pending_analytics(self, limit: int) -> Sequence[PendingAnalytics]: ...

    async def delete_expired(
        self, now: datetime, limit: int, lock_key: int | None = None
    ) -> Sequence[UUID]: ...

    async def count_expired(self, now: datetime) -> int: ...


_INSERT = """
INSERT INTO feedback (
    feedback_id, tenant_id, session_ref,
    translation_quality, performance, usability, net_promoter_score,
    improvements_ciphertext, form_version, retention_policy_version,
    consent_snapshot, analytics_event_id, analytics_state,
    created_at, expires_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, $14, $15
)
"""

# No improvements_ciphertext column here, deliberately.
_CLAIM_PENDING = """
SELECT feedback_id, tenant_id, session_ref, analytics_event_id,
       translation_quality, performance, usability, net_promoter_score,
       form_version, created_at
FROM feedback
WHERE analytics_state = 'pending'
ORDER BY created_at
LIMIT $1
"""

_DELETE_EXPIRED = """
DELETE FROM feedback
WHERE feedback_id IN (
    SELECT feedback_id FROM feedback WHERE expires_at <= $1 LIMIT $2
)
RETURNING feedback_id, tenant_id, created_at, expires_at
"""

_COUNT_EXPIRED = "SELECT count(*) FROM feedback WHERE expires_at <= $1"

_TRY_LOCK = "SELECT pg_try_advisory_xact_lock($1)"

_AUDIT_DELETION = """
INSERT INTO feedback_deletion_audit (
    feedback_id, tenant_id, created_at, expires_at, deleted_at, reason
) VALUES ($1, $2, $3, $4, $5, 'retention_expiry')
"""


class PostgresFeedbackRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, *, dsn: str, password: str | None = None) -> "PostgresFeedbackRepository":
        """Take the password beside the DSN rather than inside it.

        asyncpg parses a DSN as a URL, so a password is only safe there if
        every byte of it is URL-safe. Generated ones are not: `/` raises
        before any I/O, and `@` truncates the password and folds the remainder
        into the hostname without raising at all.
        """
        pool = await asyncpg.create_pool(
            dsn=dsn, password=password or None, min_size=1, max_size=10
        )
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def store(self, record: FeedbackRecord) -> None:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await _bind_tenant(connection, record.tenant_id)
                    await connection.execute(
                        _INSERT,
                        record.feedback_id,
                        record.tenant_id,
                        record.session_ref,
                        record.translation_quality,
                        record.performance,
                        record.usability,
                        record.net_promoter_score,
                        record.improvements_ciphertext,
                        record.form_version,
                        record.retention_policy_version,
                        json.dumps(record.consent_snapshot),
                        record.analytics_event_id,
                        record.analytics_state.value,
                        record.created_at,
                        record.expires_at,
                    )
        except (asyncpg.PostgresError, OSError) as error:
            # Type name only. The exception string and its __cause__ chain both
            # carry the bound parameters.
            logger.warning("Feedback write failed: %s", type(error).__name__)
            raise FeedbackStorageUnavailable("the feedback record could not be committed") from None

    async def mark_analytics_delivered(self, feedback_id: UUID, tenant_id: str) -> None:
        await self.mark_analytics_state(feedback_id, AnalyticsState.DELIVERED, tenant_id)

    async def mark_analytics_state(
        self, feedback_id: UUID, state: AnalyticsState, tenant_id: str
    ) -> None:
        """Bind the tenant even though only the id is needed to find the row.

        Under the request-path role the policy filters this UPDATE. Unbound it
        matches nothing, asyncpg reports success, and the row stays `pending`
        forever -- so the reconciler re-emits every submission it ever accepted.
        A silent no-op is the worst available failure here, so the tenant is a
        required argument rather than an optional one.
        """
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await _bind_tenant(connection, tenant_id)
                await connection.execute(
                    "UPDATE feedback SET analytics_state = $2 WHERE feedback_id = $1",
                    feedback_id,
                    state.value,
                )

    async def claim_pending_analytics(self, limit: int) -> Sequence[PendingAnalytics]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(_CLAIM_PENDING, limit)
        return [PendingAnalytics(**dict(row)) for row in rows]

    async def delete_expired(
        self, now: datetime, limit: int, lock_key: int | None = None
    ) -> Sequence[UUID]:
        """Delete past expiry, auditing each row in the same transaction.

        `lock_key` takes a transaction-scoped advisory lock so that only one
        replica deletes per pass.

        The xact form rather than the spec's `pg_try_advisory_lock`. Both are
        safe with the pool as configured -- asyncpg's default reset query ends
        in `pg_advisory_unlock_all()`, and PostgreSQL releases session locks
        when a backend dies -- so this is not a bug fix. It removes a
        dependency: the session form is correct only while that reset query
        stays as it is, and asyncpg documents `get_reset_query` as overridable.
        The xact form is released by PostgreSQL at commit regardless.
        """
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                if lock_key is not None and not await connection.fetchval(_TRY_LOCK, lock_key):
                    raise RetentionLockUnavailable("another replica holds the retention lock")
                rows = await connection.fetch(_DELETE_EXPIRED, now, limit)
                for row in rows:
                    await connection.execute(
                        _AUDIT_DELETION,
                        row["feedback_id"],
                        row["tenant_id"],
                        row["created_at"],
                        row["expires_at"],
                        now,
                    )
        return [row["feedback_id"] for row in rows]

    async def count_expired(self, now: datetime) -> int:
        """Rows still past expiry after a pass.

        A deletion counter alone cannot tell a deployment with nothing to
        delete from a maintenance role that can no longer see anything to
        delete. Both report zero deletions and success forever.
        """
        async with self._pool.acquire() as connection:
            return await connection.fetchval(_COUNT_EXPIRED, now)


async def _bind_tenant(connection: asyncpg.Connection, tenant_id: str) -> None:
    """Set the row-level-security context for this transaction."""
    await connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", tenant_id)
