"""Pending re-enrolments waiting for their mailed link (spec §9.9; migration 010).

Lock order, as in every key writer: the user's active key row, then the pending
row, then the audit. The sweep runs in its own transaction, before the caller's,
and only one runs per tenant at a time.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

import asyncpg

from .audit import AuditEvent
from .key_retirement import reenrolment_ref
from .recovery_requests_model import Refused
from .reenrolment_repository import complete_swap, lock_active_key, reenrolment_refusal
from .repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    UserKeyRecord,
    append_audits,
    bind_tenant,
    storage_unavailable,
)

T = TypeVar("T")

_PENDING = "user_sub, key_version, fingerprint, requested_at, expires_at"
# The app may not UPDATE pending rows, so it cannot lock them FOR UPDATE: deleting one
# is the lock, and a refusal that must keep it rolls the deletion back.
_TAKE = f"DELETE FROM user_key_reenrolments WHERE token_hash = $1 RETURNING {_PENDING}"


class _KeepPendingError(Exception):
    """Rolls a confirm back, so its pending row survives a refusal the user can wait out."""

    def __init__(self, refused: Refused) -> None:
        super().__init__(refused.code)
        self.refused = refused


@dataclass(frozen=True)
class PendingKey:
    """What the keys screen shows while a link is out."""

    fingerprint: bytes
    expires_at: datetime


@dataclass(frozen=True)
class LinkDetails:
    """What the link's page shows before its owner confirms or declines."""

    fingerprint: bytes
    requested_at: datetime
    expires_at: datetime


def _event(tenant_id: str, row: Any, event_type: str, now: datetime) -> AuditEvent:
    ref = reenrolment_ref(row["user_sub"], row["key_version"])
    return AuditEvent(tenant_id, row["user_sub"], f"key_reenrolment.{event_type}", ref, now)


async def _lapsed(
    connection: asyncpg.Connection, tenant_id: str, taken: Any, now: datetime
) -> Refused | None:
    """For a row already taken: `link_invalid` if there was none, `link_expired` if it lapsed."""
    if taken is None:
        return Refused("link_invalid")
    if taken["expires_at"] > now:
        return None
    await append_audits(connection, [_event(tenant_id, taken, "expired", now)])
    return Refused("link_expired")


