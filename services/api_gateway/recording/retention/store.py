"""The retention worker's access to `ssf_recording`, as its site's role (spec §16.1).

Every tenant-owned query binds `ssf.tenant_id` first, as the gateway's do, so
row-level security decides what is visible: the replica's role sees and
writes only its own site's rows. `next_attempt_at` is moved only if it still
holds the value the row was read with, so a decision that arrives while a row
is worked on keeps the row due.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Self

import asyncpg

from ..audit import RETENTION_ACTOR, AuditEvent
from ..repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    append_audit,
    bind_tenant,
    storage_unavailable,
)
from ..storage.archive import object_key
from .decisions import UNENDED_GRACE, RetentionRefusedError
from .restore_guard import AuditMark
from .settings import Site, WorkerSettings

BACKOFF_CEILING: Final[timedelta] = timedelta(hours=6)
# A bucket locks each version for the retention rounded up to whole days plus
# one, from its upload, which can come up to a session's length after the
# first yes. A lock further past its conversation's date than this points to
# an extension the database no longer knows (a restore).
LOCK_MARGIN: Final[timedelta] = timedelta(days=3)
# Every table that names a conversation, in the order its rows go (spec §16.1).
EXPIRY_DELETION_ORDER: Final[tuple[str, ...]] = (
    "version_locks",
    "site_clearances",
    "chain_stamps",
    "stored_objects",
    "chain_entries",
    "key_wraps",
    "conversation_keys",
    "recording_windows",
    "conversations",
)
# Kept after expiry beside the audit events (concept §11).
KEPT_AFTER_EXPIRY: Final[tuple[str, ...]] = ("retention_decisions",)
# stored_objects and key_wraps name no conversation: they go through their parents.
_DELETE: Final[dict[str, str]] = {
    "version_locks": "DELETE FROM version_locks WHERE conversation_id = $1",
    "site_clearances": "DELETE FROM site_clearances WHERE conversation_id = $1",
    "chain_stamps": "DELETE FROM chain_stamps WHERE conversation_id = $1",
    "stored_objects": "DELETE FROM stored_objects WHERE entry_id IN"
    " (SELECT entry_id FROM chain_entries WHERE conversation_id = $1)",
    "chain_entries": "DELETE FROM chain_entries WHERE conversation_id = $1",
    "key_wraps": "DELETE FROM key_wraps WHERE key_id IN"
    " (SELECT key_id FROM conversation_keys WHERE conversation_id = $1)",
    "conversation_keys": "DELETE FROM conversation_keys WHERE conversation_id = $1",
    "recording_windows": "DELETE FROM recording_windows WHERE conversation_id = $1",
    "conversations": "DELETE FROM conversations WHERE conversation_id = $1",
}
# A version still held on either site keeps its conversation readable: shred
# only once every site has lifted every hold.
_HELD_VERSION: Final[str] = (
    "SELECT EXISTS (SELECT 1 FROM version_locks"
    " WHERE conversation_id = $1 AND held AND deleted_at IS NULL)"
)
_DUE_EXPIRY: Final[str] = (
    "SELECT c.conversation_id FROM conversations c"
    " WHERE c.retention_until <= $1 AND NOT c.legal_hold AND c.shredded_at IS NULL"
    " AND (c.ended_at IS NOT NULL OR c.started_at < $2)"
    " AND NOT EXISTS (SELECT 1 FROM version_locks v"
    "  WHERE v.conversation_id = c.conversation_id AND v.held AND v.deleted_at IS NULL)"
    " ORDER BY c.retention_until"
)
_HOLD_MISMATCHES: Final[str] = (
    "SELECT count(*) FROM version_locks v JOIN conversations c"
    " ON c.tenant_id = v.tenant_id AND c.conversation_id = v.conversation_id"
    " WHERE v.site = $1 AND v.deleted_at IS NULL AND v.held AND NOT c.legal_hold"
    " AND NOT EXISTS (SELECT 1 FROM retention_decisions d"
    "  WHERE d.conversation_id = v.conversation_id AND d.kind = 'hold_off'"
    "  AND d.at > v.held_since)"
)
# The oldest step this site owes: a failing row since it first failed, a row
# still due since it fell due.
_OVERDUE_SINCE: Final[str] = (
    "SELECT min(coalesce(failing_since, next_attempt_at)) FROM version_locks"
    " WHERE site = $1 AND deleted_at IS NULL"
    " AND (failing_since IS NOT NULL OR next_attempt_at <= $2)"
)
_RESTORE_CONFLICTS: Final[str] = (
    "SELECT v.conversation_id, CASE"
    "  WHEN v.checked_at IS NULL THEN 'not_yet_read'"
    "  WHEN v.held AND NOT c.legal_hold THEN 'held_without_hold'"
    "  ELSE 'locked_beyond_date' END AS reason, v.locked_until"
    " FROM version_locks v JOIN conversations c"
    " ON c.tenant_id = v.tenant_id AND c.conversation_id = v.conversation_id"
    " WHERE v.site = $1 AND v.deleted_at IS NULL AND c.shredded_at IS NULL AND ("
    "  v.checked_at IS NULL OR (v.held AND NOT c.legal_hold)"
    "  OR v.locked_until > c.retention_until + $2::interval)"
    " ORDER BY v.conversation_id"
)
_CLEARABLE: Final[str] = (
    "SELECT c.conversation_id FROM conversations c WHERE c.shredded_at IS NOT NULL"
    " AND NOT EXISTS (SELECT 1 FROM site_clearances s"
    "  WHERE s.conversation_id = c.conversation_id AND s.site = $1)"
    " AND NOT EXISTS (SELECT 1 FROM version_locks v"
    "  WHERE v.conversation_id = c.conversation_id AND v.site = $1 AND v.deleted_at IS NULL)"
    " ORDER BY c.shredded_at"
)
_DELETABLE: Final[str] = (
    "SELECT c.conversation_id FROM conversations c WHERE c.shredded_at IS NOT NULL"
    " AND (SELECT count(*) FROM site_clearances s WHERE s.conversation_id = c.conversation_id)"
    " = 2 ORDER BY c.shredded_at"
)

_DISCOVER: Final[str] = (
    "INSERT INTO version_locks (tenant_id, conversation_id, entry_id, object_type, site,"
    " version_id, next_attempt_at)"
    " SELECT s.tenant_id, e.conversation_id, s.entry_id, s.object_type, $1, s.version_id, $2"
    " FROM stored_objects s JOIN chain_entries e"
    " ON e.tenant_id = s.tenant_id AND e.entry_id = s.entry_id"
    " WHERE NOT EXISTS (SELECT 1 FROM version_locks v WHERE v.tenant_id = s.tenant_id"
    "  AND v.entry_id = s.entry_id AND v.object_type = s.object_type AND v.site = $1)"
    " ON CONFLICT DO NOTHING"
)
_DUE: Final[str] = (
    "SELECT v.tenant_id, v.conversation_id, v.entry_id, v.object_type, v.version_id,"
    " v.checked_at, v.locked_until, v.held, v.held_since, v.attempts, v.next_attempt_at,"
    " c.retention_until, c.legal_hold, c.shredded_at,"
    " (SELECT max(d.at) FROM retention_decisions d WHERE d.conversation_id = v.conversation_id"
    "  AND d.kind = 'hold_on') AS hold_on_at,"
    " (SELECT max(d.at) FROM retention_decisions d WHERE d.conversation_id = v.conversation_id"
    "  AND d.kind = 'hold_off') AS hold_off_at"
    " FROM version_locks v JOIN conversations c"
    " ON c.tenant_id = v.tenant_id AND c.conversation_id = v.conversation_id"
    " WHERE v.site = $1 AND v.deleted_at IS NULL AND v.next_attempt_at <= $2"
    " ORDER BY v.next_attempt_at LIMIT $3"
)
_ROW: Final[str] = "entry_id = $1 AND object_type = $2 AND site = $3 AND version_id = $4"
_RECORD: Final[str] = (
    "UPDATE version_locks SET checked_at = $5, locked_until = $6, held = $7, held_since = $8,"
    " deleted_at = $9, attempts = 0, failing_since = NULL,"
    " next_attempt_at = CASE WHEN next_attempt_at = $10 THEN $11 ELSE next_attempt_at END"
    " WHERE " + _ROW
)
# The exponent is capped so the interval cannot overflow before least() applies.
# What the failed step had already done to the version is kept ($8 onwards),
# unless the version was never read ($8 null).
_FAILED: Final[str] = (
    "UPDATE version_locks SET attempts = attempts + 1,"
    " failing_since = coalesce(failing_since, $5),"
    " next_attempt_at = CASE WHEN next_attempt_at = $6"
    "  THEN $5 + least(interval '60 seconds' * power(2, least(attempts, 20)), $7)"
    "  ELSE next_attempt_at END,"
    " checked_at = coalesce($8::timestamptz, checked_at),"
    " locked_until = CASE WHEN $8::timestamptz IS NULL THEN locked_until"
    "  ELSE $9::timestamptz END,"
    " held = CASE WHEN $8::timestamptz IS NULL THEN held ELSE $10::boolean END,"
    " held_since = CASE WHEN $8::timestamptz IS NULL THEN held_since"
    "  ELSE $11::timestamptz END"
    " WHERE " + _ROW
)


@dataclass(frozen=True)
class DueVersion:
    tenant_id: str
    conversation_id: str
    entry_id: str
    object_type: str
    version_id: str
    key: str
    checked_at: datetime | None
    locked_until: datetime | None
    held: bool
    held_since: datetime | None
    attempts: int
    # As read: a decision that resets it meanwhile must not be overwritten.
    next_attempt_at: datetime
    retention_until: datetime
    legal_hold: bool
    shredded_at: datetime | None
    hold_on_at: datetime | None
    hold_off_at: datetime | None


@dataclass(frozen=True)
class LockState:
    checked_at: datetime
    locked_until: datetime | None
    held: bool
    held_since: datetime | None
    deleted_at: datetime | None


def _due(row: Any) -> DueVersion:
    conversation_id, entry_id = str(row["conversation_id"]), str(row["entry_id"])
    return DueVersion(
        tenant_id=row["tenant_id"],
        conversation_id=conversation_id,
        entry_id=entry_id,
        object_type=row["object_type"],
        version_id=row["version_id"],
        key=object_key(conversation_id, entry_id, row["object_type"]),
        checked_at=row["checked_at"],
        locked_until=row["locked_until"],
        held=row["held"],
        held_since=row["held_since"],
        attempts=row["attempts"],
        next_attempt_at=row["next_attempt_at"],
        retention_until=row["retention_until"],
        legal_hold=row["legal_hold"],
        shredded_at=row["shredded_at"],
        hold_on_at=row["hold_on_at"],
        hold_off_at=row["hold_off_at"],
    )


class PostgresRetentionStore:
    def __init__(self, pool: asyncpg.Pool, site: Site) -> None:
        self._pool = pool
        self.site = site

    @classmethod
    async def connect(cls, settings: WorkerSettings) -> Self:
        try:
            pool = await asyncpg.create_pool(
                dsn=settings.database_url,
                password=settings.database_password,
                min_size=1,
                max_size=2,
                command_timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None
        return cls(pool, settings.site)

    @property
    def pool(self) -> asyncpg.Pool:
        return self._pool

    async def close(self) -> None:
        await self._pool.close()

    async def _run(self, tenant_id: str | None, work: Any) -> Any:
        """One transaction, bound to the tenant unless the work is tenant-free."""
        try:
            async with self._pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection:
                async with connection.transaction():
                    if tenant_id is not None:
                        await bind_tenant(connection, tenant_id)
                    return await work(connection)
        # The triggers' refusals, before the driver failures they subclass.
        except asyncpg.NoDataFoundError:
            raise RetentionRefusedError("no_conversation") from None
        except asyncpg.RaiseError as error:
            raise RetentionRefusedError(error.message) from None
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def tenants(self) -> list[str]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch("SELECT tenant FROM recording_tenants() AS tenant")

        return [row["tenant"] for row in await self._run(None, work)]

    async def audit_mark(self, tenant_id: str) -> AuditMark | None:
        """The tenant's last audit event; None while it has none."""

        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchrow(
                "SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1"
            )

        row = await self._run(tenant_id, work)
        return None if row is None else AuditMark(row["seq"], bytes(row["hash"]).hex())

    async def audit_hash_at(self, tenant_id: str, seq: int) -> str | None:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchval("SELECT hash FROM audit_events WHERE seq = $1", seq)

        found = await self._run(tenant_id, work)
        return None if found is None else bytes(found).hex()

    async def recheck_all(self, tenant_id: str, now: datetime) -> None:
        """After a restore: read every version's real lock and hold from the store again."""

        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "UPDATE version_locks SET checked_at = NULL, next_attempt_at = $2"
                " WHERE site = $1 AND deleted_at IS NULL",
                self.site,
                now,
            )

        await self._run(tenant_id, work)

    async def hold_mismatches(self, tenant_id: str) -> int:
        """Versions held here although no hold applies and no later hold_off lifts them."""

        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchval(_HOLD_MISMATCHES, self.site)

        return int(await self._run(tenant_id, work))

    async def restore_conflicts(self, tenant_id: str) -> list[tuple[str, str, datetime | None]]:
        """What a restore may have lost here: (conversation, reason, the version's lock)."""

        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(_RESTORE_CONFLICTS, self.site, LOCK_MARGIN)

        return [
            (str(row["conversation_id"]), row["reason"], row["locked_until"])
            for row in await self._run(tenant_id, work)
        ]

    async def discover(self, tenant_id: str, now: datetime) -> int:
        """A row per stored version this site has not tracked yet; the count added."""

        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.execute(_DISCOVER, self.site, now)

        status: str = await self._run(tenant_id, work)
        return int(status.rsplit(" ", 1)[-1])

    async def due_versions(
        self, tenant_id: str, now: datetime, limit: int = 200
    ) -> list[DueVersion]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(_DUE, self.site, now, limit)

        return [_due(row) for row in await self._run(tenant_id, work)]

    def _row(self, row: DueVersion) -> tuple[str, str, str, str]:
        return row.entry_id, row.object_type, self.site, row.version_id

    async def record(self, row: DueVersion, state: LockState, revisit_at: datetime) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                _RECORD,
                *self._row(row),
                state.checked_at,
                state.locked_until,
                state.held,
                state.held_since,
                state.deleted_at,
                row.next_attempt_at,
                revisit_at,
            )

        await self._run(row.tenant_id, work)

    async def record_failure(
        self, row: DueVersion, now: datetime, state: LockState | None = None
    ) -> None:
        """A failed step, keeping `state`: what the steps before it changed in the store."""
        known: tuple[Any, ...] = (None, None, None, None)
        if state is not None:
            known = (state.checked_at, state.locked_until, state.held, state.held_since)

        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                _FAILED, *self._row(row), now, row.next_attempt_at, BACKOFF_CEILING, *known
            )

        await self._run(row.tenant_id, work)

    async def overdue_since(self, tenant_id: str, now: datetime) -> datetime | None:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchval(_OVERDUE_SINCE, self.site, now)

        result: datetime | None = await self._run(tenant_id, work)
        return result

    async def beat(
        self, now: datetime, failing_seconds: float, halted: bool, hold_mismatches: int
    ) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "INSERT INTO retention_worker_status (site, beat_at, failing_seconds, halted,"
                " hold_mismatches) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (site) DO UPDATE SET"
                " beat_at = EXCLUDED.beat_at, failing_seconds = EXCLUDED.failing_seconds,"
                " halted = EXCLUDED.halted, hold_mismatches = EXCLUDED.hold_mismatches",
                self.site,
                now,
                failing_seconds,
                halted,
                hold_mismatches,
            )

        await self._run(None, work)

    def _primary_only(self) -> None:
        if self.site != "primary":
            raise RetentionRefusedError("primary_only")

    async def _conversation_ids(self, tenant_id: str, sql: str, *args: Any) -> list[str]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(sql, *args)

        return [str(row["conversation_id"]) for row in await self._run(tenant_id, work)]

    async def due_expiries(self, tenant_id: str, now: datetime) -> list[str]:
        self._primary_only()
        return await self._conversation_ids(tenant_id, _DUE_EXPIRY, now, now - UNENDED_GRACE)

    async def shred(self, tenant_id: str, conversation_id: str, now: datetime, actor: str) -> bool:
        """False, changing nothing, when the conversation is no longer due (a hold arrived)."""
        self._primary_only()

        async def work(connection: asyncpg.Connection) -> bool:
            return await _shred_in(
                connection, tenant_id, conversation_id, now, actor, require_due=True
            )

        return bool(await self._run(tenant_id, work))

    async def clearable(self, tenant_id: str) -> list[str]:
        return await self._conversation_ids(tenant_id, _CLEARABLE, self.site)

    async def record_clearance(self, tenant_id: str, conversation_id: str, now: datetime) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "INSERT INTO site_clearances (tenant_id, conversation_id, site, cleared_at)"
                " VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                tenant_id,
                conversation_id,
                self.site,
                now,
            )

        await self._run(tenant_id, work)

    async def deletable(self, tenant_id: str) -> list[str]:
        self._primary_only()
        return await self._conversation_ids(tenant_id, _DELETABLE)

    async def delete_rows(self, tenant_id: str, conversation_id: str, now: datetime) -> bool:
        """Every row of a shredded conversation both sites have cleared; audited before and after."""
        self._primary_only()

        async def work(connection: asyncpg.Connection) -> bool:
            ready = await connection.fetchval(
                "SELECT shredded_at IS NOT NULL AND (SELECT count(*) FROM site_clearances"
                " WHERE conversation_id = $1) = 2 FROM conversations"
                " WHERE conversation_id = $1 FOR UPDATE",
                conversation_id,
            )
            if not ready:
                return False
            await _audit(connection, tenant_id, "recording.versions_deleted", conversation_id, now)
            for table in EXPIRY_DELETION_ORDER:
                await connection.execute(_DELETE[table], conversation_id)
            await _audit(connection, tenant_id, "recording.expired", conversation_id, now)
            return True

        return bool(await self._run(tenant_id, work))

    async def known_conversations(self, tenant_id: str) -> dict[str, bool]:
        """Each conversation that still has rows, and whether it is shredded."""

        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(
                "SELECT conversation_id, shredded_at IS NOT NULL AS shredded FROM conversations"
            )

        rows = await self._run(tenant_id, work)
        return {str(row["conversation_id"]): row["shredded"] for row in rows}

    async def erase(
        self, tenant_id: str, conversation_id: str, now: datetime, operator: str, reason: str
    ) -> str:
        """An operator's early erasure: the decision, then the shred, in one transaction."""
        self._primary_only()
        decision_id = str(uuid.uuid4())
        actor = f"operator:{operator}"

        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "INSERT INTO retention_decisions (tenant_id, decision_id, conversation_id, at,"
                " actor_sub, kind, reason) VALUES ($1, $2, $3, $4, $5, 'erase', $6)",
                tenant_id,
                decision_id,
                conversation_id,
                now,
                actor,
                reason,
            )
            await append_audit(
                connection,
                AuditEvent(tenant_id, actor, "recording.retention.erased", decision_id, now),
            )
            # The trigger checked hold, end and shred under the row lock it still holds.
            if not await _shred_in(
                connection, tenant_id, conversation_id, now, actor, require_due=False
            ):
                raise RetentionRefusedError("version_held")

        await self._run(tenant_id, work)
        return decision_id


