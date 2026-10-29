"""In-memory stand-ins for the retention worker's database and a failing archive store."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.retention.decisions import RetentionRefusedError
from services.api_gateway.recording.retention.restore_guard import AuditMark
from services.api_gateway.recording.retention.store import DueVersion, LockState
from services.api_gateway.recording.storage.archive import object_key

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
TENANT = "tenant-a"
CONVERSATION = "0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a"
ENTRY = "1e7d3c2b-0f9e-4e8d-a7b6-5a4f3e2d1c0b"
KEY = object_key(CONVERSATION, ENTRY, "record.json")


def due_row(**changes) -> DueVersion:
    base = DueVersion(
        tenant_id=TENANT,
        conversation_id=CONVERSATION,
        entry_id=ENTRY,
        object_type="record.json",
        version_id="v1",
        key=KEY,
        checked_at=NOW - timedelta(days=1),
        locked_until=NOW + timedelta(days=31),
        held=False,
        held_since=None,
        attempts=0,
        next_attempt_at=NOW,
        retention_until=NOW + timedelta(days=30),
        legal_hold=False,
        shredded_at=None,
        hold_on_at=None,
        hold_off_at=None,
    )
    return dataclasses.replace(base, **changes)


class FakeRetentionStore:
    """Due rows and the worker's bookkeeping, as PostgresRetentionStore keeps them."""

    def __init__(self, *rows: DueVersion, positions: dict[str, int] | None = None) -> None:
        self.rows = {row.version_id: row for row in rows}
        # Each tenant's audit chain as its hashes, oldest first.
        self.audit = {
            tenant: [f"{tenant}:{seq}" for seq in range(1, count + 1)]
            for tenant, count in (positions if positions is not None else {TENANT: 1}).items()
        }
        self.rechecked: list[str] = []
        self.recorded: dict[str, tuple[LockState, datetime]] = {}
        self.failed: list[str] = []
        self.failing: dict[str, datetime] = {}
        self.discovered: list[str] = []
        self.beats: list[tuple[datetime, float, bool, int]] = []
        self.unavailable: set[str] = set()
        self.calls = 0
        self.closed = False
        self.conversations: dict[str, dict[str, bool]] = {}
        self.hold_arrives: set[str] = set()
        self.shred_actors: list[str] = []
        self.cleared: set[str] = set()
        self.cleared_elsewhere: set[str] = set()
        self.rows_deleted: list[str] = []
        self.steps: list[str] = []
        self.erased: list[tuple[str, str, str, str]] = []
        self.erase_refusals: dict[str, str] = {}
        self.conflicts: dict[str, list[tuple[str, str]]] = {}

    def restore(self, tenant_id: str, count: int) -> None:
        """The tenant's chain as a dump restored it: count events, then others than before."""
        kept = self.audit[tenant_id][:count]
        self.audit[tenant_id] = kept + [f"{tenant_id}:restored:{n}" for n in range(1, 4)]

    async def tenants(self) -> list[str]:
        return sorted(self.audit)

    async def audit_mark(self, tenant_id: str) -> AuditMark | None:
        chain = self.audit.get(tenant_id, [])
        return AuditMark(len(chain), chain[-1]) if chain else None

    async def audit_hash_at(self, tenant_id: str, seq: int) -> str | None:
        chain = self.audit.get(tenant_id, [])
        return chain[seq - 1] if 1 <= seq <= len(chain) else None

    async def recheck_all(self, tenant_id: str, now: datetime) -> None:
        self.rechecked.append(tenant_id)
        for version, row in list(self.rows.items()):
            if row.tenant_id == tenant_id:
                self.rows[version] = dataclasses.replace(row, checked_at=None, next_attempt_at=now)

    async def hold_mismatches(self, tenant_id: str) -> int:
        return sum(
            1
            for row in self.rows.values()
            if row.tenant_id == tenant_id
            and row.held
            and not row.legal_hold
            and not (row.hold_off_at and row.held_since and row.hold_off_at > row.held_since)
        )

    async def discover(self, tenant_id: str, now: datetime) -> int:
        if tenant_id in self.unavailable:
            raise RecordingStorageUnavailable("the recording database is unavailable")
        self.discovered.append(tenant_id)
        return 0

    async def due_versions(self, tenant_id, now, limit=200):
        self.calls += 1
        due = [
            row
            for row in self.rows.values()
            if row.tenant_id == tenant_id and row.next_attempt_at <= now
        ]
        return due[:limit]

    async def record(self, row, state, revisit_at):
        self.recorded[row.version_id] = (state, revisit_at)
        self.failing.pop(row.version_id, None)
        self.rows[row.version_id] = dataclasses.replace(
            row,
            checked_at=state.checked_at,
            locked_until=state.locked_until,
            held=state.held,
            held_since=state.held_since,
            next_attempt_at=revisit_at,
        )
        if state.deleted_at is not None:
            del self.rows[row.version_id]

    async def record_failure(self, row, now):
        self.failed.append(row.version_id)
        self.failing.setdefault(row.version_id, now)
        self.rows[row.version_id] = dataclasses.replace(
            row, next_attempt_at=now + timedelta(minutes=1)
        )

    async def overdue_since(self, tenant_id, now):
        moments = [
            self.failing.get(version, row.next_attempt_at)
            for version, row in self.rows.items()
            if row.tenant_id == tenant_id
            and (version in self.failing or row.next_attempt_at <= now)
        ]
        return min(moments, default=None)

    async def beat(self, now, failing_seconds, halted, hold_mismatches):
        self.beats.append((now, failing_seconds, halted, hold_mismatches))

    async def close(self) -> None:
        self.closed = True

    # Expiry: conversations by ID, with what the primary and the other site did.
    def conversation(self, conversation_id: str, *, due=False, shredded=False) -> None:
        self.conversations[conversation_id] = {"due": due, "shredded": shredded}

    async def due_expiries(self, tenant_id, now):
        self.steps.append("due_expiries")
        held = {row.conversation_id for row in self.rows.values() if row.held}
        return [
            cid
            for cid, c in self.conversations.items()
            if c["due"] and not c["shredded"] and cid not in held
        ]

    async def shred(self, tenant_id, conversation_id, now, actor):
        if conversation_id in self.hold_arrives:
            return False
        self.conversations[conversation_id]["shredded"] = True
        self.shred_actors.append(actor)
        return True

    async def clearable(self, tenant_id):
        self.steps.append("clearable")
        tracked = {row.conversation_id for row in self.rows.values()}
        return [
            cid
            for cid, c in self.conversations.items()
            if c["shredded"] and cid not in self.cleared and cid not in tracked
        ]

    async def record_clearance(self, tenant_id, conversation_id, now):
        self.cleared.add(conversation_id)

    async def deletable(self, tenant_id):
        self.steps.append("deletable")
        return sorted(self.cleared & self.cleared_elsewhere)

    async def delete_rows(self, tenant_id, conversation_id, now):
        del self.conversations[conversation_id]
        self.rows_deleted.append(conversation_id)
        return True

    async def erase(self, tenant_id, conversation_id, now, operator, reason):
        code = self.erase_refusals.get(conversation_id)
        if code is not None:
            raise RetentionRefusedError(code)
        self.erased.append((tenant_id, conversation_id, operator, reason))
        return f"decision-{len(self.erased)}"

    async def restore_conflicts(self, tenant_id):
        return self.conflicts.get(tenant_id, [])

    async def known_conversations(self, tenant_id):
        self.steps.append("known_conversations")
        return {cid: c["shredded"] for cid, c in self.conversations.items()}


class Failing:
    """An archive store failing one operation with one error, passing the rest through."""

    def __init__(self, inner, operation: str, error: Exception) -> None:
        self._inner, self._operation, self._error = inner, operation, error

    def __getattr__(self, name):
        if name == self._operation:

            async def fail(*args, **kwargs):
                raise self._error

            return fail
        return getattr(self._inner, name)
