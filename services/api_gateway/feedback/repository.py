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
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import AbstractAsyncContextManager
from typing import AsyncIterator, Protocol, Sequence
from uuid import UUID

import asyncpg

from .models import AnalyticsState, FeedbackRecord

logger = logging.getLogger(__name__)


# Everything the driver can raise at this boundary, so the route can answer
# 503 rather than 500. asyncpg has no single base class: InterfaceError and
# InternalClientError descend from Exception directly, not from PostgresError.
# Both arrive during an ordinary restart -- InterfaceError is what a pooled
# connection closed by the server raises, and what `acquire()` raises once the
# pool is closing -- so leaving them uncaught would lose submissions on every
# deploy and put an asyncpg error, which carries the bound parameters, into a
# response body.
_DRIVER_FAILURE = (
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
    asyncpg.InternalClientError,
    OSError,
)


class ReconciliationLockUnavailable(RuntimeError):
    """Another replica is already reconciling.

    Not a failure, for the same reason RetentionLockUnavailable is not.
    """


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

    def pass_lock(self, lock_key: int) -> "AbstractAsyncContextManager[None]": ...


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

# The session form, not the xact form, because this one is held across work
# that is not a transaction: the reconciler emits to the collector between the
# claim and the state update. PostgreSQL releases session locks when the
# backend dies, and the unlock below runs even when the pass raises.
_TRY_SESSION_LOCK = "SELECT pg_try_advisory_lock($1)"
_SESSION_UNLOCK = "SELECT pg_advisory_unlock($1)"

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
        except _DRIVER_FAILURE as error:
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

    @asynccontextmanager
    async def pass_lock(self, lock_key: int) -> AsyncIterator[None]:
        """Hold a lock for a whole maintenance pass, not one transaction.

        `claim_pending_analytics` selects; it marks nothing and takes no row
        locks, so with N replicas every pending row was re-emitted N times per
        pass. ClickHouse deduplicates the counts on `event_id`, but `avgState`
        has no distinct-by form, so the rating and NPS averages skewed by a
        factor scaling with replica count whenever a pass found a backlog.

        A transaction-scoped lock cannot serve here -- it would be released at
        the claim's commit, before anything is emitted -- so this holds a
        pooled connection for the pass. That is affordable because emitting is
        an append to the exporter's in-memory batch queue, not network I/O.
        """
        connection = await self._pool.acquire()
        try:
            if not await connection.fetchval(_TRY_SESSION_LOCK, lock_key):
                raise ReconciliationLockUnavailable("another replica holds the pass lock")
            try:
                yield
            finally:
                await connection.fetchval(_SESSION_UNLOCK, lock_key)
        finally:
            await self._pool.release(connection)

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


_SELECT_COLUMNS = """
    feedback_id, tenant_id, session_ref, translation_quality, performance,
    usability, net_promoter_score, improvements_ciphertext, form_version,
    retention_policy_version, consent_snapshot, analytics_event_id,
    analytics_state, created_at, expires_at
"""

# No tenant predicate in either statement, deliberately. The tenant is bound on
# the connection and feedback_tenant_isolation filters the read, so a row from
# another tenant is not merely unselected -- it is not visible to this role at
# all. A WHERE clause here would hide whether the policy still works.
_LIST_RECORDS = f"""
SELECT {_SELECT_COLUMNS}
FROM feedback
ORDER BY created_at DESC, feedback_id
LIMIT $1 OFFSET $2
"""

_FETCH_RECORD = f"""
SELECT {_SELECT_COLUMNS}
FROM feedback
WHERE feedback_id = $1
"""

_AUDIT_ACCESS = """
INSERT INTO feedback_access_audit (
    feedback_id, tenant_id, accessed_by, accessed_at, access_scope
) VALUES ($1, $2, $3, $4, $5)
"""


class PostgresFeedbackReadRepository:
    """The authorised read path's store, as `ssf_feedback_reader`.

    A separate class rather than more methods on PostgresFeedbackRepository
    because it is a separate connection as a separate role. Sharing the class
    would mean one pool whose privileges are the union of both, which is the
    thing migration 003 exists to avoid.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(
        cls, *, dsn: str, password: str | None = None
    ) -> "PostgresFeedbackReadRepository":
        pool = await asyncpg.create_pool(dsn=dsn, password=password or None, min_size=1, max_size=5)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def list_records(
        self, *, tenant_id: str, limit: int, offset: int
    ) -> Sequence[FeedbackRecord]:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await _bind_tenant(connection, tenant_id)
                    rows = await connection.fetch(_LIST_RECORDS, limit, offset)
        except _DRIVER_FAILURE as error:
            raise _read_failed(error) from None
        return [_record_from_row(row) for row in rows]

    async def fetch_record(self, *, feedback_id: UUID, tenant_id: str) -> FeedbackRecord | None:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await _bind_tenant(connection, tenant_id)
                    row = await connection.fetchrow(_FETCH_RECORD, feedback_id)
        except _DRIVER_FAILURE as error:
            raise _read_failed(error) from None
        return _record_from_row(row) if row is not None else None

    async def record_access(
        self, *, feedback_id: UUID, tenant_id: str, accessed_by: str, access_scope: str
    ) -> None:
        try:
            async with self._pool.acquire() as connection:
                await connection.execute(
                    _AUDIT_ACCESS,
                    feedback_id,
                    tenant_id,
                    accessed_by,
                    datetime.now(timezone.utc),
                    access_scope,
                )
        except _DRIVER_FAILURE as error:
            raise _read_failed(error) from None


def _read_failed(error: BaseException) -> FeedbackStorageUnavailable:
    """Type name only, as in store(): a fetched row is in the error's DETAIL."""
    logger.warning("Feedback read failed: %s", type(error).__name__)
    return FeedbackStorageUnavailable("the feedback store could not be read")


def _record_from_row(row: asyncpg.Record) -> FeedbackRecord:
    return FeedbackRecord(
        feedback_id=row["feedback_id"],
        tenant_id=row["tenant_id"],
        session_ref=row["session_ref"],
        translation_quality=row["translation_quality"],
        performance=row["performance"],
        usability=row["usability"],
        net_promoter_score=row["net_promoter_score"],
        improvements_ciphertext=row["improvements_ciphertext"],
        form_version=row["form_version"],
        retention_policy_version=row["retention_policy_version"],
        consent_snapshot=json.loads(row["consent_snapshot"]),
        analytics_event_id=row["analytics_event_id"],
        analytics_state=AnalyticsState(row["analytics_state"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )
