"""Postgres access for recording mode, in its own database `ssf_recording`.

Every tenant-owned query runs inside a transaction that first binds
`ssf.tenant_id`, so row-level security decides what is visible; queries
therefore carry no tenant WHERE clause of their own (the feedback pattern,
see deploy/postgres/recording/migrations/001_recording_keys.sql).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Self

import asyncpg

from .audit import GENESIS, AuditEvent, AuditRow, audit_hash

COMMAND_TIMEOUT_SECONDS: Final[float] = 5.0
DRIVER_FAILURE: Final = (
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
    asyncpg.InternalClientError,
    OSError,
    TimeoutError,  # command_timeout, or no pooled connection in time
)


class RecordingStorageUnavailable(RuntimeError):
    """The recording database could not answer; the route maps it to 503."""


class KeyAlreadyEnrolledError(Exception):
    """The user already has an active key; replacing it is key recovery (#617)."""


@dataclass(frozen=True)
class UserKeyRecord:
    tenant_id: str
    user_sub: str
    key_version: int
    enc_pub: bytes
    sig_pub: bytes
    fingerprint: bytes
    # The server-layer envelope of the passphrase-sealed blob; None once deleted.
    encrypted_private: bytes | None
    created_at: datetime


async def bind_tenant(connection: asyncpg.Connection, tenant_id: str) -> None:
    await connection.execute("SELECT set_config('ssf.tenant_id', $1, TRUE)", tenant_id)


async def append_audit(connection: asyncpg.Connection, event: AuditEvent) -> None:
    await append_audits(connection, [event])


async def append_audits(connection: asyncpg.Connection, events: Sequence[AuditEvent]) -> None:
    """Append under one per-tenant transaction lock, so two writers cannot fork the chain.

    One lock, one head read and one insert however many events: a 2,000-key
    recovery step must not hold the chain, which a guest's yes waits on, for long.
    """
    if not events:
        return
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        f"ssf-recording-audit:{events[0].tenant_id}",
    )
    last = await connection.fetchrow("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1")
    seq = 0 if last is None else last["seq"]
    prev_hash = GENESIS if last is None else bytes(last["hash"])
    rows = []
    for event in events:
        seq += 1
        digest = audit_hash(event, seq, prev_hash)
        rows.append(
            (
                event.tenant_id,
                seq,
                event.at,
                event.actor_sub,
                event.event_type,
                event.object_ref,
                prev_hash,
                digest,
            )
        )
        prev_hash = digest
    await connection.executemany(
        "INSERT INTO audit_events (tenant_id, seq, at, actor_sub, event_type, object_ref,"
        " prev_hash, hash) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        rows,
    )


async def insert_user_key(connection: asyncpg.Connection, record: UserKeyRecord) -> None:
    await connection.execute(
        "INSERT INTO user_keys (tenant_id, user_sub, key_version, enc_pub,"
        " sig_pub, fingerprint, encrypted_private, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        record.tenant_id,
        record.user_sub,
        record.key_version,
        record.enc_pub,
        record.sig_pub,
        record.fingerprint,
        record.encrypted_private,
        record.created_at,
    )


def storage_unavailable(error: BaseException) -> RecordingStorageUnavailable:
    # Type name only: a driver error can carry the DSN, and the DSN the password.
    sys.stderr.write(f"Recording storage failure: {type(error).__name__}\n")
    return RecordingStorageUnavailable("the recording database is unavailable")


def user_key_from_row(row: Any) -> UserKeyRecord:
    encrypted = row["encrypted_private"]
    return UserKeyRecord(
        tenant_id=row["tenant_id"],
        user_sub=row["user_sub"],
        key_version=row["key_version"],
        enc_pub=bytes(row["enc_pub"]),
        sig_pub=bytes(row["sig_pub"]),
        fingerprint=bytes(row["fingerprint"]),
        encrypted_private=None if encrypted is None else bytes(encrypted),
        created_at=row["created_at"],
    )


class PostgresRecordingRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, *, dsn: str, password: str | None) -> Self:
        """The password arrives beside the DSN: a generated one is not URL-safe."""
        pool = await asyncpg.create_pool(
            dsn=dsn,
            password=password or None,
            min_size=1,
            max_size=5,
            # A hung database must not hold a recording step, and its session lock, forever.
            command_timeout=COMMAND_TIMEOUT_SECONDS,
        )
        return cls(pool)

    @property
    def pool(self) -> asyncpg.Pool:
        """Shared with the archive repository, so recording holds one pool."""
        return self._pool

    async def close(self) -> None:
        await self._pool.close()

    async def active_user_key(self, tenant_id: str, user_sub: str) -> UserKeyRecord | None:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    row = await connection.fetchrow(
                        "SELECT * FROM user_keys WHERE user_sub = $1 AND retired_at IS NULL",
                        user_sub,
                    )
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None
        return None if row is None else user_key_from_row(row)

    async def enrol_user_key(self, record: UserKeyRecord, audit: AuditEvent) -> None:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, record.tenant_id)
                    await insert_user_key(connection, record)
                    await append_audit(connection, audit)
        except asyncpg.UniqueViolationError:
            raise KeyAlreadyEnrolledError() from None
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def record_audit(self, event: AuditEvent) -> None:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, event.tenant_id)
                    await append_audit(connection, event)
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def audit_rows(self, tenant_id: str) -> list[AuditRow]:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    rows = await connection.fetch("SELECT * FROM audit_events ORDER BY seq")
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None
        return [
            AuditRow(
                event=AuditEvent(
                    row["tenant_id"],
                    row["actor_sub"],
                    row["event_type"],
                    row["object_ref"],
                    row["at"],
                ),
                seq=row["seq"],
                prev_hash=bytes(row["prev_hash"]),
                hash=bytes(row["hash"]),
            )
            for row in rows
        ]

    async def register_gateway_key(self, key_id: str, public_key: bytes, at: datetime) -> None:
        """Kept for good: old chain entries and wraps must stay verifiable after rotation."""
        try:
            async with self._pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO gateway_signing_keys (key_id, public_key, first_seen_at)"
                    " VALUES ($1, $2, $3) ON CONFLICT (key_id) DO NOTHING",
                    key_id,
                    public_key,
                    at,
                )
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def gateway_keys(self) -> tuple[tuple[str, bytes], ...]:
        try:
            async with self._pool.acquire() as connection:
                rows = await connection.fetch(
                    "SELECT key_id, public_key FROM gateway_signing_keys ORDER BY key_id"
                )
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None
        return tuple((row["key_id"], bytes(row["public_key"])) for row in rows)
