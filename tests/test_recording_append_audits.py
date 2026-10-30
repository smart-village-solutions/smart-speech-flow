"""Many audit events under one lock still make one unbroken chain (spec §9.6, §11.4)."""

from __future__ import annotations

from datetime import datetime, timezone

from services.api_gateway.recording.audit import GENESIS, AuditEvent, AuditRow, chain_is_intact
from services.api_gateway.recording.repository import append_audit, append_audits

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)


class Recording:
    """Counts advisory locks, answers the head, keeps what was inserted."""

    def __init__(self, head: dict | None) -> None:
        self.head = head
        self.locks = 0
        self.inserted: list[tuple] = []

    async def execute(self, query, *args):
        if "pg_advisory_xact_lock" in query:
            self.locks += 1

    async def fetchrow(self, query, *args):
        return self.head

    async def executemany(self, query, rows):
        assert "INSERT INTO audit_events" in query
        self.inserted.extend(rows)


def _events(count: int) -> list[AuditEvent]:
    return [AuditEvent("t", "sam", f"e{i}", f"r{i}", NOW) for i in range(count)]


async def test_many_events_take_one_lock_and_continue_the_chain():
    head = {"seq": 4, "hash": b"\x01" * 32}
    connection = Recording(head)
    events = _events(3)

    await append_audits(connection, events)

    assert connection.locks == 1
    rows = connection.inserted
    assert [row[1] for row in rows] == [5, 6, 7]
    assert rows[0][6] == b"\x01" * 32
    chained = [AuditRow(event, row[1], row[6], row[7]) for event, row in zip(events, rows)]
    # A chain that starts mid-way is intact once its first link is the head's hash.
    assert all(later.prev_hash == earlier.hash for earlier, later in zip(chained, chained[1:]))


async def test_a_first_batch_starts_at_genesis_and_is_intact():
    connection = Recording(None)
    events = _events(5)

    await append_audits(connection, events)

    rows = [AuditRow(e, r[1], r[6], r[7]) for e, r in zip(events, connection.inserted)]
    assert rows[0].seq == 1 and rows[0].prev_hash == GENESIS
    assert chain_is_intact(rows)


async def test_no_events_take_no_lock():
    connection = Recording(None)
    await append_audits(connection, [])
    assert connection.locks == 0 and connection.inserted == []


async def test_one_event_goes_the_same_way():
    connection = Recording(None)
    await append_audit(connection, _events(1)[0])
    assert connection.locks == 1 and len(connection.inserted) == 1
