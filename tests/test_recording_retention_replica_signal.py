"""The worker store's replica-sync signal over a scripted connection, for the unit run (#626).

The database behaviour itself is proven in
tests/integration/test_recording_retention_store.py.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from services.api_gateway.recording.retention.decisions_repository import (
    PostgresRetentionDecisions,
)
from services.api_gateway.recording.retention.metrics import WorkerStatus
from services.api_gateway.recording.retention.store import (
    BACKOFF_CEILING,
    UNREAD_BACKOFF_CEILING,
    PostgresRetentionStore,
)
from tests.recording_retention_fakes import NOW, TENANT, due_row
from tests.test_recording_archive_access_repository import ScriptedConnection, ScriptedPool


class CapturingConnection(ScriptedConnection):
    """Also keeps each query's arguments."""

    def __init__(self, answers: dict[str, object]) -> None:
        super().__init__(answers)
        self.arguments: list[tuple] = []

    async def execute(self, query, *args):
        self.arguments.append(args)
        return await super().execute(query, *args)

    async def fetchval(self, query, *args):
        self.arguments.append(args)
        return await super().fetchval(query, *args)


def _store(answers=None, site="replica"):
    connection = CapturingConnection(answers or {})
    return PostgresRetentionStore(ScriptedPool(connection), site), connection


@pytest.mark.parametrize(
    # The replica waits for its sync's copies; on the primary a missing version is a loss.
    ("site", "unread"),
    [("replica", UNREAD_BACKOFF_CEILING), ("primary", BACKOFF_CEILING)],
)
async def test_the_ceiling_for_a_version_never_read_depends_on_the_site(site, unread):
    store, connection = _store(site=site)
    await store.record_failure(due_row(checked_at=None), NOW)
    arguments = connection.arguments[-1]
    assert (arguments[6], arguments[11]) == (BACKOFF_CEILING, unread)


def test_the_unread_ceiling_is_well_inside_the_alerts_half_hour():
    assert UNREAD_BACKOFF_CEILING <= timedelta(minutes=15) < BACKOFF_CEILING


async def test_unconfirmed_since_reads_this_sites_unread_rows_for_the_tenant():
    since = NOW - timedelta(hours=1)
    store, connection = _store({"first_read_at IS NULL": since})
    assert await store.unconfirmed_since(TENANT) == since
    assert connection.arguments[-1] == ("replica",)
    assert any("set_config" in call for call in connection.calls)


async def test_the_beat_carries_unconfirmed_since():
    store, connection = _store()
    await store.beat(NOW, 0.0, False, 0, NOW - timedelta(minutes=40))
    assert connection.arguments[-1] == ("replica", NOW, 0.0, False, 0, NOW - timedelta(minutes=40))
    assert "unconfirmed_since = EXCLUDED.unconfirmed_since" in connection.calls[-1]


async def test_the_gateway_reads_unconfirmed_since_with_each_heartbeat():
    row = {
        "site": "replica",
        "beat_at": NOW,
        "failing_seconds": 0.0,
        "halted": False,
        "hold_mismatches": 0,
        "unconfirmed_since": NOW - timedelta(hours=1),
    }
    connection = ScriptedConnection({"FROM retention_worker_status": [row]})
    statuses = await PostgresRetentionDecisions(ScriptedPool(connection)).worker_statuses()
    assert statuses == [WorkerStatus(**row)]
    assert "unconfirmed_since" in connection.calls[-1]