def _is_due(row: Any, now: datetime) -> bool:
    ended = row["ended_at"] is not None or row["started_at"] < now - UNENDED_GRACE
    return (
        row["retention_until"] <= now
        and not row["legal_hold"]
        and row["shredded_at"] is None
        and ended
    )


async def _audit(
    connection: asyncpg.Connection, tenant_id: str, event_type: str, ref: str, at: datetime
) -> None:
    await append_audit(connection, AuditEvent(tenant_id, RETENTION_ACTOR, event_type, ref, at))


async def _shred_in(
    connection: asyncpg.Connection,
    tenant_id: str,
    conversation_id: str,
    now: datetime,
    actor: str,
    *,
    require_due: bool,
) -> bool:
    """Crypto-shredding: the key wraps go, so no stored ciphertext can be read again."""
    row = await connection.fetchrow(
        "SELECT retention_until, legal_hold, shredded_at, ended_at, started_at"
        " FROM conversations WHERE conversation_id = $1 FOR UPDATE",
        conversation_id,
    )
    if row is None or (require_due and not _is_due(row, now)):
        return False
    if await connection.fetchval(_HELD_VERSION, conversation_id):
        return False
    await connection.execute(_DELETE["key_wraps"], conversation_id)
    await connection.execute(
        "UPDATE conversations SET shredded_at = $2 WHERE conversation_id = $1",
        conversation_id,
        now,
    )
    # Both sites' workers look at its versions again now.
    await connection.execute(
        "UPDATE version_locks SET next_attempt_at = $2"
        " WHERE conversation_id = $1 AND deleted_at IS NULL",
        conversation_id,
        now,
    )
    await append_audit(
        connection, AuditEvent(tenant_id, actor, "recording.shredded", conversation_id, now)
    )
    return True
