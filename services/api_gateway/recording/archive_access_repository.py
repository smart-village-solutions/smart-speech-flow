"""Postgres access for an employee's own archive (spec §10.6; migrations 003, 005).

Every read that serves wraps, and every amendment, writes its audit event in
the same transaction, so nothing is served or appended without one. The
opening rule is one SQL fragment, used by each method.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from .archive_repository import entry_from_row, insert_entry, request_stamp
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


def _readable(sub: str, now: str) -> str:
    """Ended, not shredded, within its date or held, and wrapped for the caller."""
    return (
        f"c.ended_at IS NOT NULL AND c.shredded_at IS NULL"
        f" AND (c.retention_until > {now} OR c.legal_hold)"
        " AND EXISTS (SELECT 1 FROM key_wraps w JOIN conversation_keys k"
        "  ON k.tenant_id = w.tenant_id AND k.key_id = w.key_id"
        "  WHERE k.conversation_id = c.conversation_id"
        f"  AND w.recipient_kind = 'user' AND w.recipient_ref = {sub})"
    )


# The status alone is a string the requester's own call sets; k approvals are not (§9.5).
_APPROVED = (
    "(SELECT count(DISTINCT d.holder_index) FROM recovery_decisions d"
    "  WHERE d.tenant_id = r.tenant_id AND d.request_id = r.request_id"
    "  AND d.decision = 'approved' AND NOT EXISTS (SELECT 1 FROM recovery_rejections j"
    "   WHERE j.tenant_id = d.tenant_id AND j.request_id = d.request_id"
    "   AND j.holder_index = d.holder_index AND j.attempt = d.attempt))"
    " >= (SELECT rkey.k FROM recovery_keys rkey"
    "  WHERE rkey.tenant_id = r.tenant_id AND rkey.key_id = r.recovery_key_id)"
)


def _own(sub: str, now: str) -> str:
    """The employee-only rule: amendments stay the employee's own (spec §10.4)."""
    return f"c.employee_sub = {sub} AND {_readable(sub, now)}"


def _openable(sub: str, now: str, supervisor: str) -> str:
    """The opening rule (§10.6), widened by §9.5: the employee, or a supervisor
    whose request for the conversation completed. Arguments are placeholders."""
    return (
        f"(c.employee_sub = {sub} OR ({supervisor} AND EXISTS (SELECT 1"
        " FROM recovery_request_keys rk JOIN recovery_requests r"
        "  ON r.tenant_id = rk.tenant_id AND r.request_id = rk.request_id"
        f"  WHERE rk.conversation_id = c.conversation_id AND r.requester_sub = {sub}"
        f"  AND r.status = 'completed' AND {_APPROVED}))) AND {_readable(sub, now)}"
    )


_LIST = (
    "SELECT c.conversation_id, c.employee_sub, c.started_at, c.ended_at, c.retention_until, c.legal_hold,"
    " c.incomplete,"
    " (SELECT count(*) FROM chain_entries e WHERE e.conversation_id = c.conversation_id"
    "  AND e.kind IN ('message', 'failed')) AS messages,"
    " (SELECT count(*) FROM chain_entries e WHERE e.conversation_id = c.conversation_id"
    "  AND e.kind = 'amendment') AS amendments"
    f" FROM conversations c WHERE {_openable('$1', '$2', '$6')}"
    " AND ($3::timestamptz IS NULL OR c.started_at < $3"
    "  OR (c.started_at = $3 AND c.conversation_id < $5::uuid))"
    " ORDER BY c.started_at DESC, c.conversation_id DESC LIMIT $4"
)
_ONE = (
    "SELECT c.* FROM conversations c WHERE c.conversation_id = $3"
    f" AND {_openable('$1', '$2', '$4')}"
)
_ONE_OWN_LOCKED = (
    "SELECT c.* FROM conversations c WHERE c.conversation_id = $3"
    f" AND {_own('$1', '$2')} FOR UPDATE"
)


