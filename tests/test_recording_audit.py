"""The audit chain detects removal, reordering and alteration (spec §11.4, §20)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.recording.audit import (
    GENESIS,
    AuditEvent,
    AuditRow,
    audit_hash,
    chain_is_intact,
)

START = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


def _chain(count: int) -> list[AuditRow]:
    rows, previous = [], GENESIS
    for seq in range(1, count + 1):
        event = AuditEvent(
            "t1", "alice", "key_enrolled", f"user-key:{seq}", START + timedelta(seconds=seq)
        )
        digest = audit_hash(event, seq, previous)
        rows.append(AuditRow(event, seq, previous, digest))
        previous = digest
    return rows


def test_an_untouched_chain_is_intact():
    assert chain_is_intact(_chain(3))


def test_a_removed_row_is_detected():
    rows = _chain(3)
    assert not chain_is_intact([rows[0], rows[2]])


def test_reordered_rows_are_detected():
    rows = _chain(3)
    assert not chain_is_intact([rows[1], rows[0], rows[2]])


def test_an_altered_field_is_detected():
    rows = _chain(3)
    rows[1] = replace(rows[1], event=replace(rows[1].event, actor_sub="mallory"))
    assert not chain_is_intact(rows)


def test_naive_times_are_refused():
    event = AuditEvent("t1", "alice", "key_enrolled", "user-key:1", datetime(2026, 10, 26))
    with pytest.raises(ValueError):
        audit_hash(event, 1, GENESIS)
