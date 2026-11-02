"""Postgres side of verification by assigned reviewers (spec §10.7; migration 011).

Writers keep the recording lock order: user keys, the conversation, the
verification records, then the wraps, with the audit appended last.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

import asyncpg

from .archive_access_repository import OpenedConversation, read_conversation
from .audit import AuditEvent
from .recovery_requests_model import Refused
from .repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    append_audits,
    bind_tenant,
    storage_unavailable,
)
from .verification_model import (
    OPEN,
    DecisionPost,
    InboxRow,
    KeyRow,
    NewAssignment,
    NotePost,
    PendingDecisionStamp,
    VerificationRow,
    new_verification_id,
    verification_from_row,
)
from .verification_sql import (
    LIVE_REASON,
    OPEN_STATUSES,
    assigned,
    excluded,
    openable,
    reviewing,
)

T = TypeVar("T")

_KEYS = (
    "SELECT user_sub, key_version, fingerprint, enc_pub, sig_pub FROM user_keys"
    " WHERE user_sub = ANY($1::text[]) AND retired_at IS NULL"
)
_SCOPE = "SELECT key_id FROM conversation_keys WHERE conversation_id = $1 ORDER BY key_id"
_EXCLUDED = (
    "SELECT s.sub FROM unnest($2::text[]) AS s(sub) CROSS JOIN conversations c"
    f" WHERE c.conversation_id = $1 AND ({excluded('s.sub')} OR {assigned('s.sub')})"
)
_ASSIGNABLE = (
    "SELECT c.conversation_id FROM conversations c WHERE c.conversation_id = $3"
    f" AND {openable('$1', '$2', '$4')} FOR UPDATE"
)
_REVIEWER_EXCLUDED = f"SELECT {excluded('$2')} FROM conversations c WHERE c.conversation_id = $1"
_INSERT = (
    "INSERT INTO verifications (tenant_id, verification_id, conversation_id, status,"
    " requested_by, requester_key_version, requested_at, directory_read_at, reviewer_sub,"
    " reviewer_key_version, reviewer_fingerprint)"
    " VALUES ($1, $2, $3, 'awaiting', $4, $5, $6, $7, $8, $9, $10) RETURNING *"
)
_GRANT = (
    "INSERT INTO key_wraps (tenant_id, key_id, recipient_kind, recipient_ref, blob,"
    " creator_ref, creator_signature, granted_at)"
    " SELECT $1, w.key_id, 'user', $2, w.blob, $3, w.signature, $4"
    " FROM unnest($5::uuid[], $6::text[], $7::bytea[]) AS w(key_id, blob, signature)"
)


_INBOX = (
    "SELECT v.verification_id, v.status, v.requested_at, v.requested_by, c.started_at,"
    " c.ended_at, (SELECT count(*) FROM chain_entries e WHERE e.conversation_id ="
    " c.conversation_id AND e.kind IN ('message', 'failed')) AS messages,"
    f" {reviewing('$1', '$2', 'TRUE')} AS openable"
    " FROM verifications v JOIN conversations c"
    "  ON c.tenant_id = v.tenant_id AND c.conversation_id = v.conversation_id"
    f" WHERE v.reviewer_sub = $1 ORDER BY (v.status IN {OPEN_STATUSES}) DESC,"
    " v.requested_at DESC, v.verification_id DESC LIMIT 100"
)
# The caller's record and its conversation, if the reviewer branch lets them read it.
_REVIEW = (
    "SELECT v.*, row_to_json(c.*) AS conversation FROM verifications v JOIN conversations c"
    "  ON c.tenant_id = v.tenant_id AND c.conversation_id = v.conversation_id"
    f" WHERE v.verification_id = $3 AND v.reviewer_sub = $1 AND v.status IN {OPEN_STATUSES}"
    f" AND {reviewing('$1', '$2', '$4')}"
)
_CONVERSATION = "SELECT c.* FROM conversations c WHERE c.conversation_id = $1"
_NOTES = (
    "SELECT entry_id, key_id, ciphertext FROM verification_notes WHERE verification_id = $1"
    " ORDER BY entry_id"
)
_KEY_AT = (
    "SELECT user_sub, key_version, fingerprint, enc_pub, sig_pub FROM user_keys"
    " WHERE user_sub = $1 AND key_version = $2"
)


# Locks in the recording order: the conversation, then the record (§10.7).
_RECORD_OF = (
    "SELECT conversation_id FROM verifications WHERE verification_id = $1 AND reviewer_sub = $2"
)
_CONVERSATION_SHARED = "SELECT 1 FROM conversations WHERE conversation_id = $1 FOR SHARE"
_RECORD_LOCKED = "SELECT * FROM verifications WHERE verification_id = $1 FOR UPDATE"
_STILL_REVIEWING = (
    f"SELECT {reviewing('$2', '$3', 'TRUE')} AS still_reviewing FROM conversations c"
    " WHERE c.conversation_id = $1"
)
_HEAD = "SELECT seq, hash FROM chain_entries WHERE conversation_id = $1 ORDER BY seq DESC LIMIT 1"
_START = (
    "UPDATE verifications SET status = 'in_review', started_at = $2, reviewed_head_seq = $3,"
    " reviewed_head = $4, permission_snapshot = $5 WHERE verification_id = $1 RETURNING *"
)
_RESNAPSHOT = (
    "UPDATE verifications SET permission_snapshot = $2 WHERE verification_id = $1 RETURNING *"
)
_ENTRIES = "SELECT entry_id, key_id, seq FROM chain_entries WHERE conversation_id = $1"
_DROP_NOTES = "DELETE FROM verification_notes WHERE verification_id = $1"
_PUT_NOTES = (
    "INSERT INTO verification_notes (tenant_id, verification_id, entry_id, key_id, ciphertext)"
    " SELECT $1, $2, n.entry_id, n.key_id, n.ciphertext"
    " FROM unnest($3::uuid[], $4::uuid[], $5::bytea[]) AS n(entry_id, key_id, ciphertext)"
)
_PUT_OVERALL = "UPDATE verifications SET overall_note = $2 WHERE verification_id = $1"
_CLOSE = (
    "UPDATE verifications SET status = $2, closed_at = $3, close_reason = $4,"
    " overall_note = NULL WHERE verification_id = $1"
)
_REVIEWER_KEY = (
    "SELECT key_version, fingerprint FROM user_keys WHERE user_sub = $1 AND retired_at IS NULL"
    " FOR SHARE"
)
_RECORD_PRE_READ = "SELECT * FROM verifications WHERE verification_id = $1 AND reviewer_sub = $2"
_DECIDE = (
    "UPDATE verifications SET status = $2, outcome = $2, notes_digest = $3, signature = $4,"
    " signer_key_version = $5, decided_at = $6, stamp_requested_at = $6,"
    " stamp_next_attempt_at = $6 WHERE verification_id = $1 RETURNING *"
)
_DUE_STAMPS = (
    "SELECT v.verification_id, v.conversation_id, v.reviewed_head, v.outcome, v.notes_digest,"
    " v.permission_snapshot, v.signature, v.stamp_attempts, c.timestamp_authority_url"
    " FROM verifications v JOIN conversations c"
    "  ON c.tenant_id = v.tenant_id AND c.conversation_id = v.conversation_id"
    " WHERE v.tsa_token IS NULL AND v.stamp_requested_at IS NOT NULL"
    " AND v.stamp_next_attempt_at <= $1 ORDER BY v.stamp_requested_at LIMIT $2"
)
_SAVE_STAMP = (
    "UPDATE verifications SET tsa_token = $2, stamped_at = $3, stamp_attempts = stamp_attempts + 1"
    " WHERE verification_id = $1 AND tsa_token IS NULL"
)
_DEFER_STAMP = (
    "UPDATE verifications SET stamp_attempts = stamp_attempts + 1, stamp_next_attempt_at = $2"
    " WHERE verification_id = $1 AND tsa_token IS NULL"
)
# The reviewer's wraps on this conversation that no reason keeps any more (§10.7).
RELEASE = (
    "DELETE FROM key_wraps w USING conversation_keys k, conversations c"
    " WHERE k.tenant_id = w.tenant_id AND k.key_id = w.key_id"
    " AND c.tenant_id = k.tenant_id AND c.conversation_id = k.conversation_id"
    " AND c.conversation_id = $1 AND w.recipient_kind = 'user' AND w.recipient_ref = $2"
    f" AND NOT {LIVE_REASON} RETURNING w.key_id"
)


@dataclass(frozen=True)
class ReviewOpened:
    conversation: OpenedConversation
    record: VerificationRow
    draft: tuple[NotePost, ...]
    requester: KeyRow | None
    requester_name: str | None = None


def note_post(row: Mapping[str, Any]) -> NotePost:
    return NotePost(str(row["entry_id"]), str(row["key_id"]), bytes(row["ciphertext"]))


def key_row(row: Mapping[str, Any]) -> KeyRow:
    return KeyRow(
        sub=row["user_sub"],
        key_version=row["key_version"],
        fingerprint=bytes(row["fingerprint"]),
        enc_pub=bytes(row["enc_pub"]),
        sig_pub=bytes(row["sig_pub"]),
    )


class PostgresVerifications:
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

    async def excluded(
        self, tenant_id: str, conversation_id: str, subs: Sequence[str]
    ) -> frozenset[str]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(_EXCLUDED, uuid.UUID(conversation_id), list(subs))

        return frozenset(row["sub"] for row in await self._run(tenant_id, work))

    async def active_keys(self, tenant_id: str, subs: Sequence[str]) -> dict[str, KeyRow]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(_KEYS, list(subs))

        return {row["user_sub"]: key_row(row) for row in await self._run(tenant_id, work)}

    async def conversation_keys(self, tenant_id: str, conversation_id: str) -> tuple[str, ...]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(_SCOPE, uuid.UUID(conversation_id))

        return tuple(str(row["key_id"]) for row in await self._run(tenant_id, work))

    async def inbox(self, tenant_id: str, sub: str, now: datetime) -> list[InboxRow]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(_INBOX, sub, now)

        return [
            InboxRow(
                verification_id=str(row["verification_id"]),
                status=row["status"],
                requested_at=row["requested_at"],
                requested_by=row["requested_by"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                messages=row["messages"],
                openable=bool(row["openable"]) and row["status"] in OPEN,
            )
            for row in await self._run(tenant_id, work)
        ]

    async def open_review(
        self, tenant_id: str, sub: str, verification_id: str, now: datetime, *, reviewer: bool
    ) -> ReviewOpened | None:
        """The audit event is written with the read that serves the wraps (§10.6)."""

        async def work(connection: asyncpg.Connection) -> ReviewOpened | None:
            row = await connection.fetchrow(_REVIEW, sub, now, uuid.UUID(verification_id), reviewer)
            if row is None:
                await append_audits(
                    connection,
                    [
                        AuditEvent(
                            tenant_id, sub, "recording.verification.not_found", verification_id, now
                        )
                    ],
                )
                return None
            record = verification_from_row(row)
            conversation_row = await connection.fetchrow(_CONVERSATION, row["conversation_id"])
            opened = await read_conversation(connection, conversation_row, sub)
            notes = await connection.fetch(_NOTES, row["verification_id"])
            requester = await connection.fetchrow(
                _KEY_AT, record.requested_by, record.requester_key_version
            )
            await append_audits(
                connection,
                [
                    AuditEvent(
                        tenant_id, sub, "recording.archive.opened", record.conversation_id, now
                    )
                ],
            )
            return ReviewOpened(
                conversation=opened,
                record=record,
                draft=tuple(note_post(note) for note in notes),
                requester=None if requester is None else key_row(requester),
            )

        return await self._run(tenant_id, work)

    async def assign(
        self, assignment: NewAssignment, now: datetime, *, supervisor: bool
    ) -> Refused | VerificationRow:
        async def work(connection: asyncpg.Connection) -> Refused | VerificationRow:
            refused = await _assign_refusal(connection, assignment, now, supervisor)
            if refused is not None:
                return refused
            try:
                async with connection.transaction():
                    row = await _insert(connection, assignment, now)
            except asyncpg.UniqueViolationError:
                return Refused("assignment_exists")
            await _grant(connection, assignment, now)
            await append_audits(connection, _granted_events(assignment, row, now))
            return row

        return await self._run(assignment.tenant_id, work)

    async def start(
        self,
        tenant_id: str,
        sub: str,
        verification_id: str,
        expected_head_seq: int,
        snapshot: Sequence[str],
        now: datetime,
    ) -> Refused | VerificationRow:
        async def work(connection: asyncpg.Connection) -> Refused | VerificationRow:
            record = await locked_record(connection, sub, verification_id, now)
            if isinstance(record, Refused):
                return record
            if record.status == "in_review":
                row = await connection.fetchrow(
                    _RESNAPSHOT, uuid.UUID(verification_id), list(snapshot)
                )
                return verification_from_row(row)
            head = await connection.fetchrow(_HEAD, uuid.UUID(record.conversation_id))
            if head is None or head["seq"] != expected_head_seq:
                return Refused("head_changed")
            row = await connection.fetchrow(
                _START,
                uuid.UUID(verification_id),
                now,
                head["seq"],
                bytes(head["hash"]),
                list(snapshot),
            )
            started = verification_from_row(row)
            await append_audits(
                connection,
                [AuditEvent(tenant_id, sub, "recording.verification.started", started.ref, now)],
            )
            return started

        return await self._run(tenant_id, work)

    async def save_draft(
        self,
        tenant_id: str,
        sub: str,
        verification_id: str,
        overall: bytes | None,
        notes: Sequence[NotePost],
        now: datetime,
    ) -> Refused | None:
        """Not audited: a save changes no access and carries no clear content (§10.7)."""

        async def work(connection: asyncpg.Connection) -> Refused | None:
            record = await locked_record(connection, sub, verification_id, now)
            if isinstance(record, Refused):
                return record
            if record.status != "in_review":
                return Refused("not_started")
            refused = await notes_refusal(connection, record, notes)
            if refused is not None:
                return refused
            await put_notes(connection, tenant_id, record, overall, notes)
            return None

        return await self._run(tenant_id, work)

    async def decline(
        self, tenant_id: str, sub: str, verification_id: str, now: datetime
    ) -> Refused | None:
        async def work(connection: asyncpg.Connection) -> Refused | None:
            record = await locked_record(connection, sub, verification_id, now)
            if isinstance(record, Refused):
                return record
            vid = uuid.UUID(verification_id)
            await connection.execute(_DROP_NOTES, vid)
            await connection.execute(_CLOSE, vid, "declined", now, "declined")
            released = await release(connection, record)
            await append_audits(
                connection,
                [AuditEvent(tenant_id, sub, "recording.verification.declined", record.ref, now)]
                + released_events(tenant_id, sub, record, released, now),
            )
            return None

        return await self._run(tenant_id, work)

    async def record_of(
        self, tenant_id: str, sub: str, verification_id: str
    ) -> VerificationRow | None:
        """An unlocked read for the service's checks; the decision re-checks under its locks."""

        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetchrow(_RECORD_PRE_READ, uuid.UUID(verification_id), sub)

        row = await self._run(tenant_id, work)
        return None if row is None else verification_from_row(row)

    async def decide(
        self, tenant_id: str, sub: str, verification_id: str, decision: DecisionPost, now: datetime
    ) -> Refused | VerificationRow:
        async def work(connection: asyncpg.Connection) -> Refused | VerificationRow:
            key = await connection.fetchrow(_REVIEWER_KEY, sub)
            record = await locked_record(connection, sub, verification_id, now)
            if isinstance(record, Refused):
                return record
            if record.status != "in_review":
                return Refused("not_started")
            if key is None or bytes(key["fingerprint"]) != record.reviewer_fingerprint:
                return Refused("key_changed")
            signed = (decision.snapshot, decision.reviewed_head)
            if signed != (record.permission_snapshot, record.reviewed_head):
                return Refused("permissions_changed")
            refused = await notes_refusal(connection, record, decision.notes)
            if refused is not None:
                return refused
            await put_notes(connection, tenant_id, record, decision.overall, decision.notes)
            row = await connection.fetchrow(
                _DECIDE,
                uuid.UUID(verification_id),
                decision.outcome,
                decision.notes_digest,
                decision.signature,
                decision.signer_key_version,
                now,
            )
            decided = verification_from_row(row)
            released = await release(connection, decided)
            ref = f"{decided.ref}:{decision.signed_digest.hex()}"
            event = f"recording.verification.decided.{decision.outcome}"
            await append_audits(
                connection,
                [AuditEvent(tenant_id, sub, event, ref, now)]
                + released_events(tenant_id, sub, decided, released, now),
            )
            return decided

        return await self._run(tenant_id, work)

    async def pending_decision_stamps(
        self, tenant_id: str, now: datetime, limit: int = 20
    ) -> list[PendingDecisionStamp]:
        async def work(connection: asyncpg.Connection) -> Any:
            return await connection.fetch(_DUE_STAMPS, now, limit)

        return [
            PendingDecisionStamp(
                verification_id=str(row["verification_id"]),
                conversation_id=str(row["conversation_id"]),
                reviewed_head=bytes(row["reviewed_head"]),
                outcome=row["outcome"],
                notes_digest=bytes(row["notes_digest"]),
                permission_snapshot=tuple(row["permission_snapshot"]),
                signature=bytes(row["signature"]),
                url=row["timestamp_authority_url"],
                attempts=row["stamp_attempts"],
            )
            for row in await self._run(tenant_id, work)
        ]

    async def save_decision_stamp(
        self, tenant_id: str, stamp: PendingDecisionStamp, token: bytes, stamped_at: datetime
    ) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                _SAVE_STAMP, uuid.UUID(stamp.verification_id), token, stamped_at
            )

        await self._run(tenant_id, work)

    async def defer_decision_stamp(
        self, tenant_id: str, stamp: PendingDecisionStamp, next_attempt_at: datetime
    ) -> None:
        async def work(connection: asyncpg.Connection) -> None:
            await connection.execute(
                _DEFER_STAMP, uuid.UUID(stamp.verification_id), next_attempt_at
            )

        await self._run(tenant_id, work)


