"""Repository behaviour against a real PostgreSQL instance.

These run as `ssf_feedback_maintenance`, which is the role production uses for
every path exercised here: claiming a backlog, expiring rows, and the advisory
lock are all deployment-wide, with no tenant to bind them to. Tenant isolation
under the request-path role lives in test_feedback_row_level_security.py, which
is where the policy itself is proven.

Cleanup runs as the owner because neither application role can TRUNCATE, which
is deliberate -- see migration 002.

Marked integration: these need the database from deploy/postgres. Run with
    docker compose up -d ssf-postgres
    SSF_FEEDBACK_MAINTENANCE_DATABASE_URL=postgresql://... \
    SSF_FEEDBACK_OWNER_DATABASE_URL=postgresql://... \
    pytest tests/integration/test_feedback_repository.py --run-integration

Without --run-integration they skip, which looks like a pass. Check the count.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import asyncpg
import pytest

from services.api_gateway.feedback.models import AnalyticsState, FeedbackRecord
from services.api_gateway.feedback.repository import (
    FeedbackStorageUnavailable,
    PostgresFeedbackRepository,
)

pytestmark = pytest.mark.integration

DSN = os.environ.get("SSF_FEEDBACK_MAINTENANCE_DATABASE_URL", "")
APP_DSN = os.environ.get("SSF_FEEDBACK_DATABASE_URL", "")
OWNER_DSN = os.environ.get("SSF_FEEDBACK_OWNER_DATABASE_URL", "")

# Passed beside the DSN, exactly as the gateway passes it, so CI can use a
# password that a URL cannot carry. See PostgresFeedbackRepository.create.
PASSWORD = os.environ.get("SSF_FEEDBACK_MAINTENANCE_DATABASE_PASSWORD") or None
APP_PASSWORD = os.environ.get("SSF_FEEDBACK_DATABASE_PASSWORD") or None
OWNER_PASSWORD = os.environ.get("SSF_FEEDBACK_OWNER_DATABASE_PASSWORD") or None


def _record(**overrides: object) -> FeedbackRecord:
    now = datetime.now(timezone.utc)
    defaults = dict(
        feedback_id=uuid4(),
        tenant_id="tenant-a",
        session_ref="a" * 32,
        translation_quality=4,
        performance=5,
        usability=3,
        net_promoter_score=9,
        improvements_ciphertext=b"\x01ciphertext-bytes",
        form_version="v1",
        retention_policy_version="v1-12-months",
        consent_snapshot={"form_version": "v1", "manifestation": "form_submission"},
        analytics_event_id=uuid4(),
        analytics_state=AnalyticsState.PENDING,
        created_at=now,
        expires_at=now + timedelta(days=365),
    )
    defaults.update(overrides)
    return FeedbackRecord(**defaults)


@pytest.fixture
async def repository():
    owner = await asyncpg.connect(dsn=OWNER_DSN, password=OWNER_PASSWORD)
    try:
        await owner.execute("TRUNCATE feedback, feedback_deletion_audit")
    finally:
        await owner.close()
    repo = await PostgresFeedbackRepository.create(dsn=DSN, password=PASSWORD)
    yield repo
    await repo.close()


async def _store(record: FeedbackRecord) -> None:
    """Seed through the role that inserts in production.

    The maintenance role has no INSERT grant -- deliberately, see migration 002
    -- so seeding cannot go through the repository under test. Writing as the
    app role instead makes these tests prove the handover they depend on: one
    role stores the submission, another claims and expires it.
    """
    repo = await PostgresFeedbackRepository.create(dsn=APP_DSN, password=APP_PASSWORD)
    try:
        await repo.store(record)
    finally:
        await repo.close()


async def _audit_rows(query: str, *args: object):
    """Read an audit table as the owner.

    The maintenance role holds INSERT on the audit tables and no SELECT, which
    is the privilege production wants -- the job records a deletion, it never
    reads the record back. So the assertion needs the owner.
    """
    owner = await asyncpg.connect(dsn=OWNER_DSN, password=OWNER_PASSWORD)
    try:
        return await owner.fetch(query, *args)
    finally:
        await owner.close()


async def test_a_stored_record_can_be_claimed_for_analytics(repository) -> None:
    record = _record()

    await _store(record)
    pending = await repository.claim_pending_analytics(limit=100)

    assert record.feedback_id in {row.feedback_id for row in pending}


async def test_the_claimed_row_carries_the_stored_event_id(repository) -> None:
    """The reconciler re-emits this id; a fresh one would double-count."""
    record = _record()

    await _store(record)
    pending = await repository.claim_pending_analytics(limit=100)
    row = next(r for r in pending if r.feedback_id == record.feedback_id)

    assert row.analytics_event_id == record.analytics_event_id


async def test_claimed_rows_carry_no_ciphertext(repository) -> None:
    """The reconciler must be structurally unable to read free text."""
    await _store(_record())

    pending = await repository.claim_pending_analytics(limit=100)

    assert pending
    for row in pending:
        assert not hasattr(row, "improvements_ciphertext")


async def test_marking_delivered_removes_it_from_the_backlog(repository) -> None:
    record = _record()
    await _store(record)

    await repository.mark_analytics_delivered(record.feedback_id, record.tenant_id)
    pending = await repository.claim_pending_analytics(limit=100)

    assert record.feedback_id not in {row.feedback_id for row in pending}


async def test_a_not_applicable_row_is_not_a_backlog(repository) -> None:
    """Telemetry switched off must not accumulate work nothing will drain."""
    record = _record()
    await _store(record)

    await repository.mark_analytics_state(
        record.feedback_id, AnalyticsState.NOT_APPLICABLE, record.tenant_id
    )
    pending = await repository.claim_pending_analytics(limit=100)

    assert record.feedback_id not in {row.feedback_id for row in pending}


async def test_expired_rows_are_deleted(repository) -> None:
    now = datetime.now(timezone.utc)
    record = _record(expires_at=now - timedelta(seconds=1))
    await _store(record)

    deleted = await repository.delete_expired(now=now, limit=100)

    assert record.feedback_id in deleted


async def test_what_is_still_overdue_is_countable_after_a_pass(repository) -> None:
    """The number the retention alert needs.

    A deletion counter alone cannot tell a deployment with nothing to delete
    from a maintenance role that can no longer see anything to delete. Both
    report zero deletions and success forever.
    """
    now = datetime.now(timezone.utc)
    for _ in range(3):
        await _store(_record(expires_at=now - timedelta(seconds=1)))
    await _store(_record(expires_at=now + timedelta(days=365)))

    assert await repository.count_expired(now) == 3

    await repository.delete_expired(now=now, limit=1)

    assert await repository.count_expired(now) == 2


async def test_deletion_writes_a_content_free_audit_row(repository) -> None:
    now = datetime.now(timezone.utc)
    record = _record(expires_at=now - timedelta(seconds=1))
    await _store(record)

    await repository.delete_expired(now=now, limit=100)

    rows = await _audit_rows(
        "SELECT * FROM feedback_deletion_audit WHERE feedback_id = $1",
        record.feedback_id,
    )
    row = rows[0] if rows else None

    assert row is not None
    assert row["reason"] == "retention_expiry"
    assert "improvements" not in dict(row)


async def test_unexpired_rows_survive(repository) -> None:
    """An off-by-one here deletes live feedback, so it is guarded separately."""
    now = datetime.now(timezone.utc)
    record = _record(expires_at=now + timedelta(days=1))
    await _store(record)

    deleted = await repository.delete_expired(now=now, limit=100)

    assert record.feedback_id not in deleted


async def test_a_row_at_exactly_its_expiry_is_deleted(repository) -> None:
    """The boundary the twelve-month promise is measured against."""
    now = datetime.now(timezone.utc)
    record = _record(expires_at=now)
    await _store(record)

    deleted = await repository.delete_expired(now=now, limit=100)

    assert record.feedback_id in deleted


async def test_a_constraint_violation_does_not_leak_the_row(repository) -> None:
    """A PostgreSQL error DETAIL carries the entire failing row."""
    sentinel = b"\x01SENTINEL-PURPLE-RHINOCEROS"
    record = _record(translation_quality=99, improvements_ciphertext=sentinel)

    with pytest.raises(FeedbackStorageUnavailable) as caught:
        await _store(record)

    assert b"SENTINEL" not in str(caught.value).encode()
    assert "SENTINEL" not in repr(caught.value)


async def test_an_unreachable_database_is_reported_as_unavailable() -> None:
    """The caller needs a retryable signal, not an asyncpg internal."""
    with pytest.raises((FeedbackStorageUnavailable, OSError)):
        repo = await PostgresFeedbackRepository.create(
            dsn="postgresql://nobody:nobody@127.0.0.1:1/nothing"
        )
        await repo.store(_record())


# --- #305: the advisory lock ------------------------------------------------
#
# The lock cannot be proven with a fake repository: the whole point is what
# PostgreSQL does when two connections ask for the same key at once. These
# hold a real second connection to make the contention real.


async def test_a_second_replica_cannot_delete_while_the_first_holds_the_lock(
    repository,
) -> None:
    """Two replicas run the same hourly pass; only one may delete."""
    from services.api_gateway.feedback.maintenance import RETENTION_LOCK_KEY
    from services.api_gateway.feedback.repository import RetentionLockUnavailable

    now = datetime.now(timezone.utc)
    await _store(_record(expires_at=now - timedelta(days=1)))

    async with repository._pool.acquire() as holder:  # noqa: SLF001
        async with holder.transaction():
            acquired = await holder.fetchval(
                "SELECT pg_try_advisory_xact_lock($1)", RETENTION_LOCK_KEY
            )
            assert acquired is True

            with pytest.raises(RetentionLockUnavailable):
                await repository.delete_expired(now, 100, RETENTION_LOCK_KEY)

    # The holder's transaction has ended, so the lock is gone with it.
    deleted = await repository.delete_expired(now, 100, RETENTION_LOCK_KEY)
    assert len(deleted) == 1


async def test_no_advisory_lock_survives_a_completed_pass(repository) -> None:
    """Consecutive passes must both delete.

    This does NOT distinguish pg_try_advisory_xact_lock from the session-level
    form: asyncpg's pool reset ends in pg_advisory_unlock_all(), so both pass
    here. It was watched passing against both. What it does catch is a lock
    that is taken and never released -- the failure that stops retention dead
    after the first hour.
    """
    from services.api_gateway.feedback.maintenance import RETENTION_LOCK_KEY

    now = datetime.now(timezone.utc)
    await _store(_record(expires_at=now - timedelta(days=1)))
    await repository.delete_expired(now, 100, RETENTION_LOCK_KEY)

    async with repository._pool.acquire() as connection:  # noqa: SLF001
        held = await connection.fetchval(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
        )
    assert held == 0

    await _store(_record(expires_at=now - timedelta(days=1)))
    assert len(await repository.delete_expired(now, 100, RETENTION_LOCK_KEY)) == 1


async def test_deleting_without_a_lock_key_still_works(repository) -> None:
    """The parameter is optional so #302's callers are unchanged."""
    now = datetime.now(timezone.utc)
    await _store(_record(expires_at=now - timedelta(days=1)))

    assert len(await repository.delete_expired(now, 100)) == 1