class ArchiveAccessRefusedError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OwnConversation:
    conversation_id: str
    employee_sub: str
    started_at: datetime
    ended_at: datetime
    retention_until: datetime
    legal_hold: bool
    incomplete: bool
    messages: int
    amendments: int

    def public(self, caller: str) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "employee_sub": self.employee_sub,
            "recovered": self.employee_sub != caller,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "retention_until": self.retention_until.isoformat(),
            "legal_hold": self.legal_hold,
            "incomplete": self.incomplete,
            "messages": self.messages,
            "amendments": self.amendments,
            # Derived until verification records exist (#619, spec §10.5).
            "verification": "not_verified",
        }


@dataclass(frozen=True)
class WindowRow:
    window_id: str
    opened_at: datetime
    closed_at: datetime | None
    close_reason: str | None
    pauses: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class StampRow:
    head_seq: int
    head_hash: bytes
    token: bytes | None


@dataclass(frozen=True)
class KeyAccess:
    key_id: str
    epoch: int
    wrap: KeyWrap | None  # the caller's
    recovery_wrapped: bool


@dataclass(frozen=True)
class OpenedConversation:
    conversation_id: str
    employee_sub: str
    legal_basis: str
    started_at: datetime
    ended_at: datetime
    retention_until: datetime
    legal_hold: bool
    incomplete: bool
    windows: tuple[WindowRow, ...]
    entries: tuple[ChainEntry, ...]
    stored: Mapping[str, frozenset[str]]  # entry ID -> object types the store confirmed
    stamps: tuple[StampRow, ...]
    keys: tuple[KeyAccess, ...]


@dataclass(frozen=True)
class ObjectLocation:
    key: str
    version_id: str | None  # None while the spool has not delivered it


@dataclass(frozen=True)
class ExistingAmendment:
    entry: ChainEntry
    stored: bool


def _window(row: Any) -> WindowRow:
    pauses = row["pauses"]
    return WindowRow(
        window_id=str(row["window_id"]),
        opened_at=row["opened_at"],
        closed_at=row["closed_at"],
        close_reason=row["close_reason"],
        pauses=tuple(json.loads(pauses) if isinstance(pauses, str) else pauses),
    )


def _keys(rows: list[Any], sub: str) -> tuple[KeyAccess, ...]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        key_id = str(row["key_id"])
        item = by_key.setdefault(key_id, {"epoch": row["epoch"], "wrap": None, "recovery": False})
        if row["recipient_kind"] == "recovery":
            item["recovery"] = True
        elif row["recipient_ref"] == sub:
            item["wrap"] = KeyWrap(
                key_id=key_id,
                recipient_kind="user",
                recipient_ref=sub,
                blob=row["blob"],
                creator_ref=row["creator_ref"],
                creator_signature=bytes(row["creator_signature"]),
            )
    return tuple(
        KeyAccess(key_id, item["epoch"], item["wrap"], item["recovery"])
        for key_id, item in sorted(by_key.items(), key=lambda pair: pair[1]["epoch"])
    )