async def _assign_refusal(
    connection: asyncpg.Connection, assignment: NewAssignment, now: datetime, supervisor: bool
) -> Refused | None:
    """Every check under the locks, in the order spec §10.7 gives."""
    subs = sorted({assignment.requester_sub, assignment.reviewer_sub})
    keys = {
        row["user_sub"]: row["key_version"]
        for row in await connection.fetch(_KEYS + " ORDER BY user_sub FOR SHARE", subs)
    }
    if keys.get(assignment.requester_sub) != assignment.requester_key_version:
        return Refused("key_changed")
    if keys.get(assignment.reviewer_sub) != assignment.reviewer_key_version:
        return Refused("reviewer_key_changed")
    conversation = uuid.UUID(assignment.conversation_id)
    found = await connection.fetchrow(
        _ASSIGNABLE, assignment.requester_sub, now, conversation, supervisor
    )
    if found is None:
        return Refused("not_found")
    if await connection.fetchval(_REVIEWER_EXCLUDED, conversation, assignment.reviewer_sub):
        return Refused("reviewer_not_eligible")
    scope = [str(row["key_id"]) for row in await connection.fetch(_SCOPE, conversation)]
    if sorted(wrap.key_id for wrap in assignment.wraps) != scope:
        return Refused("scope_not_covered")
    return None


