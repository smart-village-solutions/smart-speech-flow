"""The reconciler and the retention job (#305).

Both run in every gateway replica, so both must be safe to run concurrently
and safe to run against a database that is momentarily unreachable. Neither
may ever raise into the lifespan task that drives it: a maintenance failure is
a metric, not an outage.

Neither path can carry free text. `PendingAnalytics` has no ciphertext field
and `_CLAIM_PENDING` does not select the column, so the recovery path is
structurally unable to leak the improvement text rather than merely careful.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from prometheus_client import CollectorRegistry

from services.api_gateway.feedback.maintenance import (
    RECONCILIATION_LOCK_KEY,
    RETENTION_LOCK_KEY,
    FeedbackMaintenance,
    FeedbackMaintenanceMetrics,
)
from services.api_gateway.feedback.models import AnalyticsState
from services.api_gateway.feedback.repository import (
    FeedbackStorageUnavailable,
    PendingAnalytics,
    ReconciliationLockUnavailable,
    RetentionLockUnavailable,
)
from services.api_gateway.quality_telemetry import ProbeOutcome, ProbeResult
from services.api_gateway.session_pseudonym import feedback_ref

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _pending(**overrides) -> PendingAnalytics:
    fields = dict(
        feedback_id=uuid4(),
        tenant_id="tenant-a",
        session_ref="c" * 32,
        analytics_event_id=uuid4(),
        translation_quality=4,
        performance=5,
        usability=3,
        net_promoter_score=9,
        form_version="v1",
        created_at=NOW - timedelta(hours=2),
    )
    fields.update(overrides)
    return PendingAnalytics(**fields)


class FakeRepository:
    def __init__(
        self,
        pending: list[PendingAnalytics] | None = None,
        *,
        deleted: list[UUID] | None = None,
        claim_raises: Exception | None = None,
        delete_raises: Exception | None = None,
        overdue: int = 0,
        overdue_raises: Exception | None = None,
        lock_held: bool = False,
    ) -> None:
        self._pending = pending or []
        self._deleted = deleted or []
        self._overdue = overdue
        self._overdue_raises = overdue_raises
        self._lock_held = lock_held
        self.lock_keys: list[int] = []
        self._claim_raises = claim_raises
        self._delete_raises = delete_raises
        self.states: dict[UUID, AnalyticsState] = {}
        self.marked_tenants: dict[UUID, str] = {}
        self.delete_calls: list[dict] = []

    @asynccontextmanager
    async def pass_lock(self, lock_key):
        self.lock_keys.append(lock_key)
        if self._lock_held:
            raise ReconciliationLockUnavailable("another replica holds it")
        yield

    async def claim_pending_analytics(self, limit):
        if self._claim_raises is not None:
            raise self._claim_raises
        return self._pending[:limit]

    async def mark_analytics_delivered(self, feedback_id, tenant_id):
        self.marked_tenants[feedback_id] = tenant_id
        self.states[feedback_id] = AnalyticsState.DELIVERED

    async def mark_analytics_state(self, feedback_id, state, tenant_id):
        self.marked_tenants[feedback_id] = tenant_id
        self.states[feedback_id] = state

    async def delete_expired(self, now, limit, lock_key=None):
        self.delete_calls.append({"now": now, "limit": limit, "lock_key": lock_key})
        if self._delete_raises is not None:
            raise self._delete_raises
        return self._deleted

    async def count_expired(self, now):
        if self._overdue_raises is not None:
            raise self._overdue_raises
        return self._overdue


class FakeTelemetry:
    def __init__(self, outcomes: list[ProbeOutcome] | None = None) -> None:
        self.calls: list[dict] = []
        self._outcomes = outcomes

    def emit_feedback_submitted(self, **kwargs) -> ProbeResult:
        self.calls.append(kwargs)
        if self._outcomes is None:
            outcome = ProbeOutcome.EMITTED
        else:
            outcome = self._outcomes[min(len(self.calls) - 1, len(self._outcomes) - 1)]
        return ProbeResult(outcome, kwargs["event_id"])


def _maintenance(repository, telemetry=None, registry=None):
    return FeedbackMaintenance(
        repository=repository,
        telemetry=telemetry or FakeTelemetry(),
        metrics=FeedbackMaintenanceMetrics(registry or CollectorRegistry()),
        clock=lambda: NOW,
    )


def _value(registry: CollectorRegistry, name: str, **labels) -> float:
    return registry.get_sample_value(name, labels or None) or 0.0


class TestReconciliationRecoversDelivery:
    async def test_a_pending_row_is_re_emitted_and_marked_delivered(self):
        row = _pending()
        repository = FakeRepository([row])
        telemetry = FakeTelemetry()

        result = await _maintenance(repository, telemetry).reconcile_once()

        assert result.recovered == 1
        assert repository.states[row.feedback_id] is AnalyticsState.DELIVERED
        assert telemetry.calls[0]["event_id"] == row.analytics_event_id

    async def test_the_recovered_row_is_marked_under_its_own_tenant(self):
        """The reconciler crosses tenants, so it cannot assume a single one."""
        row = _pending()
        repository = FakeRepository([row])

        await _maintenance(repository, FakeTelemetry()).reconcile_once()

        assert repository.marked_tenants[row.feedback_id] == row.tenant_id

    async def test_it_re_emits_the_stored_event_id_not_a_fresh_one(self):
        """Gold deduplicates on uniqExactState(event_id); a new id double-counts."""
        row = _pending()
        telemetry = FakeTelemetry()

        await _maintenance(FakeRepository([row]), telemetry).reconcile_once()
        await _maintenance(FakeRepository([row]), telemetry).reconcile_once()

        assert telemetry.calls[0]["event_id"] == telemetry.calls[1]["event_id"]
        assert telemetry.calls[0]["event_id"] == row.analytics_event_id

    async def test_it_emits_the_feedback_reference_derived_from_the_row(self):
        row = _pending()
        telemetry = FakeTelemetry()

        await _maintenance(FakeRepository([row]), telemetry).reconcile_once()

        assert telemetry.calls[0]["feedback_ref"] == feedback_ref(row.feedback_id)
        assert telemetry.calls[0]["session_ref"] == row.session_ref

    async def test_a_row_that_fails_again_stays_pending_for_the_next_pass(self):
        row = _pending()
        repository = FakeRepository([row])
        telemetry = FakeTelemetry([ProbeOutcome.EXPORT_FAILED])

        result = await _maintenance(repository, telemetry).reconcile_once()

        assert result.recovered == 0
        assert result.failed == 1
        assert row.feedback_id not in repository.states

    async def test_a_disabled_deployment_drains_the_backlog_rather_than_retrying(self):
        """Nothing will ever deliver these, so they are not a backlog."""
        row = _pending()
        repository = FakeRepository([row])
        telemetry = FakeTelemetry([ProbeOutcome.DISABLED])

        result = await _maintenance(repository, telemetry).reconcile_once()

        assert repository.states[row.feedback_id] is AnalyticsState.NOT_APPLICABLE
        assert result.recovered == 0

    async def test_one_failing_row_does_not_abandon_the_rest_of_the_batch(self):
        first, second = _pending(), _pending()
        repository = FakeRepository([first, second])
        telemetry = FakeTelemetry([ProbeOutcome.EXPORT_FAILED, ProbeOutcome.EMITTED])

        result = await _maintenance(repository, telemetry).reconcile_once()

        assert result.failed == 1
        assert result.recovered == 1
        assert repository.states[second.feedback_id] is AnalyticsState.DELIVERED

    async def test_an_emitter_that_raises_is_contained(self):
        """A raising emitter must not kill the pass or the lifespan task."""
        first, second = _pending(), _pending()

        class Exploding(FakeTelemetry):
            def emit_feedback_submitted(self, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) == 1:
                    raise RuntimeError("collector exploded")
                return ProbeResult(ProbeOutcome.EMITTED, kwargs["event_id"])

        repository = FakeRepository([first, second])
        result = await _maintenance(repository, Exploding()).reconcile_once()

        assert result.failed == 1
        assert result.recovered == 1

    async def test_an_unreachable_database_is_a_metric_not_an_exception(self):
        repository = FakeRepository(claim_raises=FeedbackStorageUnavailable("down"))

        result = await _maintenance(repository).reconcile_once()

        assert result.failed == 0
        assert result.recovered == 0
        assert result.unavailable is True


class TestReconciliationCarriesNoText:
    def test_the_pending_row_has_no_field_that_could_hold_text(self):
        assert not any(
            "ciphertext" in field or "improvement" in field
            for field in PendingAnalytics.__dataclass_fields__
        )

    async def test_no_emitted_attribute_carries_anything_but_the_declared_fields(self):
        row = _pending()
        telemetry = FakeTelemetry()

        await _maintenance(FakeRepository([row]), telemetry).reconcile_once()

        assert set(telemetry.calls[0]) == {
            "event_id",
            "session_ref",
            "feedback_ref",
            "translation_quality",
            "performance",
            "usability",
            "net_promoter_score",
            "form_version",
        }


class TestRetentionDeletesAtExpiry:
    async def test_expired_rows_are_deleted_under_the_advisory_lock(self):
        deleted = [uuid4(), uuid4()]
        repository = FakeRepository(deleted=deleted)

        result = await _maintenance(repository).expire_once()

        assert result.deleted == 2
        assert repository.delete_calls[0]["now"] == NOW
        assert repository.delete_calls[0]["lock_key"] is not None

    async def test_a_replica_that_loses_the_lock_skips_rather_than_double_deleting(self):
        repository = FakeRepository(delete_raises=RetentionLockUnavailable("held"))

        result = await _maintenance(repository).expire_once()

        assert result.skipped is True
        assert result.deleted == 0

    async def test_a_deletion_failure_is_reported_not_raised(self):
        repository = FakeRepository(delete_raises=FeedbackStorageUnavailable("down"))

        result = await _maintenance(repository).expire_once()

        assert result.failed is True
        assert result.deleted == 0

    async def test_an_unexpected_error_is_still_contained(self):
        repository = FakeRepository(delete_raises=RuntimeError("boom"))

        result = await _maintenance(repository).expire_once()

        assert result.failed is True


class TestTheMetricsMakeItObservable:
    async def test_recovered_and_failed_rows_are_counted_separately(self):
        registry = CollectorRegistry()
        repository = FakeRepository([_pending(), _pending()])
        telemetry = FakeTelemetry([ProbeOutcome.EMITTED, ProbeOutcome.EXPORT_FAILED])

        await _maintenance(repository, telemetry, registry).reconcile_once()

        assert _value(registry, "ssf_feedback_reconciliation_total", outcome="recovered") == 1
        assert _value(registry, "ssf_feedback_reconciliation_total", outcome="failed") == 1

    async def test_the_backlog_depth_is_a_gauge_not_a_counter(self):
        """It must fall when the backlog drains, which a counter cannot do."""
        registry = CollectorRegistry()
        metrics = FeedbackMaintenanceMetrics(registry)

        first = FeedbackMaintenance(
            repository=FakeRepository([_pending(), _pending()]),
            telemetry=FakeTelemetry(),
            metrics=metrics,
            clock=lambda: NOW,
        )
        await first.reconcile_once()
        assert _value(registry, "ssf_feedback_reconciliation_backlog") == 2

        second = FeedbackMaintenance(
            repository=FakeRepository([]),
            telemetry=FakeTelemetry(),
            metrics=metrics,
            clock=lambda: NOW,
        )
        await second.reconcile_once()
        assert _value(registry, "ssf_feedback_reconciliation_backlog") == 0

    async def test_deletions_are_counted(self):
        registry = CollectorRegistry()
        repository = FakeRepository(deleted=[uuid4(), uuid4(), uuid4()])

        await _maintenance(repository, None, registry).expire_once()

        assert _value(registry, "ssf_feedback_retention_deleted_total") == 3

    async def test_each_job_reports_its_own_failures(self):
        registry = CollectorRegistry()
        metrics = FeedbackMaintenanceMetrics(registry)

        await FeedbackMaintenance(
            repository=FakeRepository(claim_raises=FeedbackStorageUnavailable("x")),
            telemetry=FakeTelemetry(),
            metrics=metrics,
            clock=lambda: NOW,
        ).reconcile_once()
        await FeedbackMaintenance(
            repository=FakeRepository(delete_raises=FeedbackStorageUnavailable("x")),
            telemetry=FakeTelemetry(),
            metrics=metrics,
            clock=lambda: NOW,
        ).expire_once()

        name = "ssf_feedback_maintenance_failures_total"
        assert _value(registry, name, job="reconciliation") == 1
        assert _value(registry, name, job="retention") == 1

    async def test_a_lock_that_another_replica_holds_is_not_a_failure(self):
        """Every replica but one skips every pass; alerting on it would page nightly."""
        registry = CollectorRegistry()
        repository = FakeRepository(delete_raises=RetentionLockUnavailable("held"))

        await _maintenance(repository, None, registry).expire_once()

        assert _value(registry, "ssf_feedback_maintenance_failures_total", job="retention") == 0

    def test_registering_twice_on_one_registry_does_not_raise(self):
        """The lifespan re-enters per TestClient; prometheus_client raises on
        a duplicate name, and that must never stop the gateway starting."""
        registry = CollectorRegistry()

        FeedbackMaintenanceMetrics(registry)
        FeedbackMaintenanceMetrics(registry)


class TestRetentionReportsWhatItDidNotDelete:
    """A pass that deletes nothing is indistinguishable from one with nothing
    to delete -- unless something counts what is still overdue.

    That is not hypothetical: a maintenance role that loses BYPASSRLS sees no
    rows, deletes none, and reports success on every pass. The deletion counter
    stays at zero either way.
    """

    async def test_a_pass_that_deletes_nothing_reports_the_rows_it_left(self):
        registry = CollectorRegistry()
        repository = FakeRepository(deleted=[], overdue=7)

        await _maintenance(repository, registry=registry).expire_once()

        assert _value(registry, "ssf_feedback_retention_overdue") == 7

    async def test_a_pass_that_clears_the_backlog_reports_nothing_overdue(self):
        registry = CollectorRegistry()
        repository = FakeRepository(deleted=[uuid4(), uuid4()], overdue=0)

        await _maintenance(repository, registry=registry).expire_once()

        assert _value(registry, "ssf_feedback_retention_overdue") == 0
        assert _value(registry, "ssf_feedback_retention_deleted_total") == 2

    async def test_a_skipped_replica_does_not_report_a_backlog_it_never_looked_at(self):
        """N-1 replicas skip every pass by design; they know nothing."""
        registry = CollectorRegistry()
        repository = FakeRepository(delete_raises=RetentionLockUnavailable("held"), overdue=9)

        result = await _maintenance(repository, registry=registry).expire_once()

        assert result.skipped is True
        assert _value(registry, "ssf_feedback_retention_overdue") == 0

    async def test_a_count_that_fails_does_not_fail_the_pass(self):
        """The deletion already happened; losing the gauge must not undo it."""
        registry = CollectorRegistry()
        repository = FakeRepository(
            deleted=[uuid4()], overdue_raises=FeedbackStorageUnavailable("gone")
        )

        result = await _maintenance(repository, registry=registry).expire_once()

        assert result.deleted == 1
        assert result.failed is False


class TestOnlyOneReplicaReconcilesPerPass:
    """The claim is not a claim: it selects, and marks nothing.

    Retention already takes an advisory lock so exactly one replica deletes per
    pass. Reconciliation had no equivalent, so with N replicas every pending
    row was re-emitted N times. uniqExactState(event_id) absorbs that for
    counts and rates, but avgState has no distinct-by form -- migration 005
    says so -- and the rating and NPS averages skew by a factor that scales
    with replica count on any pass that finds a backlog.
    """

    async def test_the_pass_is_taken_under_a_lock(self):
        repository = FakeRepository([_pending()])

        await _maintenance(repository).reconcile_once()

        assert repository.lock_keys == [RECONCILIATION_LOCK_KEY]

    async def test_the_lock_is_not_the_one_retention_uses(self):
        """Sharing a key would make the two passes exclude each other, and
        retention runs hourly while reconciliation runs every five minutes."""
        assert RECONCILIATION_LOCK_KEY != RETENTION_LOCK_KEY

    async def test_a_replica_that_loses_the_lock_emits_nothing(self):
        row = _pending()
        repository = FakeRepository([row], lock_held=True)
        telemetry = FakeTelemetry()

        result = await _maintenance(repository, telemetry).reconcile_once()

        assert telemetry.calls == []
        assert result.skipped is True
        assert result.recovered == 0

    async def test_losing_the_lock_is_not_a_failure(self):
        """With N replicas, N-1 skip every pass by design."""
        registry = CollectorRegistry()
        repository = FakeRepository([_pending()], lock_held=True)

        await _maintenance(repository, registry=registry).reconcile_once()

        assert (
            _value(registry, "ssf_feedback_maintenance_failures_total", job="reconciliation") == 0
        )

    async def test_a_skipped_replica_does_not_publish_a_backlog_it_never_read(self):
        registry = CollectorRegistry()
        repository = FakeRepository([_pending(), _pending()], lock_held=True)

        await _maintenance(repository, registry=registry).reconcile_once()

        assert _value(registry, "ssf_feedback_reconciliation_backlog") == 0


class TestASkippedPassDoesNotLeaveAStaleGauge:
    """A Prometheus gauge keeps its last value; not setting it clears nothing.

    Concretely, with two replicas: A wins a pass while 150 rows are pending and
    publishes 150. B wins every pass afterwards and drains the backlog to zero.
    A's series still reads 150, so an unaggregated alert on it latches and
    never clears. Exactly one replica does the work each pass, so the losers
    publish zero and the alerts aggregate with max() -- the winner's number
    always survives that.
    """

    async def test_a_skipped_reconciliation_publishes_zero_not_the_last_backlog(self):
        registry = CollectorRegistry()
        winner = FakeRepository([_pending(), _pending()])
        await _maintenance(winner, registry=registry).reconcile_once()
        assert _value(registry, "ssf_feedback_reconciliation_backlog") == 2

        loser = FakeRepository([_pending(), _pending()], lock_held=True)
        await _maintenance(loser, registry=registry).reconcile_once()

        assert _value(registry, "ssf_feedback_reconciliation_backlog") == 0

    async def test_a_skipped_retention_publishes_zero_not_the_last_overdue(self):
        registry = CollectorRegistry()
        winner = FakeRepository(deleted=[uuid4()], overdue=9)
        await _maintenance(winner, registry=registry).expire_once()
        assert _value(registry, "ssf_feedback_retention_overdue") == 9

        loser = FakeRepository(delete_raises=RetentionLockUnavailable("held"), overdue=9)
        await _maintenance(loser, registry=registry).expire_once()

        assert _value(registry, "ssf_feedback_retention_overdue") == 0