class PostgresArchiveAccess:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _run(self, tenant_id: str, work: Any) -> Any:
        try:
            async with (
                self._pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as connection,
                connection.transaction(),
            ):
                await bind_tenant(connection, tenant_id)
                return await work(connection)
        except DRIVER_FAILURE as error:
            raise storage_unavailable(error) from None

    async def own_conversations(
        self,
        tenant_id: str,
        sub: str,
        now: datetime,
        *,
        limit: int,
        started_before: datetime | None,
        before_id: str | None,
        supervisor: bool = False,
    ) -> list[OwnConversation]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(
                _LIST, sub, now, started_before, limit, before_id, supervisor
            )

        return [
            OwnConversation(
                conversation_id=str(row["conversation_id"]),
                employee_sub=row["employee_sub"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                retention_until=row["retention_until"],
                legal_hold=row["legal_hold"],
                incomplete=row["incomplete"],
                messages=row["messages"],
                amendments=row["amendments"],
            )
            for row in await self._run(tenant_id, work)
        ]

    async def open(
        self,
        tenant_id: str,
        sub: str,
        conversation_id: str,
        now: datetime,
        *,
        supervisor: bool = False,
    ) -> OpenedConversation | None:
        async def work(connection: asyncpg.Connection) -> OpenedConversation | None:
            row = await connection.fetchrow(_ONE, sub, now, conversation_id, supervisor)
            if row is None:
                await append_audit(
                    connection,
                    AuditEvent(tenant_id, sub, "recording.archive.not_found", conversation_id, now),
                )
                return None
            opened = await _read_conversation(connection, row, sub)
            await append_audit(
                connection,
                AuditEvent(tenant_id, sub, "recording.archive.opened", conversation_id, now),
            )
            return opened

        result: OpenedConversation | None = await self._run(tenant_id, work)
        return result

    async def openable(
        self,
        tenant_id: str,
        sub: str,
        conversation_id: str,
        now: datetime,
        *,
        supervisor: bool = False,
    ) -> bool:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchrow(_ONE, sub, now, conversation_id, supervisor)

        return await self._run(tenant_id, work) is not None

    async def object_location(
        self,
        tenant_id: str,
        sub: str,
        conversation_id: str,
        entry_id: str,
        object_type: str,
        now: datetime,
        *,
        supervisor: bool = False,
    ) -> ObjectLocation | None:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchrow(
                "SELECT e.objects, o.version_id FROM chain_entries e"
                " JOIN conversations c ON c.tenant_id = e.tenant_id"
                "  AND c.conversation_id = e.conversation_id"
                " LEFT JOIN stored_objects o ON o.tenant_id = e.tenant_id"
                "  AND o.entry_id = e.entry_id AND o.object_type = $5"
                f" WHERE e.conversation_id = $3 AND e.entry_id = $4"
                f" AND {_openable('$1', '$2', '$6')}"
                " AND EXISTS (SELECT 1 FROM key_wraps w WHERE w.tenant_id = e.tenant_id"
                "  AND w.key_id = e.key_id AND w.recipient_kind = 'user' AND w.recipient_ref = $1)",
                sub,
                now,
                conversation_id,
                entry_id,
                object_type,
                supervisor,
            )

        row = await self._run(tenant_id, work)
        if row is None:
            return None
        listed = [item for item in json.loads(row["objects"]) if item["type"] == object_type]
        if not listed:
            return None
        return ObjectLocation(listed[0]["key"], row["version_id"])

    async def existing_amendment(
        self, tenant_id: str, sub: str, conversation_id: str, entry_id: str, now: datetime
    ) -> ExistingAmendment | None:
        async def work(connection: asyncpg.Connection) -> Any:
            entry = await connection.fetchrow(
                "SELECT e.* FROM chain_entries e JOIN conversations c"
                " ON c.tenant_id = e.tenant_id AND c.conversation_id = e.conversation_id"
                " WHERE e.entry_id = $4 AND e.conversation_id = $3 AND e.kind = 'amendment'"
                f" AND {_own('$1', '$2')}",
                sub,
                now,
                conversation_id,
                entry_id,
            )
            stored = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM stored_objects WHERE entry_id = $1)", entry_id
            )
            return entry, stored

        row, stored = await self._run(tenant_id, work)
        return None if row is None else ExistingAmendment(entry_from_row(row), bool(stored))

    async def append_amendment(
        self,
        tenant_id: str,
        sub: str,
        conversation_id: str,
        key_id: str,
        now: datetime,
        seal: Callable[[int, bytes], ChainEntry],
        audit_at: datetime,
    ) -> ChainEntry:
        async def work(connection: asyncpg.Connection) -> ChainEntry:
            if await connection.fetchrow(_ONE_OWN_LOCKED, sub, now, conversation_id) is None:
                raise ArchiveAccessRefusedError("no_conversation")
            usable = await connection.fetchval(
                "SELECT count(DISTINCT w.recipient_kind) = 2 FROM key_wraps w"
                " JOIN conversation_keys k ON k.tenant_id = w.tenant_id AND k.key_id = w.key_id"
                " WHERE k.key_id = $1 AND k.conversation_id = $2"
                " AND (w.recipient_kind = 'recovery' OR w.recipient_ref = $3)",
                key_id,
                conversation_id,
                sub,
            )
            if not usable:
                raise ArchiveAccessRefusedError("key_not_usable")
            head = await connection.fetchrow(
                "SELECT seq, hash FROM chain_entries WHERE conversation_id = $1"
                " ORDER BY seq DESC LIMIT 1",
                conversation_id,
            )
            entry = seal(head["seq"] + 1, bytes(head["hash"])) if head else seal(1, bytes(32))
            try:
                await insert_entry(connection, entry)
            except asyncpg.UniqueViolationError:
                raise ArchiveAccessRefusedError("entry_exists") from None
            await request_stamp(connection, conversation_id, audit_at)
            await append_audit(
                connection,
                AuditEvent(tenant_id, sub, "recording.amendment.added", entry.entry_id, audit_at),
            )
            return entry

        result: ChainEntry = await self._run(tenant_id, work)
        return result

    async def mark_incomplete(self, tenant_id: str, conversation_id: str) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                "UPDATE conversations SET incomplete = TRUE WHERE conversation_id = $1",
                conversation_id,
            )

        await self._run(tenant_id, work)

    async def record_not_found(
        self, tenant_id: str, sub: str, conversation_ref: str, at: datetime
    ) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await append_audit(
                connection,
                AuditEvent(tenant_id, sub, "recording.archive.not_found", conversation_ref, at),
            )

        await self._run(tenant_id, work)

    async def record_integrity_failure(
        self, tenant_id: str, sub: str, conversation_id: str, stage: str, at: datetime
    ) -> None:
        event_type = f"recording.archive.integrity_failed.{stage}"

        async def work(connection: asyncpg.Connection) -> None:
            await append_audit(
                connection, AuditEvent(tenant_id, sub, event_type, conversation_id, at)
            )

        await self._run(tenant_id, work)