class PostgresKeyConfirmations:
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

    async def hold(
        self,
        record: UserKeyRecord,
        replaces_version: int,
        token_hash: bytes,
        expires_at: datetime,
    ) -> Refused | str:
        """Keeps `record` aside for its link; returns the pinned address it goes to."""
        now = record.created_at

        async def work(connection: asyncpg.Connection) -> Refused | str:
            old = await lock_active_key(connection, record.user_sub)
            refused = await reenrolment_refusal(
                connection, old, record.user_sub, replaces_version, now
            )
            if refused is not None:
                return refused
            if old["email"] is None:
                return Refused("email_not_verified")
            events = []
            earlier = await connection.fetchrow(
                "DELETE FROM user_key_reenrolments WHERE user_sub = $1"
                " RETURNING user_sub, key_version",
                record.user_sub,
            )
            if earlier is not None:
                events.append(_event(record.tenant_id, earlier, "cancelled", now))
            await connection.execute(
                "INSERT INTO user_key_reenrolments (tenant_id, user_sub, key_version, enc_pub,"
                " sig_pub, fingerprint, encrypted_private, email, replaces_version, token_hash,"
                " requested_at, expires_at)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
                record.tenant_id,
                record.user_sub,
                record.key_version,
                record.enc_pub,
                record.sig_pub,
                record.fingerprint,
                record.encrypted_private,
                old["email"],
                replaces_version,
                token_hash,
                now,
                expires_at,
            )
            pending = {"user_sub": record.user_sub, "key_version": record.key_version}
            events.append(_event(record.tenant_id, pending, "requested", now))
            await append_audits(connection, events)
            return str(old["email"])

        return await self._run(record.tenant_id, work)

    async def release(self, tenant_id: str, token_hash: bytes, now: datetime) -> None:
        """Drops the pending key whose mail failed: by its hash, never a newer request's."""

        async def work(connection: asyncpg.Connection) -> None:
            row = await connection.fetchrow(
                "DELETE FROM user_key_reenrolments WHERE token_hash = $1"
                " RETURNING user_sub, key_version",
                token_hash,
            )
            if row is not None:
                await append_audits(connection, [_event(tenant_id, row, "cancelled", now)])

        await self._run(tenant_id, work)

    async def sweep(self, tenant_id: str, now: datetime, *, keep: bytes | None = None) -> None:
        """Expires the tenant's lapsed links, but `keep`, which its own call answers for."""

        async def work(connection: asyncpg.Connection) -> None:
            # One sweep per tenant at a time; another one's rows are left to it.
            if not await connection.fetchval(
                "SELECT pg_try_advisory_xact_lock(hashtextextended($1, 0))",
                f"ssf-recording-reenrolment-sweep:{tenant_id}",
            ):
                return
            rows = await connection.fetch(
                "DELETE FROM user_key_reenrolments WHERE expires_at <= $1"
                " AND token_hash IS DISTINCT FROM $2 RETURNING user_sub, key_version",
                now,
                keep,
            )
            ordered = sorted(rows, key=lambda row: row["user_sub"])
            await append_audits(connection, [_event(tenant_id, r, "expired", now) for r in ordered])

        await self._run(tenant_id, work)

    async def pending_of(self, tenant_id: str, sub: str, now: datetime) -> PendingKey | None:
        async def work(connection: asyncpg.Connection) -> PendingKey | None:
            row = await connection.fetchrow(
                "SELECT fingerprint, expires_at FROM user_key_reenrolments"
                " WHERE user_sub = $1 AND expires_at > $2",
                sub,
                now,
            )
            return None if row is None else PendingKey(bytes(row["fingerprint"]), row["expires_at"])

        return await self._run(tenant_id, work)

    async def tenant_of(self, token_hash: bytes) -> str | None:
        """The link's tenant, through the one cross-tenant read the app role may make."""
        try:
            async with self._pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection:
                tenant = await connection.fetchval("SELECT reenrolment_tenant($1)", token_hash)
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None
        return None if tenant is None else str(tenant)

    async def lookup(
        self, tenant_id: str, token_hash: bytes, now: datetime
    ) -> LinkDetails | Refused:
        async def work(connection: asyncpg.Connection) -> LinkDetails | Refused:
            row = await connection.fetchrow(
                f"SELECT {_PENDING} FROM user_key_reenrolments WHERE token_hash = $1", token_hash
            )
            if row is None:
                return Refused("link_invalid")
            if row["expires_at"] > now:
                return LinkDetails(
                    bytes(row["fingerprint"]), row["requested_at"], row["expires_at"]
                )
            # Taken again by its hash: a concurrent call may have used or expired it.
            return await _lapsed(
                connection, tenant_id, await connection.fetchrow(_TAKE, token_hash), now
            ) or Refused("link_invalid")

        return await self._run(tenant_id, work)

    async def decline(self, tenant_id: str, token_hash: bytes, now: datetime) -> Refused | None:
        """ "This wasn't me": the pending key goes, the active one stays."""

        async def work(connection: asyncpg.Connection) -> Refused | None:
            row = await connection.fetchrow(_TAKE, token_hash)
            refused = await _lapsed(connection, tenant_id, row, now)
            if refused is not None:
                return refused
            await append_audits(connection, [_event(tenant_id, row, "declined", now)])
            return None

        return await self._run(tenant_id, work)

    async def confirm(self, tenant_id: str, token_hash: bytes, now: datetime) -> Refused | bytes:
        """§9.6's swap from the pending row; returns the new key's fingerprint."""

        async def work(connection: asyncpg.Connection) -> Refused | bytes:
            # Unlocked, to learn whose key row to lock first.
            sub = await connection.fetchval(
                "SELECT user_sub FROM user_key_reenrolments WHERE token_hash = $1", token_hash
            )
            if sub is None:
                return Refused("link_invalid")
            old = await lock_active_key(connection, sub)
            row = await connection.fetchrow(
                "DELETE FROM user_key_reenrolments WHERE token_hash = $1 AND user_sub = $2"
                " RETURNING *",
                token_hash,
                sub,
            )
            refused = await _lapsed(connection, tenant_id, row, now)
            if refused is not None:
                return refused
            refused = await reenrolment_refusal(connection, old, sub, row["replaces_version"], now)
            if refused == Refused("ceremony_in_progress"):
                raise _KeepPendingError(refused)
            if refused is not None:
                await append_audits(connection, [_event(tenant_id, row, "cancelled", now)])
                return Refused("link_invalid")
            record = _pending_record(tenant_id, row, now)
            await complete_swap(connection, record, old, now, [])
            return record.fingerprint

        try:
            return await self._run(tenant_id, work)
        except _KeepPendingError as kept:
            return kept.refused


def _pending_record(tenant_id: str, row: Any, now: datetime) -> UserKeyRecord:
    return UserKeyRecord(
        tenant_id=tenant_id,
        user_sub=row["user_sub"],
        key_version=row["key_version"],
        enc_pub=bytes(row["enc_pub"]),
        sig_pub=bytes(row["sig_pub"]),
        fingerprint=bytes(row["fingerprint"]),
        encrypted_private=bytes(row["encrypted_private"]),
        created_at=now,
        email=row["email"],
    )
