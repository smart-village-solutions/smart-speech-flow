"""Repository behaviour against a real PostgreSQL instance.

Marked integration: these need the database from deploy/postgres. Run with
    docker compose up -d ssf-postgres
    SSF_FEEDBACK_DATABASE_URL=postgresql://... pytest tests/integration/test_feedback_repository.py --run-integration

Without --run-integration they skip, which looks like a pass. Check the count.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from services.api_gateway.feedback.models import AnalyticsState, FeedbackRecord
from services.api_gateway.feedback.repository import (
    FeedbackStorageUnavailable,
    PostgresFeedbackRepository,
)

pytestmark = pytest.mark.integration

DSN = os.environ.get("SSF_FEEDBACK_DATABASE_URL", "")


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
    repo = await PostgresFeedbackRepository.create(dsn=DSN)
    async with repo._pool.acquire() as connection:  # noqa: SLF001 - test cleanup
        await connection.execute("TRUNCATE feedback, feedback_deletion_audit")
    yield repo
    await repo.close()


async def test_a_stored_record_can_be_claimed_for_analytics(repository) -> None:
    record = _record()

    await repository.store(record)
    pending = await repository.claim_pending_analytics(limit=100)

    assert record.feedback_id in {row.feedback_id for row in pending}


async def test_the_claimed_row_carries_the_stored_event_id(repository) -> None:
    """The reconciler re-emits this id; a fresh one would double-count."""
    record = _record()

    await repository.store(record)
    pending = await repository.claim_pending_analytics(limit=100)
    row = next(r for r in pending if r.feedback_id == record.feedback_id)

    assert row.analytics_event_id == record.analytics_event_id


async def test_claimed_rows_carry_no_ciphertext(repository) -> None:
    """The reconciler must be structurally unable to read free text."""
    await repository.store(_record())

    pending = await repository.claim_pending_analytics(limit=100)

    assert pending
    for row in pending:
        assert not hasattr(row, "improvements_ciphertext")


async def test_marking_delivered_removes_it_from_the_backlog(repository) -> None:
    record = _record()
    await repository.store(record)

    await repository.mark_analytics_delivered(record.feedback_id, record.tenant_id)
    pending = await repository.claim_pending_analytics(limit=100)

    assert record.feedback_id not in {row.feedback_id for row in pending}


async def test_a_not_applicable_row_is_not_a_backlog(repository) -> None:
    """Telemetry switched off must not accumulate work nothing will drain."""
    record = _record()
    await repository.store(record)

    await repository.mark_analytics_state(
        record.feedback_id, AnalyticsState.NOT_APPLICABLE, record.tenant_id
    )
    pending = await repository.claim_pending_analytics(limit=100)

    assert record.feedback_id not in {row.feedback_id for row in pending}


async def test_expired_rows_are_deleted(repository) -> None:
    now = datetime.now(timezone.utc)
    record = _record(expires_at=now - timedelta(seconds=1))
    await repository.store(record)

    deleted = await repository.delete_expired(now=now, limit=100)

    assert record.feedback_id in deleted


async def test_deletion_writes_a_content_free_audit_row(repository) -> None:
    now = datetime.now(timezone.utc)
    record = _record(expires_at=now - timedelta(seconds=1))
    await repository.store(record)

    await repository.delete_expired(now=now, limit=100)

    async with repository._pool.acquire() as connection:  # noqa: SLF001
        row = await connection.fetchrow(
            "SELECT * FROM feedback_deletion_audit WHERE feedback_id = $1",
            record.feedback_id,
        )

    assert row is not None
    assert row["reason"] == "retention_expiry"
    assert "improvements" not in dict(row)


async def test_unexpired_rows_survive(repository) -> None:
    """An off-by-one here deletes live feedback, so it is guarded separately."""
    now = datetime.now(timezone.utc)
    record = _record(expires_at=now + timedelta(days=1))
    await repository.store(record)

    deleted = await repository.delete_expired(now=now, limit=100)

    assert record.feedback_id not in deleted


async def test_a_row_at_exactly_its_expiry_is_deleted(repository) -> None:
    """The boundary the twelve-month promise is measured against."""
    now = datetime.now(timezone.utc)
    record = _record(expires_at=now)
    await repository.store(record)

    deleted = await repository.delete_expired(now=now, limit=100)

    assert record.feedback_id in deleted


async def test_a_constraint_violation_does_not_leak_the_row(repository) -> None:
    """A PostgreSQL error DETAIL carries the entire failing row."""
    sentinel = b"\x01SENTINEL-PURPLE-RHINOCEROS"
    record = _record(translation_quality=99, improvements_ciphertext=sentinel)

    with pytest.raises(FeedbackStorageUnavailable) as caught:
        await repository.store(record)

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
    await repository.store(_record(expires_at=now - timedelta(days=1)))

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
    await repository.store(_record(expires_at=now - timedelta(days=1)))
    await repository.delete_expired(now, 100, RETENTION_LOCK_KEY)

    async with repository._pool.acquire() as connection:  # noqa: SLF001
        held = await connection.fetchval(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
        )
    assert held == 0

    await repository.store(_record(expires_at=now - timedelta(days=1)))
    assert len(await repository.delete_expired(now, 100, RETENTION_LOCK_KEY)) == 1


async def test_deleting_without_a_lock_key_still_works(repository) -> None:
    """The parameter is optional so #302's callers are unchanged."""
    now = datetime.now(timezone.utc)
    await repository.store(_record(expires_at=now - timedelta(days=1)))

    assert len(await repository.delete_expired(now, 100)) == 1


async def test_the_deletion_audit_survives_the_row_it_describes(repository) -> None:
    now = datetime.now(timezone.utc)
    record = _record(expires_at=now - timedelta(days=1))
    await repository.store(record)

    await repository.delete_expired(now, 100, RETENTION_LOCK_KEY := 0x55F_FEED)

    async with repository._pool.acquire() as connection:  # noqa: SLF001
        rows = await connection.fetch("SELECT * FROM feedback_deletion_audit")
        remaining = await connection.fetchval("SELECT count(*) FROM feedback")

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
    await repository.store(record)

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

    await repository.store(_record(improvements_ciphertext=b"\x01SENTINEL-BYTES"))
    pending = await repository.claim_pending_analytics(limit=10)

    assert "improvements" not in _CLAIM_PENDING
    # slots=True, so there is no __dict__ to walk: read the declared fields.
    values = [getattr(pending[0], f) for f in PendingAnalytics.__dataclass_fields__]
    assert not any("SENTINEL" in str(value) for value in values)
