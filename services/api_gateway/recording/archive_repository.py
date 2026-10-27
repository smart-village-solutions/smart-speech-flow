"""Postgres access for recorded conversations (spec §11, §13; migration 003).

Each method is one transaction bound to the tenant, so row-level security
decides visibility as everywhere in `ssf_recording`. The chain and the
stored-object rows are append-only; only a conversation's end and
incompleteness, a window's close and pauses, and a stamp's progress change.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from .audit import AuditEvent
from .chain import ChainEntry
from .conversation_keys import KeyWrap
from .repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    append_audit,
    bind_tenant,
    storage_unavailable,
)

# An entry whose listed objects are not all confirmed by the store.
_UNSTORED_ENTRY = """
    SELECT 1 FROM chain_entries e
    WHERE e.conversation_id = s.conversation_id AND e.seq <= s.head_seq
      AND (SELECT count(*) FROM stored_objects o WHERE o.entry_id = e.entry_id)
          < jsonb_array_length(e.objects::jsonb)
"""


@dataclass(frozen=True)
class ConversationRecord:
    tenant_id: str
    conversation_id: str
    session_ref: str
    employee_sub: str
    legal_basis: str
    timestamp_authority_url: str
    started_at: datetime
    retention_until: datetime


@dataclass(frozen=True)
class NewKey:
    """A conversation key's public record: its epoch and the wraps made at creation."""

    key_id: str
    epoch: int
    created_at: datetime
    wraps: tuple[KeyWrap, ...]


@dataclass(frozen=True)
class WindowOpening:
    """Everything a guest's yes writes, together or not at all."""

    conversation: ConversationRecord
    new_conversation: bool
    window_id: str
    opened_at: datetime
    key: NewKey | None
    consent: ChainEntry
    audit: AuditEvent


@dataclass(frozen=True)
class PendingStamp:
    conversation_id: str
    head_seq: int
    head_hash: bytes
    url: str
    attempts: int


def _conversation(row: Any) -> ConversationRecord:
    return ConversationRecord(
        tenant_id=row["tenant_id"],
        conversation_id=str(row["conversation_id"]),
        session_ref=row["session_ref"],
        employee_sub=row["employee_sub"],
        legal_basis=row["legal_basis"],
        timestamp_authority_url=row["timestamp_authority_url"],
        started_at=row["started_at"],
        retention_until=row["retention_until"],
    )


def _entry(row: Any) -> ChainEntry:
    return ChainEntry(
        tenant_id=row["tenant_id"],
        conversation_id=str(row["conversation_id"]),
        seq=row["seq"],
        entry_id=str(row["entry_id"]),
        kind=row["kind"],
        window_id=None if row["window_id"] is None else str(row["window_id"]),
        key_id=str(row["key_id"]),
        objects=row["objects"],
        prev_hash=bytes(row["prev_hash"]),
        hash=bytes(row["hash"]),
        signer_key_id=row["signer_key_id"],
        signature=bytes(row["signature"]),
        created_at=row["created_at"],
    )


async def _insert_key(
    connection: asyncpg.Connection, tenant_id: str, conversation_id: str, key: NewKey
) -> None:
    await connection.execute(
        "INSERT INTO conversation_keys (tenant_id, key_id, conversation_id, epoch, created_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        tenant_id,
        key.key_id,
        conversation_id,
        key.epoch,
        key.created_at,
    )
    for wrap in key.wraps:
        await connection.execute(
            "INSERT INTO key_wraps (tenant_id, key_id, recipient_kind, recipient_ref, blob,"
            " creator_ref, creator_signature, granted_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            tenant_id,
            wrap.key_id,
            wrap.recipient_kind,
            wrap.recipient_ref,
            wrap.blob,
            wrap.creator_ref,
            wrap.creator_signature,
            key.created_at,
        )


async def _insert_entry(connection: asyncpg.Connection, entry: ChainEntry) -> None:
    await connection.execute(
        "INSERT INTO chain_entries (tenant_id, conversation_id, seq, entry_id, kind, window_id,"
        " key_id, objects, prev_hash, hash, signer_key_id, signature, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)",
        entry.tenant_id,
        entry.conversation_id,
        entry.seq,
        entry.entry_id,
        entry.kind,
        entry.window_id,
        entry.key_id,
        entry.objects,
        entry.prev_hash,
        entry.hash,
        entry.signer_key_id,
        entry.signature,
        entry.created_at,
    )