async def test_the_deletion_audit_survives_the_row_it_describes(repository) -> None:
    now = datetime.now(timezone.utc)
    record = _record(expires_at=now - timedelta(days=1))
    await _store(record)

    await repository.delete_expired(now, 100, RETENTION_LOCK_KEY := 0x55F_FEED)

    rows = await _audit_rows("SELECT * FROM feedback_deletion_audit")
    remaining = (await _audit_rows("SELECT count(*) AS n FROM feedback"))[0]["n"]

    assert remaining == 0
    assert len(rows) == 1
    assert rows[0]["feedback_id"] == record.feedback_id
    assert rows[0]["reason"] == "retention_expiry"
    # Content-free by construction: no column could hold the text.
    assert "improvements_ciphertext" not in rows[0].keys()


async def test_a_full_reconciliation_pass_recovers_a_pending_row(repository) -> None:
    """The reconciler against the real store, not a fake."""
    from prometheus_client import CollectorRegistry

    from services.api_gateway.feedback.maintenance import (
        FeedbackMaintenance,
        FeedbackMaintenanceMetrics,
    )
    from services.api_gateway.quality_telemetry import QualityTelemetry, TelemetryMode

    record = _record()
    await _store(record)

    exported: list = []
    maintenance = FeedbackMaintenance(
        repository=repository,
        telemetry=QualityTelemetry(
            mode=TelemetryMode.ENABLED,
            exporter=lambda name, attributes, at: exported.append((name, dict(attributes))),
            registry=CollectorRegistry(),
        ),
        metrics=FeedbackMaintenanceMetrics(CollectorRegistry()),
    )

    first = await maintenance.reconcile_once()
    assert first.recovered == 1
    assert exported[0][1]["ssf.quality.event_id"] == str(record.analytics_event_id)

    # Delivered rows must not be claimed again, or every pass re-emits forever.
    second = await maintenance.reconcile_once()
    assert second.recovered == 0
    assert len(exported) == 1


async def test_the_reconciler_never_reads_the_ciphertext_column(repository) -> None:
    """Structural, not careful: the claim query has no such column."""
    from services.api_gateway.feedback.repository import _CLAIM_PENDING, PendingAnalytics

    await _store(_record(improvements_ciphertext=b"\x01SENTINEL-BYTES"))
    pending = await repository.claim_pending_analytics(limit=10)

    assert "improvements" not in _CLAIM_PENDING
    # slots=True, so there is no __dict__ to walk: read the declared fields.
    values = [getattr(pending[0], f) for f in PendingAnalytics.__dataclass_fields__]
    assert not any("SENTINEL" in str(value) for value in values)
