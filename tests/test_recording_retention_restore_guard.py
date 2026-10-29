"""The restore guard: a database behind the worker's audit marks halts destructive steps."""

from __future__ import annotations

import stat

from services.api_gateway.recording.retention.restore_guard import (
    STATE_FILE,
    AuditHighWater,
    AuditMark,
)

A1, A3, B2 = AuditMark(1, "a1"), AuditMark(3, "a3"), AuditMark(2, "b2")


def _observe(path, behind=False, latest=None) -> bool:
    with AuditHighWater(path).locked() as guard:
        return guard.observe(behind, latest or {})


def test_marks_advance_while_the_database_keeps_up(tmp_path):
    assert _observe(tmp_path, latest={"a": A1}) is False
    assert _observe(tmp_path, latest={"a": A3, "b": B2}) is False
    with AuditHighWater(tmp_path).locked() as guard:
        assert guard.marks == {"a": A3, "b": B2}
        assert guard.recheck == set()


def test_a_database_behind_halts_for_good_and_marks_every_tenant_for_a_re_read(tmp_path):
    _observe(tmp_path, latest={"a": A3, "b": B2})
    assert _observe(tmp_path, behind=True, latest={"a": A1, "c": AuditMark(1, "c1")}) is True
    # Halted marks stay as they were: the next pass compares against the same events.
    assert _observe(tmp_path, latest={"a": AuditMark(9, "a9")}) is True
    with AuditHighWater(tmp_path).locked() as guard:
        assert guard.marks == {"a": A3, "b": B2}
        assert guard.recheck == {"a", "b", "c"}
        guard.rechecked("b")
    with AuditHighWater(tmp_path).locked() as guard:
        assert guard.recheck == {"a", "c"}


def test_an_acknowledgement_resumes_and_survives_the_running_loop(tmp_path):
    running = AuditHighWater(tmp_path)  # the loop's guard, built once
    with running.locked() as guard:
        guard.observe(False, {"a": A3})
    with running.locked() as guard:
        assert guard.observe(True, {"a": A1}) is True

    with AuditHighWater(tmp_path).locked() as guard:  # acknowledge-restore, another process
        guard.acknowledge({"a": A1})

    with running.locked() as guard:
        assert guard.observe(False, {"a": AuditMark(2, "a2")}) is False
        assert guard.marks == {"a": AuditMark(2, "a2")}
        assert guard.recheck == set()


def test_an_unreadable_state_halts_and_re_reads_every_tenant(tmp_path):
    (tmp_path / STATE_FILE).write_text("{not json")
    assert _observe(tmp_path, latest={"a": A1, "b": B2}) is True
    with AuditHighWater(tmp_path).locked() as guard:
        assert guard.recheck == {"a", "b"}
    for text in (
        '{"marks": [], "halted": false}',
        '{"marks": {"a": {"seq": "x", "hash": "h"}}, "halted": false}',
        '{"marks": {"a": {"seq": 1, "hash": "h"}}, "halted": "no"}',
        '{"marks": {"a": {"seq": 1}}, "halted": false}',
    ):
        (tmp_path / STATE_FILE).write_text(text)
        assert AuditHighWater(tmp_path).halted is True, text


def test_the_state_is_private_to_the_worker(tmp_path):
    _observe(tmp_path / "state", latest={"a": A1})
    assert stat.S_IMODE((tmp_path / "state" / STATE_FILE).stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "state").stat().st_mode) == 0o700
    assert [path.name for path in (tmp_path / "state").iterdir() if path.suffix == ".tmp"] == []