async def _insert(
    connection: asyncpg.Connection, assignment: NewAssignment, now: datetime
) -> VerificationRow:
    row = await connection.fetchrow(
        _INSERT,
        assignment.tenant_id,
        uuid.UUID(new_verification_id()),
        uuid.UUID(assignment.conversation_id),
        assignment.requester_sub,
        assignment.requester_key_version,
        now,
        assignment.directory_read_at,
        assignment.reviewer_sub,
        assignment.reviewer_key_version,
        assignment.reviewer_fingerprint,
    )
    return verification_from_row(row)


async def _grant(connection: asyncpg.Connection, assignment: NewAssignment, now: datetime) -> None:
    wraps = sorted(assignment.wraps, key=lambda wrap: wrap.key_id)
    await connection.execute(
        _GRANT,
        assignment.tenant_id,
        assignment.reviewer_sub,
        assignment.requester_sub,
        now,
        [uuid.UUID(wrap.key_id) for wrap in wraps],
        [wrap.blob for wrap in wraps],
        [wrap.signature for wrap in wraps],
    )


def _granted_events(
    assignment: NewAssignment, row: VerificationRow, now: datetime
) -> list[AuditEvent]:
    actor, reviewer = assignment.requester_sub, assignment.reviewer_sub
    events = [
        AuditEvent(assignment.tenant_id, actor, "recording.verification.requested", row.ref, now)
    ]
    for key_id in sorted(wrap.key_id for wrap in assignment.wraps):
        events.append(
            AuditEvent(assignment.tenant_id, actor, "key_wrap.granted", f"{key_id}:{reviewer}", now)
        )
    return events