async def _read_conversation(
    connection: asyncpg.Connection, row: Any, sub: str
) -> OpenedConversation:
    conversation_id = row["conversation_id"]
    windows = await connection.fetch(
        "SELECT * FROM recording_windows WHERE conversation_id = $1 ORDER BY opened_at",
        conversation_id,
    )
    entries = await connection.fetch(
        "SELECT * FROM chain_entries WHERE conversation_id = $1 ORDER BY seq", conversation_id
    )
    stored = await connection.fetch(
        "SELECT o.entry_id, o.object_type FROM stored_objects o JOIN chain_entries e"
        " ON e.tenant_id = o.tenant_id AND e.entry_id = o.entry_id WHERE e.conversation_id = $1",
        conversation_id,
    )
    stamps = await connection.fetch(
        "SELECT head_seq, head_hash, tsa_token FROM chain_stamps WHERE conversation_id = $1"
        " ORDER BY head_seq",
        conversation_id,
    )
    wraps = await connection.fetch(
        "SELECT k.key_id, k.epoch, w.recipient_kind, w.recipient_ref, w.blob, w.creator_ref,"
        " w.creator_signature FROM conversation_keys k JOIN key_wraps w"
        " ON w.tenant_id = k.tenant_id AND w.key_id = k.key_id"
        " WHERE k.conversation_id = $1 AND (w.recipient_kind = 'recovery' OR w.recipient_ref = $2)",
        conversation_id,
        sub,
    )
    types: dict[str, set[str]] = {}
    for item in stored:
        types.setdefault(str(item["entry_id"]), set()).add(item["object_type"])
    return OpenedConversation(
        conversation_id=str(conversation_id),
        employee_sub=row["employee_sub"],
        legal_basis=row["legal_basis"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        retention_until=row["retention_until"],
        legal_hold=row["legal_hold"],
        incomplete=row["incomplete"],
        windows=tuple(_window(item) for item in windows),
        entries=tuple(entry_from_row(item) for item in entries),
        stored={entry_id: frozenset(kinds) for entry_id, kinds in types.items()},
        stamps=tuple(
            StampRow(
                item["head_seq"],
                bytes(item["head_hash"]),
                None if item["tsa_token"] is None else bytes(item["tsa_token"]),
            )
            for item in stamps
        ),
        keys=_keys(list(wraps), sub),
    )