async def _request_stamp(
    connection: asyncpg.Connection, conversation_id: str, at: datetime
) -> None:
    """Stamp the current head, once; a conversation with no entry has nothing to stamp."""
    await connection.execute(
        "INSERT INTO chain_stamps (tenant_id, conversation_id, head_seq, head_hash,"
        " requested_at, next_attempt_at)"
        " SELECT tenant_id, conversation_id, seq, hash, $2, $2 FROM chain_entries"
        " WHERE conversation_id = $1 ORDER BY seq DESC LIMIT 1"
        " ON CONFLICT DO NOTHING",
        conversation_id,
        at,
    )


class PostgresArchiveRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _run(self, tenant_id: str, work: Any) -> Any:
        try:
            async with self._pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection:
                async with connection.transaction():
                    await bind_tenant(connection, tenant_id)
                    return await work(connection)
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def open_window(self, opening: WindowOpening) -> None:
        conversation = opening.conversation

        async def work(connection: asyncpg.Connection) -> None:
            if opening.new_conversation:
                await connection.execute(
                    "INSERT INTO conversations (tenant_id, conversation_id, session_ref,"
                    " employee_sub, legal_basis, timestamp_authority_url, started_at,"
                    " retention_until) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                    conversation.tenant_id,
                    conversation.conversation_id,
                    conversation.session_ref,
                    conversation.employee_sub,
                    conversation.legal_basis,
                    conversation.timestamp_authority_url,
                    conversation.started_at,
                    conversation.retention_until,
                )
            await connection.execute(
                "INSERT INTO recording_windows (tenant_id, window_id, conversation_id, opened_at)"
                " VALUES ($1, $2, $3, $4)",
                conversation.tenant_id,
                opening.window_id,
                conversation.conversation_id,
                opening.opened_at,
            )
            if opening.key is not None:
                await _insert_key(
                    connection, conversation.tenant_id, conversation.conversation_id, opening.key
                )
            await _insert_entry(connection, opening.consent)
            await append_audit(connection, opening.audit)

        await self._run(conversation.tenant_id, work)

    async def append_entry(self, entry: ChainEntry, key: NewKey | None) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            if key is not None:
                await _insert_key(connection, entry.tenant_id, entry.conversation_id, key)
            await _insert_entry(connection, entry)

        await self._run(entry.tenant_id, work)

    async def conversation(self, tenant_id: str, conversation_id: str) -> ConversationRecord | None:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchrow(
                "SELECT * FROM conversations WHERE conversation_id = $1", conversation_id
            )

        row = await self._run(tenant_id, work)
        return None if row is None else _conversation(row)

    async def chain_state(self, tenant_id: str, conversation_id: str) -> tuple[int, bytes, int]:
        """(head seq, head hash, highest key epoch); zeros for a conversation without entries."""

        async def work(connection: asyncpg.Connection) -> Any:
            head = await connection.fetchrow(
                "SELECT seq, hash FROM chain_entries WHERE conversation_id = $1"
                " ORDER BY seq DESC LIMIT 1",
                conversation_id,
            )
            epoch = await connection.fetchval(
                "SELECT coalesce(max(epoch), 0) FROM conversation_keys WHERE conversation_id = $1",
                conversation_id,
            )
            return head, epoch

        head, epoch = await self._run(tenant_id, work)
        if head is None:
            return 0, bytes(32), epoch
        return head["seq"], bytes(head["hash"]), epoch

    async def chain(self, tenant_id: str, conversation_id: str) -> list[ChainEntry]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(
                "SELECT * FROM chain_entries WHERE conversation_id = $1 ORDER BY seq",
                conversation_id,
            )

        return [_entry(row) for row in await self._run(tenant_id, work)]

    async def record_stored(
        self, tenant_id: str, entry_id: str, object_type: str, version_id: str, at: datetime
    ) -> bool:
        """False when no entry lists the object: nothing to record, and nothing to retry."""

        async def work(connection: asyncpg.Connection) -> bool:
            known = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM chain_entries WHERE entry_id = $1)", entry_id
            )
            if known:
                await connection.execute(
                    "INSERT INTO stored_objects (tenant_id, entry_id, object_type, version_id,"
                    " stored_at) VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
                    tenant_id,
                    entry_id,
                    object_type,
                    version_id,
                    at,
                )
            return bool(known)

        return bool(await self._run(tenant_id, work))

    async def stored_types(self, tenant_id: str, entry_id: str) -> frozenset[str]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(
                "SELECT object_type FROM stored_objects WHERE entry_id = $1", entry_id
            )

        return frozenset(row["object_type"] for row in await self._run(tenant_id, work))

    async def note_pause(
        self, tenant_id: str, conversation_id: str, window_id: str, at: datetime, reason: str
    ) -> None:
        pause = json.dumps([{"at": at.isoformat(), "reason": reason, "resumed_at": None}])

        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "UPDATE recording_windows SET pauses = pauses || $2::jsonb WHERE window_id = $1",
                window_id,
                pause,
            )
            await connection.execute(
                "UPDATE conversations SET incomplete = TRUE WHERE conversation_id = $1",
                conversation_id,
            )

        await self._run(tenant_id, work)

    async def note_resume(self, tenant_id: str, window_id: str, at: datetime) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "UPDATE recording_windows SET pauses = jsonb_set(pauses,"
                " ARRAY[(jsonb_array_length(pauses) - 1)::text, 'resumed_at'], to_jsonb($2::text))"
                " WHERE window_id = $1 AND jsonb_array_length(pauses) > 0",
                window_id,
                at.isoformat(),
            )

        await self._run(tenant_id, work)

    async def mark_incomplete(self, tenant_id: str, conversation_id: str) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "UPDATE conversations SET incomplete = TRUE WHERE conversation_id = $1",
                conversation_id,
            )

        await self._run(tenant_id, work)

    async def close_window(
        self, tenant_id: str, conversation_id: str, window_id: str, at: datetime, reason: str
    ) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "UPDATE recording_windows SET closed_at = $2, close_reason = $3"
                " WHERE window_id = $1 AND closed_at IS NULL",
                window_id,
                at,
                reason,
            )
            await _request_stamp(connection, conversation_id, at)

        await self._run(tenant_id, work)

    async def end_conversation(self, tenant_id: str, conversation_id: str, at: datetime) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "UPDATE conversations SET ended_at = $2"
                " WHERE conversation_id = $1 AND ended_at IS NULL",
                conversation_id,
                at,
            )
            # A window whose close was never written (a failed write, a crash) ends here.
            await connection.execute(
                "UPDATE recording_windows SET closed_at = $2, close_reason = 'session_ended'"
                " WHERE conversation_id = $1 AND closed_at IS NULL",
                conversation_id,
                at,
            )
            await _request_stamp(connection, conversation_id, at)

        await self._run(tenant_id, work)

    async def pending_stamps(
        self, tenant_id: str, now: datetime, limit: int = 20
    ) -> list[PendingStamp]:
        """Heads due for a token whose entries are all stored, oldest first."""

        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(
                "SELECT s.conversation_id, s.head_seq, s.head_hash, s.attempts,"
                " c.timestamp_authority_url FROM chain_stamps s"
                " JOIN conversations c USING (tenant_id, conversation_id)"
                " WHERE s.tsa_token IS NULL AND s.next_attempt_at <= $1"
                f" AND NOT EXISTS ({_UNSTORED_ENTRY})"
                " ORDER BY s.requested_at LIMIT $2",
                now,
                limit,
            )

        return [
            PendingStamp(
                conversation_id=str(row["conversation_id"]),
                head_seq=row["head_seq"],
                head_hash=bytes(row["head_hash"]),
                url=row["timestamp_authority_url"],
                attempts=row["attempts"],
            )
            for row in await self._run(tenant_id, work)
        ]

    async def save_stamp(
        self,
        tenant_id: str,
        stamp: PendingStamp,
        token: bytes,
        stamped_at: datetime,
    ) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "UPDATE chain_stamps SET tsa_token = $3, stamped_at = $4, attempts = attempts + 1"
                " WHERE conversation_id = $1 AND head_seq = $2 AND tsa_token IS NULL",
                stamp.conversation_id,
                stamp.head_seq,
                token,
                stamped_at,
            )

        await self._run(tenant_id, work)

    async def defer_stamp(
        self, tenant_id: str, stamp: PendingStamp, next_attempt_at: datetime
    ) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "UPDATE chain_stamps SET attempts = attempts + 1, next_attempt_at = $3"
                " WHERE conversation_id = $1 AND head_seq = $2 AND tsa_token IS NULL",
                stamp.conversation_id,
                stamp.head_seq,
                next_attempt_at,
            )

        await self._run(tenant_id, work)

    async def stamps(self, tenant_id: str, conversation_id: str) -> Sequence[Any]:
        """Every stamp row of a conversation, for checks and tests."""

        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(
                "SELECT * FROM chain_stamps WHERE conversation_id = $1 ORDER BY head_seq",
                conversation_id,
            )

        return list(await self._run(tenant_id, work))