async def locked_record(
    connection: asyncpg.Connection, sub: str, verification_id: str, now: datetime
) -> Refused | VerificationRow:
    """The caller's open record, locked after its conversation; refusals before any write."""
    vid = uuid.UUID(verification_id)
    conversation = await connection.fetchval(_RECORD_OF, vid, sub)
    if conversation is None:
        return Refused("verification_not_found")
    await connection.execute(_CONVERSATION_SHARED, conversation)
    record = verification_from_row(await connection.fetchrow(_RECORD_LOCKED, vid))
    if record.status not in OPEN:
        return Refused("verification_closed")
    if not await connection.fetchval(_STILL_REVIEWING, conversation, sub, now):
        return Refused("verification_closed")  # shredded, past its date, or no wrap left
    return record


async def notes_refusal(
    connection: asyncpg.Connection, record: VerificationRow, notes: Sequence[NotePost]
) -> Refused | None:
    """Each note under its own entry's key, at or before the reviewed head."""
    entries = {
        str(row["entry_id"]): (str(row["key_id"]), row["seq"])
        for row in await connection.fetch(_ENTRIES, uuid.UUID(record.conversation_id))
    }
    head = record.reviewed_head_seq or 0
    for note in notes:
        found = entries.get(note.entry_id)
        if found is None or found[0] != note.key_id or found[1] > head:
            return Refused("bad_notes")
    return None


async def put_notes(
    connection: asyncpg.Connection,
    tenant_id: str,
    record: VerificationRow,
    overall: bytes | None,
    notes: Sequence[NotePost],
) -> None:
    vid = uuid.UUID(record.verification_id)
    await connection.execute(_DROP_NOTES, vid)
    await connection.execute(
        _PUT_NOTES,
        tenant_id,
        vid,
        [uuid.UUID(note.entry_id) for note in notes],
        [uuid.UUID(note.key_id) for note in notes],
        [note.ciphertext for note in notes],
    )
    await connection.execute(_PUT_OVERALL, vid, overall)


async def release(connection: asyncpg.Connection, record: VerificationRow) -> list[str]:
    rows = await connection.fetch(RELEASE, uuid.UUID(record.conversation_id), record.reviewer_sub)
    return sorted(str(row["key_id"]) for row in rows)


def released_events(
    tenant_id: str, actor: str, record: VerificationRow, key_ids: Sequence[str], now: datetime
) -> list[AuditEvent]:
    return [
        AuditEvent(tenant_id, actor, "key_wrap.released", f"{key_id}:{record.reviewer_sub}", now)
        for key_id in key_ids
    ]
